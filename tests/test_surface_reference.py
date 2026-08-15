"""
The surface anchor: declaring what a raster band means.

WHY THIS STAGE EXISTS. Stage 8 established that a vertical reference needs a
surface model with an elevation axis and a declared datum, and reported that no
dataset held had one. The reason turned out not to be missing evidence: the
COP30 DEM's band 1 IS elevation in metres. Two defects in the GeoTIFF converter
made it unusable.

  1. The elevation axis was INFERRED FROM THE DECLARED MODALITY -- a raster
     called lidar got `AxisKind.ELEVATION_M`, one called satellite got
     `AxisKind.NONE`. The COP30 DEM was ingested as satellite, so it could never
     anchor anything; and an AHN raster got an elevation axis nobody had
     actually asserted, which is the same category error pointing the other way.

  2. `record.elevation` was never set by ANY raster ingest. So even a frame
     whose axis said ELEVATION_M produced records with no elevation, and
     `assess_surface` saw nothing to anchor with.

Neither is a research problem, and fixing them invents nothing: the numbers were
already in the file and already in `signal`. What was missing was somebody
saying what they mean, and a converter that recorded who said it.
"""
import numpy as np
import pytest

from converters.geotiff_converter import GeoTIFFConverter
from schemas.spatial import AxisKind, CRSProvenance
from schemas.spatial_reference import SpatialDimension, assess_spatial_reference
from schemas.subterra_record import SensorType

rasterio = pytest.importorskip("rasterio", reason="rasterio is needed to write a test raster")


@pytest.fixture
def raster(tmp_path):
    """
    A tiny GeoTIFF whose band 1 holds plausible elevations.

    Constructed, not measured -- it exists to exercise the declaration
    machinery. Nothing derived from it is presented as a survey.
    """
    from rasterio.transform import from_origin

    path = tmp_path / "surface.tif"
    values = np.arange(36, dtype="float32").reshape(6, 6) + 20.0
    with rasterio.open(
        path, "w", driver="GTiff", height=6, width=6, count=1,
        dtype="float32", crs="EPSG:4326", transform=from_origin(4.3, 52.0, 0.0001, 0.0001),
    ) as ds:
        ds.write(values, 1)
    return path


def convert(path, sensor_type=SensorType.SATELLITE, **kwargs):
    return GeoTIFFConverter().load(
        path, dataset_id="d", sensor_type=sensor_type, stride=1, **kwargs)


def frame_of(result):
    return result.frames[0]


def assumption(frame, key):
    return next(a for a in frame.assumptions if a.key == key)


# ---------------------------------------------------------------------------
# the defect, reproduced
# ---------------------------------------------------------------------------

def test_a_dem_ingested_as_satellite_used_to_have_no_elevation_axis(raster):
    """The COP30 case: no declaration, and the modality says satellite."""
    result = convert(raster)
    assert frame_of(result).vertical_axis.kind == AxisKind.NONE
    assert all(r.elevation is None for r in result.records)


# ---------------------------------------------------------------------------
# the declaration
# ---------------------------------------------------------------------------

def test_declaring_the_band_as_elevation_produces_an_elevation_axis(raster):
    result = convert(raster, band_is_elevation=True)
    axis = frame_of(result).vertical_axis

    assert axis.kind == AxisKind.ELEVATION_M
    assert axis.units == "m"


def test_declaring_the_band_as_elevation_puts_it_on_the_records(raster):
    """
    The half nobody noticed: an elevation axis with no elevations anchors
    nothing.
    """
    result = convert(raster, band_is_elevation=True)

    assert all(r.elevation is not None for r in result.records)
    assert {r.elevation for r in result.records} == {float(v) for v in
                                                     np.arange(36) + 20.0}


def test_the_band_value_is_kept_in_signal_either_way(raster):
    """Nothing is lost when the claim is absent, or later withdrawn."""
    declared = convert(raster, band_is_elevation=True)
    undeclared = convert(raster)

    assert [r.signal for r in declared.records] == [r.signal for r in undeclared.records]


def test_declaring_the_band_is_not_elevation_is_respected(raster):
    """A LiDAR raster whose band is intensity, not height."""
    result = convert(raster, sensor_type=SensorType.LIDAR, band_is_elevation=False)

    assert frame_of(result).vertical_axis.kind == AxisKind.NONE
    assert all(r.elevation is None for r in result.records)


def test_a_declaration_is_recorded_as_supplied_by_the_caller(raster):
    result = convert(raster, band_is_elevation=True)
    declared = assumption(frame_of(result), "band_is_elevation")

    assert declared.value is True
    assert "SUPPLIED BY CALLER" in declared.basis
    # Nothing checked the band against anything.
    assert declared.verified is False


def test_the_modality_fallback_is_recorded_as_an_inference(raster):
    """
    It used to pass silently as fact. A band of numbers is elevation,
    reflectance or temperature indistinguishably.
    """
    result = convert(raster, sensor_type=SensorType.LIDAR)
    inferred = assumption(frame_of(result), "band_is_elevation")

    assert inferred.value is True
    assert "INFERRED" in inferred.basis
    assert "not something the raster said" in inferred.basis
    assert inferred.verified is False


def test_the_existing_modality_behaviour_is_unchanged_when_nobody_declares(raster):
    """No regression for callers that never asked for this."""
    assert frame_of(convert(raster, sensor_type=SensorType.LIDAR)).vertical_axis.kind == \
        AxisKind.ELEVATION_M
    assert frame_of(convert(raster, sensor_type=SensorType.SATELLITE)).vertical_axis.kind == \
        AxisKind.NONE


def test_a_lidar_raster_now_also_carries_elevations(raster):
    """The `record.elevation` defect applied to every raster, not just DEMs."""
    result = convert(raster, sensor_type=SensorType.LIDAR)
    assert all(r.elevation is not None for r in result.records)


# ---------------------------------------------------------------------------
# what it unblocks, and what it does not
# ---------------------------------------------------------------------------

def test_a_declared_band_alone_is_not_yet_a_usable_surface(raster):
    """
    An elevation axis without a declared datum still anchors nothing. Stage 8
    decides that, and it is unchanged.
    """
    result = convert(raster, band_is_elevation=True)
    assessment = assess_spatial_reference(
        "d", [], [], surface_frames=[frame_of(result)])

    surface = assessment.dimension(SpatialDimension.SURFACE_REFERENCE)
    assert surface.state == "unvalidated"
    assert any("declares no vertical datum" in p for p in surface.detail["problems"])


def test_a_declared_band_and_a_declared_datum_make_a_usable_surface(raster):
    """
    The first configuration in this platform's history that reaches
    `surface_reference: available`.
    """
    result = convert(raster, band_is_elevation=True, vertical_datum="EGM96")
    frame = frame_of(result)
    assert frame.vertical_axis.vertical_datum.code == "EGM96"
    assert frame.vertical_axis.vertical_datum.provenance == CRSProvenance.SUPPLIED_BY_CALLER

    assessment = assess_spatial_reference("d", [], [], surface_frames=[frame])
    assert assessment.dimension(SpatialDimension.SURFACE_REFERENCE).state == "available"


def test_a_usable_surface_does_not_by_itself_register_a_survey_vertically(raster):
    """
    THE HONEST LIMIT OF THIS STAGE. An anchor is one of three things an absolute
    elevation needs; the depth-axis origin and the subsurface datum are still
    required, and no held GPR frame has them.
    """
    from fusion.vertical_reference import assess
    from schemas.spatial import VerticalAxis

    surface = frame_of(convert(raster, band_is_elevation=True, vertical_datum="EGM96"))

    class _Sub:
        frame_id = "gpr:line1"
        vertical_axis = VerticalAxis(
            kind=AxisKind.DEPTH_M, units="m", origin="instrument time zero",
            positive_down=True, conversion={"method": "constant_velocity", "v": 0.1})

    relationship = assess(_Sub(), surface)
    assert relationship.absolute_elevation_available is False
    assert any("ground surface" in r for r in relationship.reasons)


def test_nothing_infers_a_datum_from_a_declared_elevation(raster):
    """Saying the band is elevation says nothing about what it is measured from."""
    frame = frame_of(convert(raster, band_is_elevation=True))
    assert frame.vertical_axis.vertical_datum is None


# ---------------------------------------------------------------------------
# ingest options at the acquisition boundary
# ---------------------------------------------------------------------------

def test_an_option_the_format_cannot_use_is_refused():
    """
    Recording a declaration for a format that ignores it would be provenance
    for an effect that never happened.
    """
    from fastapi import HTTPException

    from api import acquisition
    from api.routes.imports import AcceptRequest
    from database.models import ImportJob

    job = ImportJob(id="j", identification={"detected_format": "csv"})
    with pytest.raises(HTTPException) as exc:
        acquisition.validated_ingest_options(job, AcceptRequest(band_is_elevation=True))
    assert "cannot be applied to a csv file" in exc.value.detail


def test_an_option_the_format_accepts_is_kept():
    from api import acquisition
    from api.routes.imports import AcceptRequest
    from database.models import ImportJob

    job = ImportJob(id="j", identification={"detected_format": "geotiff"})
    assert acquisition.validated_ingest_options(
        job, AcceptRequest(band_is_elevation=True)) == {"band_is_elevation": True}


def test_no_options_is_not_an_error():
    from api import acquisition
    from api.routes.imports import AcceptRequest
    from database.models import ImportJob

    job = ImportJob(id="j", identification={"detected_format": "geotiff"})
    assert acquisition.validated_ingest_options(job, None) == {}
    assert acquisition.validated_ingest_options(job, AcceptRequest()) == {}


def test_a_surface_only_dataset_still_names_what_blocks_its_registration():
    """
    Found by browser verification. A DEM with a ready horizontal reference and a
    declared datum reported 3D reconstruction blocked with an EMPTY `missing`
    list -- a blocker nobody could act on, which is the one invariant every
    other branch of the assessment maintains.
    """
    from fusion.vertical_reference import assess
    from schemas.dataset_report import (
        Capability, CandidateSummary, QualityReport, assess_readiness,
        build_horizontal, build_vertical, build_volume,
    )
    from schemas.spatial import (
        CRSKind, CRSProvenance, GeographicPosition, SpatialRef, VerticalAxis, VerticalDatum,
    )
    from schemas.subterra_record import SubterraRecord
    from schemas.survey_frame import SurveyFrame

    surface = SurveyFrame(
        frame_id="dem:tile", dataset_id="d", modality=SensorType.SATELLITE,
        source_format="geotiff", n_positions=4,
        spatial_ref=SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                               crs_provenance=CRSProvenance.DECLARED_BY_SOURCE),
        vertical_axis=VerticalAxis(
            kind=AxisKind.ELEVATION_M, units="m", origin="raster band 1 value",
            positive_down=False,
            vertical_datum=VerticalDatum(code="EGM2008",
                                         provenance=CRSProvenance.SUPPLIED_BY_CALLER,
                                         name="EGM2008")))
    records = [
        SubterraRecord(dataset_id="d", sensor_type=SensorType.SATELLITE,
                       position=GeographicPosition(lat=45.96 + i * 1e-4, lon=25.87),
                       latitude=45.96 + i * 1e-4, longitude=25.87,
                       frame_id="dem:tile", elevation=600.0 + i, signal=[600.0 + i])
        for i in range(4)
    ]

    vertical = build_vertical([surface], assess=assess)
    assert vertical.missing, "a surface-only dataset must say what registration needs"

    readiness = assess_readiness(
        build_volume(records, [surface]), build_horizontal(records, [surface]),
        vertical, QualityReport(), CandidateSummary())
    for capability in readiness:
        if capability.readiness.value != "ready":
            assert capability.missing, f"{capability.capability} blocked with nothing to act on"
