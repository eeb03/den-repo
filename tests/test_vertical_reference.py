"""
The vertical reference model: what can and cannot be said about Z.

Site 01 is the modelling case. The conclusion reached there was
REGISTRATION_REQUIRED, and these tests pin both the conclusion and the
evidence that produced it, so neither can drift into a fabricated absolute
elevation later.

The three states that must stay distinct:

    measured GPR time  ->  derived GPR depth  ->  absolute elevation
                                                  (NOT AVAILABLE)
    AHN surface elevation  ->  absolute elevation
                               (NOT AVAILABLE: datum undeclared)
"""
import glob
import math
import os
import struct
from pathlib import Path

import pytest

from converters.geotiff_converter import GeoTIFFConverter
from converters.segy_converter import SEGYConverter
from fusion import vertical_reference as vr
from schemas.spatial import (
    AcquisitionElevationDatum, AxisKind, CRSProvenance, VerticalAxis, VerticalDatum,
    VerticalRelationshipKind,
)
from schemas.subterra_record import SensorType
from schemas.survey_frame import SurveyFrame

AHN = Path("datasets/raw/pdok_ahn/dtm_05m/AHN_DTM_05m_site01.tif")
GPR_DIR = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted/01")
INGV = "datasets/downloads/multiline_C1T_0001_0002_extracted"

REAL = pytest.mark.skipif(not (AHN.exists() and GPR_DIR.exists()),
                          reason="site-01 AHN or GPR data not present locally")


@pytest.fixture(scope="module")
def gpr_frame():
    files = sorted(glob.glob(str(GPR_DIR / "**/*.sgy"), recursive=True), key=os.path.getsize)
    return SEGYConverter().load(Path(files[0]), dataset_id="4tu01",
                                sensor_type=SensorType.GPR,
                                coordinate_encoding="ieee_nmea")


@pytest.fixture(scope="module")
def ahn_frame():
    return GeoTIFFConverter().load(AHN, dataset_id="ahn", sensor_type=SensorType.LIDAR,
                                   stride=60, reproject=False)


def _frame(axis, fid="f", acquisition_elevation_datum=None):
    return SurveyFrame.model_construct(
        frame_id=fid, dataset_id="d", modality=SensorType.GPR, source_format="x",
        spatial_ref=None, vertical_axis=axis, assumptions=[], source_metadata={},
        acquisition_elevation_datum=acquisition_elevation_datum)


def _axis(kind, origin, datum=None, conversion=None):
    return VerticalAxis(kind=kind, units="m", origin=origin, positive_down=True,
                        conversion=conversion, vertical_datum=datum)


NAP = VerticalDatum(code="NAP", provenance=CRSProvenance.SUPPLIED_BY_CALLER, name="PDOK docs")


# --- the datum vocabulary refuses undeclared codes ---

def test_a_datum_code_requires_a_provenance():
    with pytest.raises(ValueError) as e:
        VerticalDatum(code="NAP")
    assert "nobody declared is not a datum" in str(e.value)


def test_absence_is_the_default():
    d = VerticalDatum()
    assert d.code is None and d.provenance == CRSProvenance.NONE


# --- what each real dataset actually declares ---

@REAL
def test_ahn_declares_no_vertical_datum_by_default(ahn_frame):
    """The GeoTIFF has no VERT_CS, no band units, no band description."""
    axis = ahn_frame.frames[0].vertical_axis
    assert axis.kind == AxisKind.ELEVATION_M
    assert axis.vertical_datum is None


@REAL
def test_a_caller_may_declare_ahns_documented_datum():
    res = GeoTIFFConverter().load(AHN, dataset_id="ahn", sensor_type=SensorType.LIDAR,
                                  stride=100, reproject=False, vertical_datum="NAP")
    d = res.frames[0].vertical_axis.vertical_datum
    assert d.code == "NAP"
    assert d.provenance == CRSProvenance.SUPPLIED_BY_CALLER   # never declared_by_source
    assert "declares no vertical CRS" in d.name


@REAL
def test_gpr_exposes_its_acquisition_elevation_without_claiming_a_datum(gpr_frame):
    r = gpr_frame.records[0]
    assert r.elevation is not None
    assert 25.0 < r.elevation < 35.0                      # metres, site 01
    assert r.metadata["acquisition_elevation_datum"] == "UNDECLARED"
    assert gpr_frame.frames[0].vertical_axis.vertical_datum is None
    a = gpr_frame.frames[0].assumption("acquisition_elevation_datum")
    assert a is not None and a.verified is False
    assert "consistent with, not a declaration of" in a.basis


@REAL
def test_the_gpr_depth_axis_origin_is_not_the_ground_surface(gpr_frame):
    """Depth 0 is instrument time-zero, so it is not where AHN's surface is."""
    assert gpr_frame.frames[0].vertical_axis.origin == "instrument time-zero at each trace"


@pytest.mark.skipif(not Path(INGV).exists(), reason="INGV data not present")
def test_the_default_segy_path_still_reports_no_elevation():
    """
    INGV DOES populate the elevation fields as standard scaled integers
    (482.88 m via ElevationScalar -100). Reading them on the default path
    would change pinned records, so elevation is gated to the ieee_nmea
    declaration. This guards that gate.
    """
    f = sorted(glob.glob(INGV + "/*.SGY"))[0]
    recs = SEGYConverter().load(Path(f), dataset_id="ingv",
                                sensor_type=SensorType.GPR).records
    assert all(r.elevation is None for r in recs[:100])


# --- the assessment on real site-01 data ---

@REAL
def test_site01_conclusion_is_registration_required(gpr_frame, ahn_frame):
    rel = vr.assess(gpr_frame.frames[0], ahn_frame.frames[0])
    assert rel.kind == VerticalRelationshipKind.REGISTRATION_REQUIRED
    assert rel.absolute_elevation_available is False


@REAL
def test_the_three_missing_pieces_are_named(gpr_frame, ahn_frame):
    rel = vr.assess(gpr_frame.frames[0], ahn_frame.frames[0])
    joined = " ".join(rel.missing)
    assert "vertical datum for the acquisition elevations" in joined
    assert "vertical datum for the surface model" in joined
    assert "offset from the depth-axis origin to the ground" in joined


@REAL
def test_declaring_only_the_surface_datum_does_not_unlock_absolute_z(gpr_frame):
    res = GeoTIFFConverter().load(AHN, dataset_id="ahn", sensor_type=SensorType.LIDAR,
                                  stride=100, reproject=False, vertical_datum="NAP")
    rel = vr.assess(gpr_frame.frames[0], res.frames[0])
    assert rel.kind == VerticalRelationshipKind.REGISTRATION_REQUIRED
    assert rel.absolute_elevation_available is False
    assert not any("surface model" in m for m in rel.missing)   # that one is satisfied
    assert any("acquisition elevations" in m for m in rel.missing)


@REAL
def test_supplying_a_velocity_creates_depth_but_not_elevation(gpr_frame):
    """Depth is a different question from Z, and answering one does not answer the other."""
    files = sorted(glob.glob(str(GPR_DIR / "**/*.sgy"), recursive=True), key=os.path.getsize)
    withv = SEGYConverter().load(Path(files[0]), dataset_id="4tu01",
                                 sensor_type=SensorType.GPR,
                                 coordinate_encoding="ieee_nmea", velocity_m_per_ns=0.1)
    assert withv.records[0].depth is not None
    res = GeoTIFFConverter().load(AHN, dataset_id="ahn", sensor_type=SensorType.LIDAR,
                                  stride=100, reproject=False, vertical_datum="NAP")
    rel = vr.assess(withv.frames[0], res.frames[0])
    assert rel.absolute_elevation_available is False


# --- the evidence behind the conclusion, pinned ---

@REAL
def test_the_residual_is_systematic_yet_still_does_not_declare_a_datum():
    """
    The measurement behind the conclusion, RE-MEASURED against the corrected
    site-01 window.

    An earlier run against a truncated window (one tile instead of the two
    that cover the site) reported a 1.761 m spread of per-activity means and
    concluded the offset could not be a fixed one. With complete coverage --
    24,013 traces instead of 18,299 -- the residual is SYSTEMATIC: about
    -0.51 m with a per-activity spread of roughly 0.26 m. That earlier spread
    was largely an artefact of edge and nodata sampling.

    The corrected evidence points MORE strongly toward a shared datum, not
    less. It still does not establish one: no source declares a vertical
    datum, the -0.51 m constant is unexplained (an antenna-height correction,
    terrain change, or a geoid-model difference would all look like this), and
    the depth axis still starts at instrument time-zero rather than the ground.
    This test pins the numbers AND the fact that they change nothing.
    """
    rasterio = pytest.importorskip("rasterio")
    from rasterio.warp import transform
    import collections
    import statistics

    def nmea(v):
        d = int(abs(v) // 100)
        out = d + (abs(v) - 100 * d) / 60.0
        return -out if v < 0 else out

    per = collections.defaultdict(list)
    for f in sorted(glob.glob(str(GPR_DIR / "**/*.sgy"), recursive=True)):
        act = os.path.relpath(f, GPR_DIR).split(os.sep)[1]
        d = open(f, "rb").read()
        ns = struct.unpack_from("<h", d, 3200 + 20)[0]
        tr = 240 + ns * 2
        body = len(d) - 3600
        if tr <= 0 or body % tr:
            continue
        for i in range(0, body // tr, 3):
            h = d[3600 + i * tr: 3600 + i * tr + 240]
            g = lambda o: struct.unpack_from("<f", h, o)[0]      # noqa: E731
            e, fx, fy = g(40), g(72), g(76)
            if not all(map(math.isfinite, (e, fx, fy))) or fx == 0 or fy == 0:
                continue
            per[act].append((nmea(fy), nmea(fx), e))

    means, everything = [], []
    with rasterio.open(AHN) as ds:
        for pts in per.values():
            xs, ys = transform("EPSG:4326", "EPSG:28992",
                               [p[1] for p in pts], [p[0] for p in pts])
            vals = [v[0] for v in ds.sample(list(zip(xs, ys)))]
            diff = [p[2] - v for p, v in zip(pts, vals) if v is not None and v < 1e30]
            if len(diff) >= 20:
                means.append(statistics.fmean(diff))
                everything += diff

    assert len(means) >= 5, "expected several activities in site 01"
    overall = statistics.fmean(everything)
    assert -1.0 < overall < 0.0, f"residual moved to {overall:.3f} m"
    assert statistics.pstdev(everything) < 0.5
    assert max(means) - min(means) < 1.0, "per-activity means should now be tightly clustered"
    # ...and none of that declares a datum.
    assert not any(m is None for m in means)


# --- the classifier's other states ---

def test_a_fully_declared_and_ground_referenced_pair_is_absolute():
    sub = _frame(_axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP), "sub")
    sur = _frame(_axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP), "sur")
    rel = vr.assess(sub, sur)
    assert rel.kind == VerticalRelationshipKind.ABSOLUTE_ELEVATION
    assert rel.absolute_elevation_available is True
    assert rel.missing == []


# --- the acquisition-elevation route: a fallback when the axis is undeclared ---

WGS84_ELLIPSOIDAL = VerticalDatum(code="WGS84 ellipsoidal", provenance=CRSProvenance.SUPPLIED_BY_CALLER,
                                  name="direct written response from the dataset author")


def test_an_undeclared_axis_falls_back_to_a_matching_acquisition_elevation_datum():
    """The exact real-world case this route exists for: the 4TU GPR frame's
    axis (two-way time) declares no datum, but its acquisition elevation does."""
    sub = _frame(_axis(AxisKind.DEPTH_M, "ground surface at each trace"), "sub",
                acquisition_elevation_datum=AcquisitionElevationDatum(
                    datum=WGS84_ELLIPSOIDAL, field="SEG-Y bytes 45-48"))
    sur = _frame(_axis(AxisKind.ELEVATION_M, "raster band 1 value", WGS84_ELLIPSOIDAL), "sur")
    rel = vr.assess(sub, sur)
    assert rel.kind == VerticalRelationshipKind.ABSOLUTE_ELEVATION
    assert rel.missing == []
    assert any("acquisition elevation" in r for r in rel.reasons)


def test_a_declared_axis_datum_is_never_overridden_by_acquisition_elevation():
    """Additive, not a replacement: a declared (even if mismatched) axis
    datum stays authoritative -- an acquisition elevation never upgrades or
    silently relabels it."""
    sub = _frame(_axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP), "sub",
                acquisition_elevation_datum=AcquisitionElevationDatum(
                    datum=WGS84_ELLIPSOIDAL, field="SEG-Y bytes 45-48"))
    sur = _frame(_axis(AxisKind.ELEVATION_M, "raster band 1 value", WGS84_ELLIPSOIDAL), "sur")
    rel = vr.assess(sub, sur)
    # NAP (axis) vs WGS84 ellipsoidal (surface axis) still differ: the
    # matching acquisition elevation must not have been substituted in.
    assert rel.kind != VerticalRelationshipKind.ABSOLUTE_ELEVATION
    assert any("NAP" in r and "WGS84 ellipsoidal" in r for r in rel.reasons)


def test_acquisition_elevation_alone_does_not_resolve_a_mismatched_pair():
    sub = _frame(_axis(AxisKind.DEPTH_M, "ground surface at each trace"), "sub",
                acquisition_elevation_datum=AcquisitionElevationDatum(
                    datum=WGS84_ELLIPSOIDAL, field="SEG-Y bytes 45-48"))
    sur = _frame(_axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP), "sur")
    rel = vr.assess(sub, sur)
    assert rel.kind != VerticalRelationshipKind.ABSOLUTE_ELEVATION
    assert any("differ" in r for r in rel.reasons)


def test_neither_axis_nor_acquisition_elevation_declared_is_still_undeclared():
    sub = _frame(_axis(AxisKind.DEPTH_M, "ground surface at each trace"), "sub")
    sur = _frame(_axis(AxisKind.ELEVATION_M, "raster band 1 value"), "sur")
    rel = vr.assess(sub, sur)
    assert rel.kind != VerticalRelationshipKind.ABSOLUTE_ELEVATION
    assert any("declares no vertical datum" in r for r in rel.reasons)


def test_ground_referenced_but_undeclared_datum_is_relative_depth_only():
    sub = _frame(_axis(AxisKind.DEPTH_M, "ground surface at each trace"), "sub")
    sur = _frame(_axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP), "sur")
    rel = vr.assess(sub, sur)
    assert rel.kind == VerticalRelationshipKind.RELATIVE_DEPTH_ONLY
    assert rel.absolute_elevation_available is False


def test_conflicting_declared_datums_require_a_transformation():
    other = VerticalDatum(code="EPSG:5709", provenance=CRSProvenance.SUPPLIED_BY_CALLER)
    sub = _frame(_axis(AxisKind.DEPTH_M, "ground surface at each trace", other), "sub")
    sur = _frame(_axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP), "sur")
    rel = vr.assess(sub, sur)
    assert rel.absolute_elevation_available is False
    assert any("transformation between" in m for m in rel.missing)


def test_a_surface_frame_without_an_elevation_axis_is_unrelated():
    sub = _frame(_axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP), "sub")
    sur = _frame(_axis(AxisKind.TWO_WAY_TIME_NS, "instrument time-zero"), "sur")
    rel = vr.assess(sub, sur)
    assert rel.kind == VerticalRelationshipKind.UNRELATED


def test_a_time_axis_without_a_velocity_names_the_velocity_as_missing():
    sub = _frame(_axis(AxisKind.TWO_WAY_TIME_NS, "ground surface at each trace", NAP), "sub")
    sur = _frame(_axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP), "sur")
    rel = vr.assess(sub, sur)
    assert any("caller-supplied velocity" in m for m in rel.missing)
    assert rel.absolute_elevation_available is False


def test_the_module_exposes_no_way_to_produce_an_absolute_z():
    """
    Deliberate: for every dataset held, an absolute elevation cannot be
    computed, so no function offers one. This guards against a helper being
    added that quietly fills the gap with an assumption.
    """
    public = {n for n in dir(vr) if not n.startswith("_")}
    for banned in ("absolute_elevation", "to_elevation", "compute_z", "elevation_of"):
        assert banned not in public


def test_describe_is_readable_and_lists_what_is_missing():
    sub = _frame(_axis(AxisKind.DEPTH_M, "instrument time-zero at each trace"), "sub")
    sur = _frame(_axis(AxisKind.ELEVATION_M, "raster band 1 value"), "sur")
    text = vr.assess(sub, sur).describe()
    assert "registration_required" in text
    assert "missing:" in text
