"""
Interpretation V1: 3D response regions.

Synthetic cases (the rule runs on arrays, so the expected answer is known):
  1. one isolated point response          -> one region, centroid / FWHM exact
  2. one elongated cylindrical response    -> one region, elongated along its axis
  3. two nearby but separate responses     -> two regions
  4. a response crossing interpolation     -> one region, interpolation reported and penalised;
                                              interpolation alone never seeds a region
  5. direct-wave / noise-like artefacts    -> no region
  6. two stacked responses offset laterally -> NOT merged; a true stacked lobe pair -> merged
Plus: connectivity modes, amplitude-scale invariance, tiny rejection, eligibility,
storage, staleness, API authorisation, append-only reviews, slice labels, export.
"""
from __future__ import annotations

import ast
import base64
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import app
from interpretation.volume_regions import propose, unpack_mask
from schemas.region import RegionConfig

D = 0.005
AXES = {"x": (0.0, D), "y": (0.0, D), "z": (0.0, D)}
SHAPE = (60, 50, 60)


def _base(seed=0):
    rng = np.random.default_rng(seed)
    f = np.abs(rng.normal(0, 1.0, SHAPE)).astype(np.float32) + 1.0
    sup = np.full(SHAPE, 2, np.uint8)        # RECONSTRUCTED
    dist = np.zeros(SHAPE[:2], np.float32)
    return f, sup, dist


def _blob(f, c, sigma, amp=30.0):
    i, j, k = np.indices(SHAPE)
    sx, sy, sz = sigma
    f += amp * np.exp(-(((i - c[0]) / sx) ** 2 + ((j - c[1]) / sy) ** 2 + ((k - c[2]) / sz) ** 2) / 2)


def _run(f, sup, dist, **kw):
    return propose(f, sup, dist, AXES, RegionConfig(**kw), z_unit="m")


def test_1_isolated_point_response_is_one_region_with_exact_geometry():
    f, s, d = _base()
    _blob(f, (30, 25, 30), (2, 2, 2))
    r = _run(f, s, d)
    assert len(r["regions"]) == 1
    g = r["regions"][0]
    assert g.peak_index == (30, 25, 30)
    assert g.centroid.x == pytest.approx(30 * D, abs=D / 2)
    assert g.centroid.y == pytest.approx(25 * D, abs=D / 2)
    assert g.centroid.z == pytest.approx(30 * D, abs=D / 2)
    # FWHM of a Gaussian = 2.355 sigma; contiguous-run measurement rounds to whole voxels
    assert g.fwhm.x == pytest.approx(2.355 * 2 * D, abs=1.5 * D)
    b = g.bounds
    assert b.x_min < 30 * D < b.x_max and b.z_min < 30 * D < b.z_max
    assert g.physical_extent.x == pytest.approx((g.index_bounds[1] - g.index_bounds[0] + 1) * D)
    assert g.support.reconstructed_voxel_fraction == 1.0
    assert g.status.value == "proposed"


def test_2_elongated_cylinder_is_one_elongated_region_along_its_axis():
    f, s, d = _base()
    i, j, k = np.indices(SHAPE)
    f += 30 * np.exp(-(((i - 30) / 2) ** 2 + ((k - 30) / 2) ** 2) / 2) * ((j > 5) & (j < 45))
    r = _run(f, s, d)
    assert len(r["regions"]) == 1
    g = r["regions"][0]
    assert g.shape.elongation > 5
    assert g.shape.azimuth_deg == pytest.approx(90, abs=5)       # along y
    assert g.shape.dip_deg == pytest.approx(0, abs=5)
    assert g.lines_spanned >= 35


def test_3_two_nearby_separate_responses_stay_two_regions():
    f, s, d = _base()
    _blob(f, (22, 25, 30), (2, 2, 2))
    _blob(f, (36, 25, 30), (2, 2, 2))
    assert len(_run(f, s, d)["regions"]) == 2


def test_4_interpolation_never_seeds_and_is_penalised_when_crossed():
    f, s, d = _base()
    i, j, k = np.indices(SHAPE)
    f += 30 * np.exp(-(((i - 30) / 2) ** 2 + ((k - 20) / 2) ** 2) / 2) * ((j > 5) & (j < 45))
    s[:, 20:30, :] = 1           # an interpolated band the response crosses
    d[:, 20:30] = 0.005
    _blob(f, (15, 25, 45), (2, 2, 2))          # a response living ONLY in interpolated space
    r = _run(f, s, d)
    assert len(r["regions"]) == 1
    g = r["regions"][0]
    assert 0.1 < g.support.interpolated_voxel_fraction < 0.5
    assert g.score_components.interpolation_penalty == pytest.approx(g.support.interpolated_voxel_fraction)
    assert r["rejected"]["seeded_only_by_interpolation"] >= 1
    # the same response with interpolation everywhere becomes nothing at all
    s[:] = 1
    assert _run(f, s, d)["regions"] == []


def test_low_support_region_is_kept_but_flagged_and_scored_lower():
    f, s, d = _base()
    _blob(f, (30, 25, 30), (3, 3, 3))
    s2 = s.copy()
    s2[:, 24:, :] = 1             # most of the blob interpolated, its seed side measured
    a = _run(f, s, d)["regions"][0]
    b = _run(f, s2, d)["regions"][0]
    assert b.support.interpolated_voxel_fraction > a.support.interpolated_voxel_fraction
    assert b.evidence_score < a.evidence_score


def test_5_direct_wave_layer_and_noise_spikes_produce_no_region():
    f, s, d = _base()
    f[:, :, 3:6] += 40.0                        # laterally continuous layer (direct wave)
    rng = np.random.default_rng(1)
    for _ in range(30):                         # isolated single-voxel spikes
        f[tuple(rng.integers(5, 45, 3))] += 25.0
    r = _run(f, s, d)
    assert r["regions"] == []
    assert r["rejected"]["tiny"] + r["rejected"]["no_seed"] >= 1


def test_6_laterally_offset_stacked_responses_are_not_merged_but_a_lobe_pair_is():
    f, s, d = _base()
    _blob(f, (20, 25, 20), (2, 2, 2))
    _blob(f, (27, 25, 29), (2, 2, 2))           # below, offset 7 voxels laterally
    assert len(_run(f, s, d)["regions"]) == 2
    f, s, d = _base()
    _blob(f, (30, 25, 18), (3, 3, 1.5))
    _blob(f, (30, 25, 30), (3, 3, 1.5))         # the same x/y, 12 voxels (60 mm) lower
    two = _run(f, s, d, merge_max_gap_m=0.0)
    assert len(two["regions"]) == 2
    one = _run(f, s, d, merge_max_gap_m=0.08)
    assert len(one["regions"]) == 1 and len(one["merges"]) == 1
    assert len(one["regions"][0].merged_from) == 2


def test_connectivity_modes_differ_on_diagonal_contact():
    f, s, d = _base()
    for n in range(12):                          # a voxel-wide diagonal chain
        f[20 + n, 20 + n, 30] = 60.0
        f[20 + n, 20 + n, 31] = 60.0          # successive pairs touch only along an edge
    kw = dict(min_voxels=5, use_local_contrast=False)
    six = _run(f, s, d, connectivity=6, **kw)["regions"]
    e18 = _run(f, s, d, connectivity=18, **kw)["regions"]
    t26 = _run(f, s, d, connectivity=26, **kw)["regions"]
    assert len(t26) == 1 and len(e18) == 1 and t26[0].voxel_count == 24
    # 6-connectivity does not join voxels that only share an edge: the chain
    # falls apart into 2-voxel pieces, all below min_voxels
    assert six == []
    with pytest.raises(ValueError):
        _run(f, s, d, connectivity=7)


def test_regions_are_invariant_to_amplitude_scale():
    f, s, d = _base()
    _blob(f, (30, 25, 30), (2, 2, 2))
    a = _run(f, s, d)["regions"]
    b = _run(f * 1000.0, s, d)["regions"]
    assert [r.index_bounds for r in a] == [r.index_bounds for r in b]
    assert [r.voxel_count for r in a] == [r.voxel_count for r in b]


def test_tiny_components_are_rejected():
    f, s, d = _base()
    _blob(f, (30, 25, 30), (0.6, 0.6, 0.6), amp=60)
    r = _run(f, s, d, min_voxels=40)
    assert r["regions"] == [] and r["rejected"]["tiny"] == 1
    assert len(_run(f, s, d, min_voxels=1)["regions"]) == 1


def test_mask_round_trip_matches_voxel_count():
    f, s, d = _base()
    _blob(f, (30, 25, 30), (2, 3, 2))
    g = _run(f, s, d)["regions"][0]
    m = unpack_mask(g)
    assert m.sum() == g.voxel_count
    i0, i1, j0, j1, k0, k1 = g.index_bounds
    assert m.shape == (i1 - i0 + 1, j1 - j0 + 1, k1 - k0 + 1)


def test_no_class_or_target_ever_enters_the_generator():
    for p in ("interpretation/volume_regions.py", "schemas/region.py"):
        src = Path(p).read_text()
        for banned in ("specimen_ground_truth", "bam_truth", "load_gt", "ground_truth(", "candidate_v2"):
            assert banned not in src, (p, banned)
    from schemas.region import ResponseRegion
    for f in ResponseRegion.model_fields:
        assert f not in ("object_class", "material", "probability", "label", "class_name")


# ------------------------------------------------------------------ product path
from tests.test_volume import build, calibrate, make_grid, root  # noqa: E402,F401


def _volume(root):
    from database.volumes_store import save_volume
    fid = make_grid()
    calibrate("ds1", fid)
    prod, arrays = build(migration="stolt_fk_3d")
    save_volume(prod, arrays)
    return prod


def test_eligibility_refuses_stale_and_mostly_unsupported_volumes(root):
    import api.regions as svc
    import api.spatial as sp
    from schemas.spatial_reference import DeclarationKind as K
    prod = _volume(root)
    assert svc.preview("ds1", prod.id, RegionConfig())["possible"]
    sparse = prod.model_copy(update={"support_summary": {"UNSUPPORTED": 80, "INTERPOLATED": 0, "RECONSTRUCTED": 20, "MEASURED": 0}})
    from interpretation.volume_regions import eligibility
    assert eligibility(sparse, {"stale": False}, RegionConfig())
    val = sp.validate_declaration(K.TIME_ZERO, {"correction_ns": 0.7, "source": "op", "evidence": "note"})
    sp.apply_declaration("ds1", K.TIME_ZERO, val, "t", frame_id="ds1:grid", declaration_id="tz9")
    p = svc.preview("ds1", prod.id, RegionConfig())
    assert not p["possible"] and "stale" in p["refusals"][0]
    with pytest.raises(svc.RegionError):
        svc.create("ds1", prod.id, RegionConfig(), "t")


def test_storage_round_trip_staleness_reviews_and_slice_labels(root):
    import api.regions as svc
    from database.regions_store import load_region_set
    from database.volumes_store import delete_volume
    prod = _volume(root)
    rs = svc.create("ds1", prod.id, RegionConfig(), "tester")
    assert rs.regions, "the synthetic point reflector must give a region"
    back = load_region_set("ds1", prod.id, rs.id)
    assert back.model_dump() == rs.model_dump()
    assert svc.staleness(rs)["stale"] is False
    g = rs.regions[0]
    # append-only history
    svc.review(rs, g.id, "uncertain", "a@x", "first look")
    svc.review(rs, g.id, "confirmed_response", "b@x", None)
    p = svc.region_payload(rs, g.id)
    assert [h["status"] for h in p["review_history"]] == ["uncertain", "confirmed_response"]
    assert p["review"]["status"] == "confirmed_response"
    assert p["review"]["evidence_grade"] == "C_operator_reviewed"
    with pytest.raises(svc.RegionError):
        svc.review(rs, g.id, "pipe", "a@x", None)
    # slice labels agree with the mask at the peak
    i, j, k = g.peak_index
    lab = svc.slice_labels(rs, prod, "xz", j)
    arr = np.frombuffer(base64.b64decode(lab["labels_u16_b64"]), "<u2").reshape(lab["rows"], lab["cols"])
    assert lab["order"][arr[k, i] - 1] == g.id
    lab_xy = svc.slice_labels(rs, prod, "xy", k)
    arr_xy = np.frombuffer(base64.b64decode(lab_xy["labels_u16_b64"]), "<u2").reshape(lab_xy["rows"], lab_xy["cols"])
    assert lab_xy["order"][arr_xy[j, i] - 1] == g.id
    # export: no invented label
    ex = svc.export_manifest(rs, prod)
    assert ex["items"][0]["operator_review"] == "confirmed_response"
    assert "class" not in str(ex["items"][0].keys())
    # a deleted / regenerated source volume makes the set stale
    delete_volume("ds1", prod.id)
    assert svc.staleness(rs)["stale"] is True


def test_time_domain_regions_are_never_in_metres(root):
    import api.regions as svc
    from database.volumes_store import save_volume
    make_grid()
    prod, arrays = build()
    save_volume(prod, arrays)
    rs = svc.create("ds1", prod.id, RegionConfig(), "t")
    assert rs.z_unit == "ns"
    for g in rs.regions:
        assert g.z_unit == "ns" and g.shape.azimuth_deg is None


def test_api_flow_and_confirmation(root):
    prod = _volume(root)
    c = TestClient(app)
    base = f"/api/volumes/ds1/{prod.id}/regions"
    p = c.post(f"{base}/preview", json={}).json()
    assert p["possible"] and p["estimated_region_count"] >= 1 and "rejected" in p
    assert c.post(base, json={}).status_code == 400
    r = c.post(base, json={"confirm": True, "config": {}})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    gid = r.json()["regions"][0]["id"]
    assert "mask_b64" not in r.json()["regions"][0]
    assert c.get(base).json()["region_sets"][0]["id"] == sid
    one = c.get(f"{base}/{sid}/{gid}").json()
    assert one["generation"]["algorithm"] == "volume_response_regions"
    rv = c.post(f"{base}/{sid}/{gid}/reviews", json={"status": "rejected_response", "notes": "ringing"})
    assert rv.status_code == 200 and rv.json()["region"]["review"]["status"] == "rejected_response"
    assert c.post(f"{base}/{sid}/{gid}/reviews", json={"status": "void"}).status_code == 409
    assert c.get(f"{base}/{sid}/slice_labels", params={"orientation": "xy", "index": 3}).status_code == 200
    assert c.get(f"{base}/nope").status_code == 404


@pytest.mark.real_auth
def test_another_user_cannot_reach_my_regions(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from configs import settings as settings_mod
    from database.models import Dataset, User
    from database.session import Base, get_db
    from database.volumes_store import save_volume

    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(settings_mod.settings, "data_root", tmp_path)
    for sub in ("raw", "processed", "metadata"):
        (tmp_path / sub).mkdir(exist_ok=True)

    def _get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_db] = _get_db
    try:
        a, b = TestClient(app), TestClient(app)
        a.post("/api/auth/register", json={"email": "a@example.test", "password": "correct-horse-battery"})
        b.post("/api/auth/register", json={"email": "b@example.test", "password": "correct-horse-battery"})
        with Session() as s:
            ida = s.query(User).filter(User.email == "a@example.test").one().id
            s.add(Dataset(id="dsA", name="A", sensor_type="gpr", original_format="test", owner_id=ida))
            s.commit()
        make_grid("dsA")
        from reconstruction.volume import build as _b
        from schemas.volume import VolumeConfig
        prod, arr = _b("dsA", VolumeConfig())
        save_volume(prod, arr)
        base = f"/api/volumes/dsA/{prod.id}/regions"
        r = a.post(base, json={"confirm": True, "config": {}})
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        for path in (base, f"{base}/{sid}"):
            assert b.get(path).status_code == 404
            assert a.get(path).status_code == 200
        assert b.post(base, json={"confirm": True, "config": {}}).status_code == 404
        if r.json()["regions"]:
            gid = r.json()["regions"][0]["id"]
            assert b.post(f"{base}/{sid}/{gid}/reviews", json={"status": "uncertain"}).status_code == 404
        assert TestClient(app).get(base).status_code == 401
    finally:
        app.dependency_overrides.clear()
