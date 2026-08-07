"""
AHN surface coverage across all 13 4TU GPR sites.

A breadth milestone: the site-01 mechanism, run everywhere, proving that
CRS-aware fusion works on real data at more than one location and that the
position kinds stay separated when four datasets of three different kinds
are fused together.

These tests assert nothing vertical beyond what the files declare, which is
nothing. Every window's elevation datum is UNDECLARED and stays that way --
see docs/vertical-reference-site01.md.
"""
import glob
import json
import os
from pathlib import Path

import pytest

from converters.geotiff_converter import GeoTIFFConverter
from converters.segy_converter import SEGYConverter
from fusion import vertical_reference as vr
from fusion.sensor_fusion import (
    fuse_datasets, multimodal_only, partition_by_spatial_ref,
)
from schemas.spatial import CRSKind, CRSProvenance, VerticalRelationshipKind
from schemas.subterra_record import SensorType

AHN_DIR = Path("datasets/raw/pdok_ahn/dtm_05m")
GPR_ROOT = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted")

REAL = pytest.mark.skipif(not (AHN_DIR.exists() and GPR_ROOT.exists()),
                          reason="AHN windows or 4TU data not present locally")

EXPECTED_SITES = {"01", "02", "03", "04", "05", "06", "07", "08", "09",
                  "010", "011", "012", "013"}


def _windows():
    return sorted(AHN_DIR.glob("AHN_DTM_05m_site*.tif"))


def _site_of(path: Path) -> str:
    return path.stem.replace("AHN_DTM_05m_site", "")


# --- coverage and provenance ---

@REAL
def test_every_gpr_site_has_a_surface_window():
    assert {_site_of(p) for p in _windows()} == EXPECTED_SITES


@REAL
def test_every_window_has_a_provenance_record_matching_its_bytes():
    import hashlib
    for tif in _windows():
        site = _site_of(tif)
        rec = json.loads((AHN_DIR / f"PROVENANCE_site{site}.json").read_text())
        assert rec["local_file"] == tif.name
        assert rec["local_bytes"] == tif.stat().st_size
        assert rec["sha256"] == hashlib.sha256(tif.read_bytes()).hexdigest()


@REAL
def test_provenance_records_the_required_fields():
    for tif in _windows():
        rec = json.loads((AHN_DIR / f"PROVENANCE_site{_site_of(tif)}.json").read_text())
        assert rec["license"] == "CC0-1.0"
        assert rec["crs"]["code"] == "EPSG:28992"
        assert rec["crs"]["provenance"] == "declared_by_source"
        assert rec["crs"]["inferred"] is False
        assert rec["resolution_m"] == 0.5
        assert rec["acquired_utc"]
        assert rec["source_tiles"]                       # which tiles it came from
        assert rec["spatial_extent_rd_epsg28992"]["x"][0] < \
            rec["spatial_extent_rd_epsg28992"]["x"][1]


@REAL
def test_provenance_states_the_vertical_unknowns_rather_than_a_datum():
    """The milestone's hard rule: no vertical datum is invented anywhere."""
    for tif in _windows():
        rec = json.loads((AHN_DIR / f"PROVENANCE_site{_site_of(tif)}.json").read_text())
        v = rec["vertical_metadata"]
        assert v["vertical_crs_in_file"] is None
        assert v["band_units_in_file"] is None
        assert "NOT the GeoTIFF" in v["documented_datum_source"]
        assert "NOT STATED" in v["acquisition_epoch"]
        assert rec["elevation_datum"] == "UNDECLARED"
        assert any("not declared by the file" in u for u in rec["unknowns"])


@REAL
def test_the_window_covers_the_measured_gpr_extent_it_was_chosen_for():
    """Compatibility is spatial, and recorded as such for every site."""
    for tif in _windows():
        rec = json.loads((AHN_DIR / f"PROVENANCE_site{_site_of(tif)}.json").read_text())
        gpr = rec["matched_gpr_site"]["gpr_extent_rd_epsg28992"]
        win = rec["spatial_extent_rd_epsg28992"]
        assert win["x"][0] <= gpr["x"][0] and win["x"][1] >= gpr["x"][1]
        assert win["y"][0] <= gpr["y"][0] and win["y"][1] >= gpr["y"][1]


# --- what each window declares once ingested ---

@REAL
@pytest.mark.parametrize("site", sorted(EXPECTED_SITES))
def test_each_window_ingests_with_a_declared_projected_crs(site):
    tif = AHN_DIR / f"AHN_DTM_05m_site{site}.tif"
    res = GeoTIFFConverter().load(tif, dataset_id=f"ahn{site}",
                                  sensor_type=SensorType.LIDAR, stride=200,
                                  reproject=False)
    ref = res.frames[0].spatial_ref
    assert ref.kind == CRSKind.PROJECTED
    assert ref.code == "EPSG:28992"
    assert ref.crs_provenance == CRSProvenance.DECLARED_BY_SOURCE
    assert res.records[0].position.kind == "projected"
    assert res.records[0].latitude is None
    # and no vertical datum is claimed
    assert res.frames[0].vertical_axis.vertical_datum is None


@REAL
def test_windows_carry_real_and_varied_elevations():
    """Guards the mosaic bug that produced all-zero rasters."""
    seen = []
    for site in ("01", "08", "010"):
        res = GeoTIFFConverter().load(AHN_DIR / f"AHN_DTM_05m_site{site}.tif",
                                      dataset_id="a", sensor_type=SensorType.LIDAR,
                                      stride=100, reproject=False)
        vals = [r.signal[0] for r in res.records]
        assert len(set(vals)) > 5, f"site {site} elevations are uniform"
        assert all(-10.0 < v < 100.0 for v in vals)
        seen += vals
    assert max(seen) - min(seen) > 5.0          # genuine relief across sites


# --- CRS-aware fusion, per site, on real data ---

@REAL
@pytest.mark.parametrize("site", sorted(EXPECTED_SITES))
def test_each_site_fuses_gpr_with_its_own_surface(site):
    ahn = GeoTIFFConverter().load(AHN_DIR / f"AHN_DTM_05m_site{site}.tif",
                                  dataset_id=f"ahn{site}", sensor_type=SensorType.LIDAR,
                                  stride=30, reproject=False)
    files = sorted(glob.glob(str(GPR_ROOT / site / "**/*.sgy"), recursive=True),
                   key=os.path.getsize)[:1]
    gpr = SEGYConverter().load(Path(files[0]), dataset_id=f"gpr{site}",
                               sensor_type=SensorType.GPR,
                               coordinate_encoding="ieee_nmea")
    frames = ahn.frames + gpr.frames
    multi = multimodal_only(fuse_datasets(ahn.records + gpr.records,
                                          radius_m=30.0, frames=frames))
    assert multi, f"site {site} produced no multimodal sample"
    s = multi[0]
    assert sorted(s.sensor_types) == ["gpr", "lidar"]
    assert s.has_geographic_centre
    assert s.n_reprojected > 0                  # the AHN members are derived
    assert 50.0 < s.center_lat < 54.0 and 3.0 < s.center_lon < 7.5


@REAL
def test_without_frames_no_site_fuses():
    """The declared CRS is what makes it work; nothing infers one."""
    site = "04"
    ahn = GeoTIFFConverter().load(AHN_DIR / f"AHN_DTM_05m_site{site}.tif",
                                  dataset_id="a", sensor_type=SensorType.LIDAR,
                                  stride=60, reproject=False)
    files = sorted(glob.glob(str(GPR_ROOT / site / "**/*.sgy"), recursive=True),
                   key=os.path.getsize)[:1]
    gpr = SEGYConverter().load(Path(files[0]), dataset_id="g",
                               sensor_type=SensorType.GPR,
                               coordinate_encoding="ieee_nmea")
    assert multimodal_only(fuse_datasets(ahn.records + gpr.records, radius_m=30.0)) == []


# --- position kinds stay separated ---

@REAL
def test_odometry_never_enters_a_geographic_sample():
    """
    Four datasets, three position kinds, one fusion call: projected-with-CRS
    joins the geographic pool, odometry stays out with its reason.
    """
    from converters.ids_dt_converter import IDSDTConverter
    from converters.mala_converter import MALAConverter
    ahn = GeoTIFFConverter().load(AHN_DIR / "AHN_DTM_05m_site01.tif", dataset_id="ahn",
                                  sensor_type=SensorType.LIDAR, stride=60, reproject=False)
    f = sorted(glob.glob(str(GPR_ROOT / "01" / "**/*.sgy"), recursive=True),
               key=os.path.getsize)[0]
    gpr = SEGYConverter().load(Path(f), dataset_id="gpr", sensor_type=SensorType.GPR,
                               coordinate_encoding="ieee_nmea")
    records = ahn.records + gpr.records
    frames = ahn.frames + gpr.frames

    mala = sorted(glob.glob("datasets/raw/zenodo/8253179/extracted/**/*.rd3", recursive=True))
    if mala:
        m = MALAConverter().load(Path(mala[0]), dataset_id="hill", sensor_type=SensorType.GPR)
        records += m.records[:2000]
        frames += m.frames
    ids = sorted(glob.glob("datasets/raw/zenodo/14637589/**/*.dt", recursive=True))
    if ids:
        d = IDSDTConverter().load(Path(ids[0]), dataset_id="gz", sensor_type=SensorType.GPR)
        records += d.records[:2000]
        frames += d.frames

    kinds = {p.kind: p for p in partition_by_spatial_ref(records, frames=frames)}
    assert kinds["geographic"].fusable is True
    if mala or ids:
        assert kinds["odometry"].fusable is False
        assert "own line only" in kinds["odometry"].reason
    for s in multimodal_only(fuse_datasets(records, radius_m=30.0, frames=frames)):
        assert "hill" not in s.dataset_ids and "gz" not in s.dataset_ids


# --- the vertical conclusion holds at every site ---

@REAL
@pytest.mark.parametrize("site", ["01", "05", "09", "013"])
def test_no_site_yields_an_absolute_elevation(site):
    """Breadth does not change the vertical conclusion: still registration_required."""
    ahn = GeoTIFFConverter().load(AHN_DIR / f"AHN_DTM_05m_site{site}.tif",
                                  dataset_id="a", sensor_type=SensorType.LIDAR,
                                  stride=200, reproject=False)
    files = sorted(glob.glob(str(GPR_ROOT / site / "**/*.sgy"), recursive=True),
                   key=os.path.getsize)[:1]
    gpr = SEGYConverter().load(Path(files[0]), dataset_id="g", sensor_type=SensorType.GPR,
                               coordinate_encoding="ieee_nmea", velocity_m_per_ns=0.1)
    rel = vr.assess(gpr.frames[0], ahn.frames[0])
    assert rel.kind == VerticalRelationshipKind.REGISTRATION_REQUIRED
    assert rel.absolute_elevation_available is False
