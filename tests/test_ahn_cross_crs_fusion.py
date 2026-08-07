"""
AHN (Tier 2.1): the first dataset on disk with a DECLARED PROJECTED CRS.

Until this milestone, cross-CRS fusion was tested only against fixtures --
nothing in the repository declared a projected CRS, so the transform path
had never run on real data. AHN does: the COG states EPSG:28992, the PDOK
ATOM feed states it, and the tile index states it.

What these tests pin:

1. **`reproject=False` preserves the declared CRS** instead of flattening
   it to WGS84 at ingest, and the default remains unchanged so no existing
   raster behaves differently.
2. **The transform happens in fusion, not at ingest**, through the existing
   `ingestion/crs_transform.py`, and the result is reported as derived via
   `FusionSample.n_reprojected`.
3. **Compatibility is established, never assumed.** A projected frame with
   no declared CRS stays excluded no matter how plausible its numbers, and
   no CRS is inferred from coordinate magnitude.
"""
from pathlib import Path

import pytest

from converters.geotiff_converter import GeoTIFFConverter
from fusion.sensor_fusion import (
    fuse_datasets, geographic_views, multimodal_only, non_fusable_partitions,
)
from schemas.spatial import CRSKind, CRSProvenance
from schemas.subterra_record import SensorType

AHN = Path("datasets/raw/pdok_ahn/dtm_05m/AHN_DTM_05m_site01.tif")
GPR_DIR = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted/01")

REAL_AHN = pytest.mark.skipif(not AHN.exists(), reason="AHN subset not present locally")
REAL_BOTH = pytest.mark.skipif(not (AHN.exists() and GPR_DIR.exists()),
                               reason="AHN subset or 4TU project 01 not present locally")

#: Measured from the real SEG-Y trace headers of 4TU project 01, then
#: transformed to EPSG:28992. Compatibility with AHN was established from
#: THIS, not from the fact that both are Dutch.
GPR_EXTENT_RD = {"x": (255012.8, 255228.5), "y": (473277.9, 473409.0)}


@pytest.fixture(scope="module")
def ahn_projected():
    """AHN in its own coordinates -- the case this milestone exists for."""
    return GeoTIFFConverter().load(AHN, dataset_id="ahn_dtm", sensor_type=SensorType.LIDAR,
                                   stride=20, reproject=False)


@pytest.fixture(scope="module")
def gpr_line():
    import glob
    import os
    from converters.segy_converter import SEGYConverter
    files = sorted(glob.glob(str(GPR_DIR / "**/*.sgy"), recursive=True), key=os.path.getsize)
    return SEGYConverter().load(Path(files[0]), dataset_id="4tu_site01",
                                sensor_type=SensorType.GPR,
                                coordinate_encoding="ieee_nmea")


# --- 1. the declared CRS survives ingest ---

@REAL_AHN
def test_ahn_declares_its_own_projected_crs(ahn_projected):
    ref = ahn_projected.frames[0].spatial_ref
    assert ref.kind == CRSKind.PROJECTED
    assert ref.code == "EPSG:28992"
    assert ref.crs_provenance == CRSProvenance.DECLARED_BY_SOURCE
    assert ref.horizontal_units == "m"


@REAL_AHN
def test_records_keep_native_easting_northing_and_no_fake_latlon(ahn_projected):
    r = ahn_projected.records[0]
    assert r.position.kind == "projected"
    assert r.latitude is None and r.longitude is None
    xs = [x.position.easting for x in ahn_projected.records]
    ys = [x.position.northing for x in ahn_projected.records]
    # Real RD New coordinates, not degrees.
    assert 254_000 < min(xs) < 256_000
    assert 473_000 < min(ys) < 474_000


@REAL_AHN
def test_no_transform_is_applied_at_ingest(ahn_projected):
    a = ahn_projected.frames[0].assumption("reprojection")
    assert a is not None and a.value == "not applied"
    assert "reported as derived" in a.basis


@REAL_AHN
def test_the_default_still_reprojects_eagerly():
    """The existing behaviour must not change for any other raster."""
    res = GeoTIFFConverter().load(AHN, dataset_id="ahn_wgs", sensor_type=SensorType.LIDAR,
                                  stride=40)
    assert res.frames[0].spatial_ref.kind == CRSKind.GEOGRAPHIC
    assert res.frames[0].spatial_ref.code == "EPSG:4326"
    assert res.records[0].position.kind == "geographic"
    assert res.frames[0].assumption("reprojection").value == "EPSG:28992 -> EPSG:4326"


def test_reproject_false_on_a_raster_with_no_crs_is_refused(tmp_path):
    """Nothing to declare, and nothing is inferred -- so it fails loudly."""
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    p = tmp_path / "nocrs.tif"
    with rasterio.open(p, "w", driver="GTiff", width=4, height=4, count=1,
                       dtype="float32") as ds:
        ds.write(np.ones((4, 4), dtype="float32"), 1)
    with pytest.raises(ValueError) as e:
        GeoTIFFConverter().load(p, dataset_id="ds", sensor_type=SensorType.LIDAR,
                                reproject=False)
    assert "declares no CRS" in str(e.value)
    assert "nothing is inferred here" in str(e.value)


# --- 2. spatial extent, established rather than assumed ---

@REAL_AHN
def test_ahn_subset_covers_the_measured_gpr_extent(ahn_projected):
    """
    Compatibility is a spatial fact, not a naming coincidence. Both are in
    EPSG:28992 here, so the comparison is apples to apples.
    """
    xs = [r.position.easting for r in ahn_projected.records]
    ys = [r.position.northing for r in ahn_projected.records]
    assert min(xs) <= GPR_EXTENT_RD["x"][0] and max(xs) >= GPR_EXTENT_RD["x"][1]
    assert min(ys) <= GPR_EXTENT_RD["y"][0] and max(ys) >= GPR_EXTENT_RD["y"][1]


@REAL_AHN
def test_elevations_are_plausible_and_nodata_is_dropped(ahn_projected):
    vals = [r.signal[0] for r in ahn_projected.records]
    assert all(v < 1e30 for v in vals)          # the float-max nodata is filtered
    assert 20.0 < min(vals) < 40.0              # Overijssel, metres NAP


# --- 3. the transform happens in fusion, and says so ---

@REAL_BOTH
def test_declared_crs_lets_ahn_reach_wgs84_through_the_existing_path(ahn_projected, gpr_line):
    frames = {f.frame_id: f for f in ahn_projected.frames + gpr_line.frames}
    records = ahn_projected.records + gpr_line.records
    views = geographic_views(records, frames)
    assert len(views) == len(records)           # every record placed
    lats = [v[0] for v in views.values()]
    lons = [v[1] for v in views.values()]
    assert 52.23 < min(lats) and max(lats) < 52.25
    assert 6.84 < min(lons) and max(lons) < 6.87


@REAL_BOTH
def test_without_frames_the_projected_records_stay_excluded(ahn_projected, gpr_line):
    """The declared CRS lives on the frame; without it there is nothing to use."""
    records = ahn_projected.records + gpr_line.records
    excluded = non_fusable_partitions(records)
    assert [(p.kind, len(p.records)) for p in excluded] == [
        ("projected", len(ahn_projected.records))]
    assert multimodal_only(fuse_datasets(records, radius_m=25.0)) == []


@REAL_BOTH
def test_real_cross_crs_fusion_produces_a_multimodal_sample(ahn_projected, gpr_line):
    """The milestone's actual goal: GPR and LiDAR over the same ground, fused."""
    frames = ahn_projected.frames + gpr_line.frames
    records = ahn_projected.records + gpr_line.records
    multi = multimodal_only(fuse_datasets(records, radius_m=25.0, frames=frames))
    assert len(multi) >= 1
    s = multi[0]
    assert sorted(s.sensor_types) == ["gpr", "lidar"]
    assert s.has_geographic_centre
    assert 52.23 < s.center_lat < 52.25 and 6.84 < s.center_lon < 6.87


@REAL_BOTH
def test_reprojected_members_are_counted_as_derived(ahn_projected, gpr_line):
    """A centre computed partly from transformed coordinates must say so."""
    frames = ahn_projected.frames + gpr_line.frames
    records = ahn_projected.records + gpr_line.records
    multi = multimodal_only(fuse_datasets(records, radius_m=25.0, frames=frames))
    for s in multi:
        # every LiDAR member arrived through the transform; no GPR member did
        assert s.n_reprojected == len(s.records_by_sensor.get("lidar", []))
        assert s.n_reprojected > 0


@REAL_BOTH
def test_fusion_does_not_mutate_the_ahn_records(ahn_projected, gpr_line):
    """Raw AHN measurements are unchanged: fusion is a reader."""
    before = [(r.position.easting, r.position.northing, r.signal[0])
              for r in ahn_projected.records[:50]]
    fuse_datasets(ahn_projected.records + gpr_line.records, radius_m=25.0,
                  frames=ahn_projected.frames + gpr_line.frames)
    after = [(r.position.easting, r.position.northing, r.signal[0])
             for r in ahn_projected.records[:50]]
    assert before == after
    assert all(r.latitude is None for r in ahn_projected.records[:50])
    assert all(r.registered_position is None for r in ahn_projected.records[:50])


# --- 3b. compatibility is required, not assumed ---

@REAL_AHN
def test_an_undeclared_projected_frame_is_still_excluded(ahn_projected):
    """
    Same coordinates, same magnitudes, CRS removed: still not fusable. Nothing
    infers EPSG:28992 from the fact that the numbers look like RD New.
    """
    frame = ahn_projected.frames[0].model_copy(deep=True)
    frame.spatial_ref = frame.spatial_ref.model_copy(
        update={"code": None, "crs_provenance": CRSProvenance.NONE})
    views = geographic_views(ahn_projected.records, {frame.frame_id: frame})
    assert views == {}
    excluded = non_fusable_partitions(ahn_projected.records, frames=[frame])
    assert [p.kind for p in excluded] == ["projected"]
    assert "declares no CRS" in excluded[0].reason


@REAL_AHN
def test_a_wrong_but_declared_crs_is_honoured_not_second_guessed(ahn_projected):
    """
    Subterra transforms what the caller declares. Declaring UTM 33N for RD
    coordinates produces a position in the wrong place -- and that is correct
    behaviour: the platform does not overrule a declaration by inspecting
    magnitudes. This pins that boundary so nobody later adds a 'sanity check'
    that silently re-infers a CRS.
    """
    frame = ahn_projected.frames[0].model_copy(deep=True)
    frame.spatial_ref = frame.spatial_ref.model_copy(update={"code": "EPSG:32633"})
    views = geographic_views(ahn_projected.records[:20], {frame.frame_id: frame})
    assert len(views) == 20
    lats = [v[0] for v in views.values()]
    assert not (52.0 < lats[0] < 53.0)       # believed the declaration, wrongly
