"""
Subterra Volume V1: reconstruction, refusals, support, provenance, staleness,
slices, storage, coordinates and the API.

The focusing test uses a synthetic point reflector whose correct image is
known analytically: a zero-offset diffraction t = t0 + 2 sqrt(dx^2 + dy^2 +
z0^2) / v must migrate to a compact response at (x0, y0, z0).
"""
from __future__ import annotations

import ast
import base64
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.signal import hilbert

from api.main import app
from schemas.spatial import AxisKind, CRSKind, SpatialRef, VerticalAxis
from schemas.subterra_record import SensorType
from schemas.survey_frame import SurveyFrame
from schemas.survey_grid import AxisProvenance, GridAxis, GriddedAcquisition
from schemas.volume import CoordinateFrameKind, SupportClass, VolumeConfig, ZDomain

DX = DY = 5.0          # mm
DT = 0.03              # ns
V, T0 = 0.12, 0.5      # m/ns, ns
X0, Y0, Z0 = 0.160, 0.120, 0.100


def _ricker(t, f=1.5):
    a = (np.pi * f * t) ** 2
    return (1 - 2 * a) * np.exp(-a)


def _point_data(nx=64, ny=48, nt=256, point=True):
    x = np.arange(nx) * DX / 1000
    y = np.arange(ny) * DY / 1000
    t = np.arange(nt) * DT
    X, Y = np.meshgrid(x, y, indexing="ij")
    tt = T0 + 2 * np.sqrt((X - X0) ** 2 + (Y - Y0) ** 2 + Z0 ** 2) / V
    d = _ricker(t[None, None, :] - tt[:, :, None]) * (1.0 if point else 0.0)
    # three flat "known-depth" reflectors for the calibration
    for z in (0.05, 0.20, 0.30):
        d += 0.3 * _ricker(t[None, None, :] - (T0 + 2 * z / V))
    return d.astype(np.float32)


@pytest.fixture
def root(tmp_path, monkeypatch):
    from configs import settings as settings_mod
    monkeypatch.setattr(settings_mod.settings, "data_root", tmp_path)
    for sub in ("raw", "processed", "metadata"):
        (tmp_path / sub).mkdir(exist_ok=True)
    return tmp_path


def make_grid(dataset_id="ds1", data=None, missing=(), ny=None):
    from database.frames_store import save_frames
    from database.grid_store import save_grid

    data = _point_data() if data is None else data
    if ny is not None:
        data = data[:, :ny, :]
    data = data.copy()
    data[:, list(missing), :] = 0
    nx, ny, nt = data.shape
    fid = f"{dataset_id}:grid"
    geom = GriddedAcquisition(
        dataset_id=dataset_id, frame_id=fid,
        trace_axis=GridAxis(name="x", n=nx, origin=0, step=DX, unit="mm", provenance=AxisProvenance.SOURCE_FILE, source="test"),
        line_axis=GridAxis(name="y", n=ny, origin=0, step=DY, unit="mm", provenance=AxisProvenance.SOURCE_FILE, source="test"),
        time_axis=GridAxis(name="t", n=nt, origin=0, step=DT, unit="ns", provenance=AxisProvenance.SOURCE_FILE, source="test"),
        array_file="", array_sha256="", missing_lines=list(missing))
    save_grid(geom, data)
    save_frames(dataset_id, [SurveyFrame(
        frame_id=fid, dataset_id=dataset_id, modality=SensorType.GPR, source_format="test_grid",
        source_metadata={"gridded_acquisition": True},
        spatial_ref=SpatialRef(kind=CRSKind.ENGINEERING, name="test grid"),
        vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns", origin="instrument time zero",
                                   positive_down=True, n_samples=nt, sample_interval=DT))])
    return fid


def calibrate(dataset_id, fid, v=V, t0=T0):
    import api.spatial as sp
    from schemas.spatial_reference import DeclarationKind as K
    pts = [{"depth_m": z, "time_ns": t0 + 2 * z / v, "depth_source": "fabrication_drawing",
            "depth_evidence": f"test reflector at {z} m", "reflector_id": f"r{z}"} for z in (0.05, 0.20, 0.30)]
    val = sp.validate_declaration(K.DEPTH_CALIBRATION, {"points": pts, "pick_convention": "peak",
                                                        "pick_precision_ns": 0.05})
    sp.apply_declaration(dataset_id, K.DEPTH_CALIBRATION, val, "test", frame_id=fid, declaration_id="cal-1")
    val = sp.validate_declaration(K.ANTENNA_OFFSET, {"offset_m": 0.0, "measured_from": "depth_axis_origin",
                                                     "evidence": "acquisition_documentation",
                                                     "supplied_by": "test documentation"})
    sp.apply_declaration(dataset_id, K.ANTENNA_OFFSET, val, "test", frame_id=fid, declaration_id="off-1")


def build(dataset_id="ds1", **kw):
    from reconstruction.volume import build as _build
    return _build(dataset_id, VolumeConfig(**kw))


# ------------------------------------------------------------------ refusals
def test_no_grid_is_refused(root):
    from reconstruction.volume import VolumeRefused, preview
    p = preview("nothing", VolumeConfig())
    assert not p["possible"] and "gridded acquisition" in p["refusals"][0]
    with pytest.raises(VolumeRefused):
        build("nothing")


def test_a_single_line_is_never_extruded_into_3d(root):
    from reconstruction.volume import VolumeRefused, preview
    make_grid(ny=1)
    p = preview("ds1", VolumeConfig())
    assert not p["possible"]
    assert any("B-scan" in r for r in p["refusals"])
    with pytest.raises(VolumeRefused):
        build()


def test_without_a_sufficient_depth_model_z_stays_time(root):
    from reconstruction.volume import VolumeRefused, preview
    make_grid()
    p = preview("ds1", VolumeConfig())
    assert p["possible"] and p["depth"]["z_domain"] == "two_way_time"
    prod, arrays = build()
    assert prod.z_domain is ZDomain.TWO_WAY_TIME
    assert prod.z_axis.unit == "ns" and prod.z_axis.name == "two_way_time"
    assert "NOT depth" in prod.coordinate_frame.z_meaning
    with pytest.raises(VolumeRefused, match="scientifically sufficient depth model"):
        build(z_domain="depth")
    with pytest.raises(VolumeRefused, match="migration"):
        build(migration="stolt_fk_3d")


def test_a_velocity_alone_is_not_enough_for_depth(root):
    import api.spatial as sp
    from reconstruction.volume import preview
    from schemas.spatial_reference import DeclarationKind as K
    fid = make_grid()
    val = sp.validate_declaration(K.DEPTH_CONVERSION, {"velocity_m_per_ns": 0.1, "velocity_basis": "user_declared", "basis": "operator"})
    sp.apply_declaration("ds1", K.DEPTH_CONVERSION, val, "test", frame_id=fid)
    assert preview("ds1", VolumeConfig())["depth"]["z_domain"] == "two_way_time"


# ------------------------------------------------------------------ depth, provenance
def test_calibrated_depth_volume_axes_and_provenance(root):
    fid = make_grid(data=_point_data(point=False))
    calibrate("ds1", fid)
    prod, arrays = build()
    assert prod.z_domain is ZDomain.DEPTH
    assert prod.z_axis.unit == "m"
    assert prod.z_axis.step == pytest.approx(V * DT / 2, rel=1e-6)
    assert prod.z_axis.origin == 0.0
    cp = prod.calibration_provenance
    assert cp["depth_calibration_declaration_id"] == "cal-1"
    assert cp["velocity"]["basis"] == "calibrated_from_known_geometry"
    assert cp["time_zero"]["status"] == "calibrated"
    assert prod.coordinate_frame.kind is CoordinateFrameKind.LOCAL
    assert prod.coordinate_frame.horizontal_registration is None
    assert prod.support_summary["MEASURED"] == int(np.prod(prod.shape))
    # a flat reflector at 0.20 m lands at depth 0.20 m (time zero removed)
    col = arrays["response_envelope.npy"][5, 5, :]
    zs = prod.z_axis.values()
    near = (zs > 0.15) & (zs < 0.25)
    assert zs[near][np.argmax(col[near])] == pytest.approx(0.20, abs=2 * prod.z_axis.step)


def test_field_order_matches_the_registered_lines(root):
    data = _point_data()
    fid = make_grid(data=data)
    calibrate("ds1", fid)
    prod, arrays = build(dewow=False)
    f = arrays["radar_response.npy"]
    s = T0 / DT
    i0, w = int(np.floor(s)), s - np.floor(s)
    expect = (1 - w) * data[7, 11, i0:i0 + 50] + w * data[7, 11, i0 + 1:i0 + 51]
    assert np.allclose(f[7, 11, :50], expect, atol=1e-5)


# ------------------------------------------------------------------ migration
def _fwhm_x(env, j, k):
    prof = env[:, j, k]
    return int((prof >= prof.max() / 2).sum())


def test_synthetic_point_reflector_focuses_where_the_maths_says(root):
    fid = make_grid()
    calibrate("ds1", fid)
    raw, raw_a = build(migration="none")
    mig, mig_a = build(migration="stolt_fk_3d")
    e = mig_a["response_envelope.npy"].copy()
    zs = mig.z_axis.values()
    e[:, :, (zs < 0.06) | (zs > 0.16)] = 0         # exclude the flat calibration reflectors
    i, j, k = np.unravel_index(np.nanargmax(e), e.shape)
    assert mig.x_axis.values()[i] == pytest.approx(X0, abs=DX / 1000)
    assert mig.y_axis.values()[j] == pytest.approx(Y0, abs=DY / 1000)
    assert zs[k] == pytest.approx(Z0, abs=3 * mig.z_axis.step)
    er = raw_a["response_envelope.npy"].copy()
    er[:, :, (zs < 0.06) | (zs > 0.16)] = 0
    k_raw = int(np.nanargmax(er[i, j, :]))
    assert _fwhm_x(e, j, k) < 0.5 * _fwhm_x(np.nan_to_num(er), j, k_raw)
    assert mig.support_summary["RECONSTRUCTED"] == int(np.prod(mig.shape))
    assert mig.migration.method == "stolt_fk_3d"
    assert mig.migration.velocity_m_per_ns == pytest.approx(V, rel=1e-3)
    assert mig.migration.time_zero_source == "calibrated"
    assert mig.migration.parameters["aliasing"]["unaliased"] is True


def test_stolt_maps_a_flat_reflector_to_v_t_over_2():
    from reconstruction.migration import stolt_migrate
    nt = 200
    t = np.arange(nt) * DT
    d = np.broadcast_to(_ricker(t - 3.0), (32, 24, nt)).astype(np.float32).copy()
    img = stolt_migrate(d, 0.005, 0.005, DT, V, pad_xy=8)
    env = np.abs(hilbert(img[16, 12, :]))
    assert np.argmax(env) * V * DT / 2 == pytest.approx(V * 3.0 / 2, abs=V * DT)


# ------------------------------------------------------------------ support / interpolation
def test_missing_line_stays_unsupported_in_no_fill_mode(root):
    fid = make_grid(missing=[10])
    calibrate("ds1", fid)
    prod, a = build()
    s = a["support_class.npy"]
    assert (s[:, 10, :] == SupportClass.UNSUPPORTED).all()
    assert np.isnan(a["radar_response.npy"][:, 10, :]).all()
    assert (s[:, 9, :] == SupportClass.MEASURED).all()


def test_linear_bounded_fills_a_one_line_gap_and_records_its_distance(root):
    fid = make_grid(missing=[10])
    calibrate("ds1", fid)
    prod, a = build(interpolation="linear_bounded")
    assert (a["support_class.npy"][:, 10, :] == SupportClass.INTERPOLATED).all()
    assert a["nearest_distance.npy"][0, 10] == pytest.approx(DY / 1000)
    f = a["radar_response.npy"]
    assert np.allclose(f[:, 10, :], 0.5 * (f[:, 9, :] + f[:, 11, :]), atol=1e-5)


def test_a_gap_wider_than_the_limit_is_never_bridged(root):
    fid = make_grid(missing=[10, 11, 12])
    calibrate("ds1", fid)
    prod, a = build(interpolation="linear_bounded", max_gap_line_spacings=2.0)
    assert (a["support_class.npy"][:, 10:13, :] == SupportClass.UNSUPPORTED).all()
    assert np.isnan(a["radar_response.npy"][:, 11, :]).all()


def test_migration_refuses_an_incomplete_grid(root):
    from reconstruction.volume import VolumeRefused
    fid = make_grid(missing=[10])
    calibrate("ds1", fid)
    with pytest.raises(VolumeRefused, match="complete regular grid"):
        build(migration="stolt_fk_3d")


def test_finer_output_spacing_marks_between_line_voxels_interpolated(root):
    fid = make_grid()
    calibrate("ds1", fid)
    prod, a = build(interpolation="linear_bounded", output_line_spacing_m=0.0025)
    assert prod.shape[1] == 2 * 48 - 1
    s = a["support_class.npy"]
    assert (s[:, 0::2, :] == SupportClass.MEASURED).all()
    assert (s[:, 1::2, :] == SupportClass.INTERPOLATED).all()
    assert a["nearest_distance.npy"][0, 1] == pytest.approx(0.0025)


# ------------------------------------------------------------------ coordinates
def test_affine_tie_makes_a_georeferenced_volume_without_touching_values(root):
    from database.frames_store import load_frames, save_frames
    from schemas.spatial import AffineControlPoint, AffineTie
    fid = make_grid()
    calibrate("ds1", fid)
    local, la = build()
    frames = load_frames("ds1")
    frames[0].affine_tie = AffineTie(
        control_points=[AffineControlPoint(x=0, y=0, lat=52.0, lon=13.0),
                        AffineControlPoint(x=1000, y=0, lat=52.0, lon=13.00001),
                        AffineControlPoint(x=0, y=1000, lat=52.00001, lon=13.0)],
        supplied_by="test survey", a=0.0, b=1e-8, e=52.0, c=1e-8, d=0.0, f=13.0)
    save_frames("ds1", frames)
    geo, ga = build()
    assert local.coordinate_frame.kind is CoordinateFrameKind.LOCAL
    assert geo.coordinate_frame.kind is CoordinateFrameKind.GEOREFERENCED
    reg = geo.coordinate_frame.horizontal_registration
    assert reg.b == pytest.approx(1e-5) and reg.c == pytest.approx(1e-5)   # per metre, not per mm
    assert geo.coordinate_frame.absolute_elevation is False
    assert np.array_equal(np.nan_to_num(la["radar_response.npy"]), np.nan_to_num(ga["radar_response.npy"]))


# ------------------------------------------------------------------ staleness / storage
def test_staleness_names_the_changed_input_and_never_rebuilds(root):
    import api.spatial as sp
    from database.volumes_store import load_volume, save_volume
    from reconstruction.volume import staleness
    from schemas.spatial_reference import DeclarationKind as K
    fid = make_grid()
    calibrate("ds1", fid)
    prod, arrays = build()
    save_volume(prod, arrays)
    assert staleness(prod)["stale"] is False
    val = sp.validate_declaration(K.TIME_ZERO, {"correction_ns": 0.6, "source": "operator",
                                                "evidence": "a later field note"})
    sp.apply_declaration("ds1", K.TIME_ZERO, val, "test", frame_id=fid, declaration_id="tz-2")
    st = staleness(load_volume("ds1", prod.id))
    assert st["stale"] is True
    assert "velocity_depth_calibration" in st["changed_components"] or "time_zero_declaration" in st["changed_components"]
    assert st["action"].startswith("regenerate")
    assert load_volume("ds1", prod.id).source_fingerprint == prod.source_fingerprint


def test_changed_measurements_make_a_volume_stale(root):
    from database.volumes_store import save_volume
    from reconstruction.volume import staleness
    fid = make_grid()
    prod, arrays = build()
    save_volume(prod, arrays)
    make_grid(data=_point_data() * 2)
    assert "source_records" in staleness(prod)["changed_components"]


def test_storage_round_trip(root):
    from database.volumes_store import list_volumes, load_volume, open_array, save_volume
    fid = make_grid()
    calibrate("ds1", fid)
    prod, arrays = build()
    save_volume(prod, arrays)
    back = load_volume("ds1", prod.id)
    assert back.model_dump() == prod.model_dump()
    assert np.array_equal(np.asarray(open_array(back, "radar_response.npy")), arrays["radar_response.npy"], equal_nan=True)
    assert [v.id for v in list_volumes("ds1")] == [prod.id]


# ------------------------------------------------------------------ slices
def test_slice_orientations_index_the_same_voxels(root):
    import api.volumes as svc
    from database.volumes_store import save_volume
    fid = make_grid()
    calibrate("ds1", fid)
    prod, a = build()
    save_volume(prod, a)
    f = a["radar_response.npy"]

    def dec(s):
        return np.frombuffer(base64.b64decode(s["values_f32_b64"]), "<f4").reshape(s["rows"], s["cols"])
    xy, xz, yz = (svc.slice_(prod, "xy", 30), svc.slice_(prod, "xz", 20), svc.slice_(prod, "yz", 15))
    assert np.array_equal(dec(xy), f[:, :, 30].T)
    assert np.array_equal(dec(xz), f[:, 20, :].T)
    assert np.array_equal(dec(yz), f[15, :, :].T)
    # the three agree at their common voxel
    assert dec(xy)[20, 15] == dec(xz)[30, 15] == dec(yz)[30, 20]
    thick = svc.slice_(prod, "xy", 30, thickness=3)
    assert thick["thickness_voxels"] == 3 and thick["note"]


def test_voxel_reports_provenance(root):
    import api.volumes as svc
    from database.volumes_store import save_volume
    fid = make_grid(missing=[10])
    calibrate("ds1", fid)
    prod, a = build(interpolation="linear_bounded")
    save_volume(prod, a)
    v = svc.voxel(prod, 3, 10, 40)
    assert v["support_class"] == "INTERPOLATED"
    assert v["interpolation_distance_m"] == pytest.approx(0.005)
    assert v["depth_calibration"]["depth_calibration_declaration_id"] == "cal-1"
    assert v["z_unit"] == "m" and v["source_frames"] == [fid]
    assert svc.voxel(prod, 3, 9, 40)["support_class"] == "MEASURED"


def test_render3d_is_bounded_and_display_only(root):
    import api.volumes as svc
    from database.volumes_store import save_volume
    fid = make_grid()
    calibrate("ds1", fid)
    prod, a = build()
    save_volume(prod, a)
    r = svc.render3d(prod, max_dim=32)
    assert r["display_only"] is True and r["original_shape"] == list(prod.shape)
    assert max(r["shape"]) <= 32
    assert len(base64.b64decode(r["data_u8_b64"])) == int(np.prod(r["shape"]))


# ------------------------------------------------------------------ ground truth stays separate
def test_reconstruction_never_reads_ground_truth():
    banned = ("specimen_ground_truth", "bam_truth", "load_gt", "load_targets", "ground_truth")
    for p in Path("reconstruction").glob("*.py"):
        src = p.read_text()
        tree = ast.parse(src)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            a.attr for a in ast.walk(tree) if isinstance(a, ast.Attribute)}
        mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        for b in banned:
            assert b not in names and not any(b in m for m in mods), (p, b)
            assert b not in src, (p, b)


def test_ground_truth_overlay_is_labelled_and_only_for_linked_bam_depth_volumes(root):
    import api.volumes as svc
    fid = make_grid()
    tprod, _ = build()
    assert svc.ground_truth(tprod, {})["available"] is False
    bam = {"benchmark": {"benchmark_id": "bam-concrete-gpr", "specimen_id": "Pk266"}}
    assert svc.ground_truth(tprod, bam)["available"] is False          # time domain
    calibrate("ds1", fid)
    dprod, _ = build()
    gt = svc.ground_truth(dprod, bam)
    assert gt["available"] and gt["label"] == "GROUND TRUTH — NOT INPUT TO RECONSTRUCTION"
    ducts = [o for o in gt["objects"] if o["kind"] == "duct"]
    assert len(ducts) == 4 and ducts[0]["z_top_m"] == pytest.approx(0.241)
    assert len([o for o in gt["objects"] if o["kind"] == "plane"]) == 4


# ------------------------------------------------------------------ API
def test_api_preview_create_confirm_slice_voxel(root):
    fid = make_grid()
    calibrate("ds1", fid)
    c = TestClient(app)
    p = c.post("/api/volumes/ds1/preview", json={"migration": "stolt_fk_3d"}).json()
    assert p["possible"] and p["depth"]["z_domain"] == "depth"
    assert c.post("/api/volumes/ds1", json={"config": {}}).status_code == 400
    r = c.post("/api/volumes/ds1", json={"confirm": True, "config": {"migration": "stolt_fk_3d"}})
    assert r.status_code == 200, r.text
    vid = r.json()["id"]
    assert r.json()["staleness"]["stale"] is False
    assert [v["id"] for v in c.get("/api/volumes/ds1").json()["volumes"]] == [vid]
    s = c.get(f"/api/volumes/ds1/{vid}/slice", params={"orientation": "xz", "index": 24}).json()
    assert s["rows"] == r.json()["shape"][2] and s["cols"] == r.json()["shape"][0]
    assert c.get(f"/api/volumes/ds1/{vid}/slice", params={"orientation": "ab", "index": 0}).status_code == 422
    assert c.get(f"/api/volumes/ds1/{vid}/voxel", params={"i": 1, "j": 2, "k": 3}).json()["support_class"] == "RECONSTRUCTED"
    assert c.get(f"/api/volumes/ds1/{vid}/render3d", params={"max_dim": 32}).json()["display_only"]
    assert c.get("/api/volumes/ds1/nope").status_code == 404
    bad = c.post("/api/volumes/ds1", json={"confirm": True, "config": {"z_domain": "depth", "frame_id": "x"}})
    assert bad.status_code == 409
    assert c.delete(f"/api/volumes/ds1/{vid}").json() == {"deleted": vid}


@pytest.mark.real_auth
def test_another_user_cannot_reach_my_volumes(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from configs import settings as settings_mod
    from database.models import Dataset, User
    from database.session import Base, get_db

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
        fid = make_grid("dsA")
        r = a.post("/api/volumes/dsA", json={"confirm": True, "config": {}})
        assert r.status_code == 200, r.text
        vid = r.json()["id"]
        for path in (f"/api/volumes/dsA", f"/api/volumes/dsA/{vid}",
                     f"/api/volumes/dsA/{vid}/slice?orientation=xy&index=0"):
            assert b.get(path).status_code == 404
            assert a.get(path).status_code == 200
        assert b.post("/api/volumes/dsA", json={"confirm": True, "config": {}}).status_code == 404
        assert TestClient(app).get(f"/api/volumes/dsA/{vid}").status_code == 401
    finally:
        app.dependency_overrides.clear()


# ------------------------------------------------------------------ spatial UX for gridded datasets
def test_spatial_page_offers_calibration_and_knows_grid_positions(root):
    from database.frames_store import load_frames
    from schemas.spatial_reference import assess_depth, assess_horizontal
    fid = make_grid()
    frames = load_frames("ds1")
    h = assess_horizontal(frames, [])
    assert h.state == "available" and "grid node" in h.reason
    d = assess_depth(frames)
    assert d.action.value == "depth_conversion"
    alts = {a.value for a in d.alternatives}
    assert {"depth_calibration", "antenna_offset"} <= alts
    assert d.detail["frames"] == [fid]
