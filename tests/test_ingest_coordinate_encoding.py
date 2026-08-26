"""
Product-ingest coordinate-encoding milestone: making the SEG-Y converter's
existing `coordinate_encoding` declaration (previously reachable only from a
research script calling `SEGYConverter.load()` directly) reachable through
the three real product ingest paths -- `POST /api/datasets/ingest`,
`POST /api/datasets/ingest_local_file`, and the review/accept flow
(`POST /api/imports` + `POST /api/imports/jobs/{id}/accept`).

WHAT THIS FILE DOES NOT TEST. The converter's own NMEA/IEEE-float decoding
arithmetic is already pinned in `tests/test_segy_little_endian.py` -- this
file never re-derives that math. It tests the NEW plumbing only: does the
option reach the converter unchanged, is it validated (a known value, and
only for a format that can use it), and does the full real chain (ingest ->
DEM alignment -> topographic correction -> dataset report) become reachable
end to end once it does.

NO NEW COORDINATE SCIENCE, NO FABRICATED ELEVATION. Every SEG-Y file here is
a real, hand-built byte sequence (mirroring test_segy_little_endian.py's own
`write_segy` helper, extended with the two elevation header fields it did
not need) -- never a claim invented by this test file.
"""
from __future__ import annotations

import struct

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.main import app
from converters.segy_converter import COORDINATE_ENCODINGS, validate_coordinate_encoding
from database.models import Dataset
from database.session import Base, get_db

pytestmark = pytest.mark.real_auth

PASSWORD = "coordinate-encoding-test-password"

# --- a minimal synthetic little-endian SEG-Y writer, elevation included ----
#
# Mirrors tests/test_segy_little_endian.py::write_segy, extended with the
# two elevation trace-header fields (bytes 41-44 ReceiverGroupElevation,
# 45-48 SourceSurfaceElevation) that converter needs under ieee_nmea and
# that file's own helper never had to set.

_CODE = {2: "i", 3: "h", 5: "f", 8: "b"}


def _int32_for_float(value: float, order: str) -> int:
    """The int32 bit pattern that reinterprets, under IEEE float32, to `value`."""
    return struct.unpack(order + "i", struct.pack(order + "f", value))[0]


def write_segy(
    path, *, n_traces=3, n_samples=8, fmt=3, interval=98,
    source_x=0, source_y=0, coord_scalar=-1000,
    receiver_group_elevation=None, source_surface_elevation=None,
):
    """Little-endian only -- ieee_nmea is a little-endian-file phenomenon in every real case this platform has seen."""
    s = "<"
    out = bytearray(b"\x00" * 3200)
    bh = bytearray(b"\x00" * 400)
    bh[16:18] = struct.pack(s + "h", interval)
    bh[20:22] = struct.pack(s + "h", n_samples)
    bh[24:26] = struct.pack(s + "h", fmt)
    out += bh
    for t in range(n_traces):
        th = bytearray(b"\x00" * 240)
        if receiver_group_elevation is not None:
            th[40:44] = struct.pack(s + "i", receiver_group_elevation)
        if source_surface_elevation is not None:
            th[44:48] = struct.pack(s + "i", source_surface_elevation)
        th[68:70] = struct.pack(s + "h", 1)  # delay_scalar
        th[70:72] = struct.pack(s + "h", coord_scalar)
        th[72:76] = struct.pack(s + "i", source_x)
        th[76:80] = struct.pack(s + "i", source_y)
        th[108:110] = struct.pack(s + "h", 0)  # delay
        th[114:116] = struct.pack(s + "h", n_samples)
        out += th
        out += struct.pack(f"{s}{n_samples}{_CODE[fmt]}",
                           *[(t * 10 + i) for i in range(n_samples)])
    path.write_bytes(bytes(out))
    return path


#: A real, hand-computed ieee_nmea coordinate pair (52.2389 N, 6.8516 E) --
#: the exact bit patterns test_segy_little_endian.py's own
#: test_ieee_nmea_encoding_yields_a_geographic_position already pins.
IEEE_NMEA_SOURCE_X = 1143129685
IEEE_NMEA_SOURCE_Y = 1168306866
IEEE_NMEA_LAT = pytest.approx(52.2389, abs=1e-3)
IEEE_NMEA_LON = pytest.approx(6.8516, abs=1e-3)


def _ieee_nmea_segy(path, antenna_elevation_m=12.5, ground_elevation_second_m=10.0, **kw):
    return write_segy(
        path, source_x=IEEE_NMEA_SOURCE_X, source_y=IEEE_NMEA_SOURCE_Y,
        receiver_group_elevation=_int32_for_float(antenna_elevation_m, "<"),
        source_surface_elevation=_int32_for_float(ground_elevation_second_m, "<"),
        **kw,
    )


# ---------------------------------------------------------------------------
# 1. validate_coordinate_encoding: the one value-check every path shares
# ---------------------------------------------------------------------------

class TestValidateCoordinateEncoding:
    def test_every_real_encoding_is_accepted(self):
        for value in COORDINATE_ENCODINGS:
            validate_coordinate_encoding(value)  # must not raise

    def test_an_unknown_value_is_rejected(self):
        with pytest.raises(ValueError, match="unknown coordinate_encoding"):
            validate_coordinate_encoding("nmea_dms")

    def test_the_error_names_the_real_supported_values(self):
        with pytest.raises(ValueError) as exc:
            validate_coordinate_encoding("bogus")
        for value in COORDINATE_ENCODINGS:
            assert value in str(exc.value)


# ---------------------------------------------------------------------------
# 2. AcceptRequest: rejects an unknown value at the schema layer
# ---------------------------------------------------------------------------

class TestAcceptRequestValidation:
    def test_a_known_encoding_is_accepted(self):
        from api.routes.imports import AcceptRequest
        req = AcceptRequest(coordinate_encoding="ieee_nmea")
        assert req.coordinate_encoding == "ieee_nmea"

    def test_none_is_the_default(self):
        from api.routes.imports import AcceptRequest
        assert AcceptRequest().coordinate_encoding is None

    def test_an_unknown_encoding_fails_at_construction(self):
        import pydantic
        from api.routes.imports import AcceptRequest
        with pytest.raises(pydantic.ValidationError, match="unknown coordinate_encoding"):
            AcceptRequest(coordinate_encoding="nonsense")


# ---------------------------------------------------------------------------
# 3. validated_ingest_options: segy accepts it, other formats refuse it
# ---------------------------------------------------------------------------

class TestValidatedIngestOptionsForSegy:
    def test_segy_accepts_coordinate_encoding(self):
        from api import acquisition
        from api.routes.imports import AcceptRequest
        from database.models import ImportJob

        job = ImportJob(id="j", identification={"detected_format": "segy"})
        assert acquisition.validated_ingest_options(
            job, AcceptRequest(coordinate_encoding="ieee_nmea"),
        ) == {"coordinate_encoding": "ieee_nmea"}

    def test_a_non_segy_format_refuses_it(self):
        from fastapi import HTTPException

        from api import acquisition
        from api.routes.imports import AcceptRequest
        from database.models import ImportJob

        job = ImportJob(id="j", identification={"detected_format": "csv"})
        with pytest.raises(HTTPException) as exc:
            acquisition.validated_ingest_options(
                job, AcceptRequest(coordinate_encoding="ieee_nmea"))
        assert "cannot be applied to a csv file" in exc.value.detail

    def test_geotiffs_own_option_is_unaffected_by_the_new_one(self):
        """The two declarations live independently; adding segy's option must not touch geotiff's."""
        from api import acquisition
        from api.routes.imports import AcceptRequest
        from database.models import ImportJob

        job = ImportJob(id="j", identification={"detected_format": "geotiff"})
        assert acquisition.validated_ingest_options(
            job, AcceptRequest(band_is_elevation=True)) == {"band_is_elevation": True}


# ---------------------------------------------------------------------------
# 4. _run_ingest_pipeline's own gate: the ONLY check for the sync routes
# ---------------------------------------------------------------------------

class TestPipelineLevelGate:
    def test_coordinate_encoding_on_a_non_segy_converter_is_refused(self):
        from api.routes.datasets import _validate_coordinate_encoding_kwarg
        from converters.csv_converter import CSVConverter
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _validate_coordinate_encoding_kwarg(
                CSVConverter(), {"coordinate_encoding": "ieee_nmea"})
        assert exc.value.status_code == 422
        assert "cannot be applied to a csv file" in exc.value.detail

    def test_an_unknown_value_on_a_segy_converter_is_refused(self):
        from api.routes.datasets import _validate_coordinate_encoding_kwarg
        from converters.segy_converter import SEGYConverter
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _validate_coordinate_encoding_kwarg(
                SEGYConverter(), {"coordinate_encoding": "bogus"})
        assert exc.value.status_code == 422
        assert "unknown coordinate_encoding" in exc.value.detail

    def test_a_known_value_on_a_segy_converter_passes(self):
        from api.routes.datasets import _validate_coordinate_encoding_kwarg
        from converters.segy_converter import SEGYConverter

        _validate_coordinate_encoding_kwarg(
            SEGYConverter(), {"coordinate_encoding": "ieee_nmea"})  # must not raise

    def test_no_coordinate_encoding_key_is_a_no_op_for_any_converter(self):
        from api.routes.datasets import _validate_coordinate_encoding_kwarg
        from converters.csv_converter import CSVConverter

        _validate_coordinate_encoding_kwarg(CSVConverter(), None)
        _validate_coordinate_encoding_kwarg(CSVConverter(), {})
        _validate_coordinate_encoding_kwarg(CSVConverter(), {"other_kwarg": 1})


# ---------------------------------------------------------------------------
# shared fixtures for the real, live-HTTP end-to-end tests
# ---------------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from configs.settings import settings
    from jobs import runner

    monkeypatch.setattr(settings, "data_root", tmp_path)
    for name in ("processed", "raw", "metadata", "downloads"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{tmp_path / 'coord_encoding.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def _get_session():
        session = Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(runner, "get_session", _get_session)
    # Drive the worker explicitly (runner._execute) so a test never races the
    # real background executor -- same discipline as
    # tests/test_auth_and_ownership.py's own end-to-end import test.
    import api.routes.imports as imports_mod
    monkeypatch.setattr(imports_mod.runner, "submit", lambda job_id: None)

    app.dependency_overrides[get_db] = _get_db
    try:
        yield Session, tmp_path
    finally:
        app.dependency_overrides.clear()


def signed_in(email="coord-owner@example.test") -> TestClient:
    client = TestClient(app)
    response = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return client


# ---------------------------------------------------------------------------
# 5. POST /api/datasets/ingest end to end
# ---------------------------------------------------------------------------

class TestIngestEndpointEndToEnd:
    def test_ieee_nmea_is_decoded_through_the_real_upload_endpoint(self, env, tmp_path):
        client = signed_in()
        segy_path = _ieee_nmea_segy(tmp_path / "line.sgy")

        resp = client.post(
            "/api/datasets/ingest",
            files={"file": ("line.sgy", segy_path.read_bytes(), "application/octet-stream")},
            data={"sensor_type": "gpr", "coordinate_encoding": "ieee_nmea",
                  "apply_preprocessing": "false"},
        )
        assert resp.status_code == 200, resp.text
        dataset_id = resp.json()["dataset_id"]

        from database.records_store import load_records
        records = load_records(dataset_id, use_cache=False)
        assert records[0].latitude == IEEE_NMEA_LAT
        assert records[0].longitude == IEEE_NMEA_LON
        assert records[0].elevation == pytest.approx(12.5)
        assert records[0].metadata["acquisition_elevation_datum"] == "UNDECLARED"

    def test_omitting_it_keeps_todays_default_behaviour(self, env, tmp_path):
        """The SAME bit pattern, read WITHOUT coordinate_encoding, decodes as plain scaled integers -- proving the parameter genuinely changes behaviour rather than always doing the ieee_nmea thing."""
        client = signed_in()
        segy_path = _ieee_nmea_segy(tmp_path / "line2.sgy")

        resp = client.post(
            "/api/datasets/ingest",
            files={"file": ("line2.sgy", segy_path.read_bytes(), "application/octet-stream")},
            data={"sensor_type": "gpr", "apply_preprocessing": "false"},
        )
        assert resp.status_code == 200, resp.text
        dataset_id = resp.json()["dataset_id"]

        from database.records_store import load_records
        records = load_records(dataset_id, use_cache=False)
        # Read as int32_scaled, the huge raw ints scale to an absurd, non-geographic position.
        assert records[0].latitude != IEEE_NMEA_LAT
        assert records[0].elevation is None  # elevation is only read under ieee_nmea

    def test_an_unknown_encoding_value_is_a_clean_422(self, env, tmp_path):
        client = signed_in()
        segy_path = write_segy(tmp_path / "line3.sgy")
        resp = client.post(
            "/api/datasets/ingest",
            files={"file": ("line3.sgy", segy_path.read_bytes(), "application/octet-stream")},
            data={"sensor_type": "gpr", "coordinate_encoding": "nmea_dms"},
        )
        assert resp.status_code == 422
        assert "unknown coordinate_encoding" in resp.json()["detail"]

    def test_coordinate_encoding_on_a_csv_upload_is_refused_not_a_500(self, env, tmp_path):
        client = signed_in()
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("lat,lon,depth,value\n52.0,6.0,1.0,3.5\n")
        resp = client.post(
            "/api/datasets/ingest",
            files={"file": ("data.csv", csv_path.read_bytes(), "text/csv")},
            data={"sensor_type": "gpr", "coordinate_encoding": "ieee_nmea"},
        )
        assert resp.status_code == 422
        assert "cannot be applied to a csv file" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 6. POST /api/datasets/ingest_local_file end to end
# ---------------------------------------------------------------------------

class TestIngestLocalFileEndToEnd:
    def test_ieee_nmea_is_decoded_through_the_local_file_endpoint(self, env, tmp_path):
        client = signed_in()
        segy_path = _ieee_nmea_segy(tmp_path / "downloads" / "local_line.sgy")

        resp = client.post(
            "/api/datasets/ingest_local_file",
            json={"path": str(segy_path), "sensor_type": "gpr",
                 "coordinate_encoding": "ieee_nmea", "apply_preprocessing": False},
        )
        assert resp.status_code == 200, resp.text
        dataset_id = resp.json()["dataset_id"]

        from database.records_store import load_records
        records = load_records(dataset_id, use_cache=False)
        assert records[0].latitude == IEEE_NMEA_LAT
        assert records[0].elevation == pytest.approx(12.5)

    def test_an_unknown_value_fails_at_the_request_schema(self, env):
        client = signed_in()
        resp = client.post(
            "/api/datasets/ingest_local_file",
            json={"path": "downloads/whatever.sgy", "sensor_type": "gpr",
                 "coordinate_encoding": "not_a_real_encoding"},
        )
        assert resp.status_code == 422
        assert "unknown coordinate_encoding" in resp.text


# ---------------------------------------------------------------------------
# 7. The real product flow: POST /api/imports -> review -> accept
# ---------------------------------------------------------------------------

class TestAsyncImportAcceptEndToEnd:
    def test_declaring_coordinate_encoding_at_accept_decodes_the_real_dataset(self, env, tmp_path):
        client = signed_in()
        segy_path = _ieee_nmea_segy(tmp_path / "async_line.sgy")

        created = client.post(
            "/api/imports",
            files={"file": ("async_line.sgy", segy_path.read_bytes(), "application/octet-stream")},
            data={"sensor_type": "gpr", "review": "true"},
        )
        assert created.status_code == 202, created.text
        job = created.json()["job"]
        assert job["state"] in ("IDENTIFIED", "NEEDS_INPUT")
        assert job["identification"]["detected_format"] == "segy"

        accepted = client.post(
            f"/api/imports/jobs/{job['id']}/accept",
            json={"coordinate_encoding": "ieee_nmea"},
        )
        assert accepted.status_code == 202, accepted.text

        # `accept` queues the job on the real background executor; run it
        # synchronously here, the same way test_auth_and_ownership.py's own
        # end-to-end import test does.
        from jobs import runner
        runner._execute(job["id"])

        final = client.get(f"/api/imports/jobs/{job['id']}").json()["job"]
        assert final["state"] == "SUCCEEDED", final
        dataset_id = final["dataset_id"]

        from database.records_store import load_records
        records = load_records(dataset_id, use_cache=False)
        assert records[0].latitude == IEEE_NMEA_LAT
        assert records[0].elevation == pytest.approx(12.5)

    def test_declaring_it_for_a_non_segy_upload_is_refused_at_accept(self, env, tmp_path):
        client = signed_in()
        csv_path = tmp_path / "async.csv"
        csv_path.write_text("lat,lon,depth,value\n52.0,6.0,1.0,3.5\n")

        created = client.post(
            "/api/imports",
            files={"file": ("async.csv", csv_path.read_bytes(), "text/csv")},
            data={"sensor_type": "gpr", "review": "true"},
        )
        job = created.json()["job"]
        resp = client.post(
            f"/api/imports/jobs/{job['id']}/accept",
            json={"coordinate_encoding": "ieee_nmea"},
        )
        assert resp.status_code == 422
        assert "cannot be applied to a csv file" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 8. Honesty: no fabricated position/elevation, and decoding never implies validation
# ---------------------------------------------------------------------------

class TestHonestFailureAndNonValidation:
    def test_non_finite_bytes_stay_no_position_not_a_fabricated_zero(self, env, tmp_path):
        segy_path = write_segy(
            tmp_path / "nan.sgy", source_x=-1, source_y=-1,  # 0xFFFFFFFF -> NaN under ieee_nmea
        )
        client = signed_in()
        resp = client.post(
            "/api/datasets/ingest",
            files={"file": ("nan.sgy", segy_path.read_bytes(), "application/octet-stream")},
            data={"sensor_type": "gpr", "coordinate_encoding": "ieee_nmea",
                  "apply_preprocessing": "false"},
        )
        assert resp.status_code == 200, resp.text
        from database.records_store import load_records
        records = load_records(resp.json()["dataset_id"], use_cache=False)
        assert records[0].position.kind == "none"
        assert records[0].latitude is None and records[0].longitude is None

    def test_no_elevation_header_field_leaves_elevation_missing_not_zero(self, env, tmp_path):
        """ieee_nmea decodes a position, but this file happens to carry no elevation field -- must stay None, never a fabricated 0.0."""
        segy_path = write_segy(
            tmp_path / "no_elev.sgy", source_x=IEEE_NMEA_SOURCE_X, source_y=IEEE_NMEA_SOURCE_Y,
        )  # receiver_group_elevation left None -> header bytes stay zero -> ev == 0.0 -> not finite&nonzero
        client = signed_in()
        resp = client.post(
            "/api/datasets/ingest",
            files={"file": ("no_elev.sgy", segy_path.read_bytes(), "application/octet-stream")},
            data={"sensor_type": "gpr", "coordinate_encoding": "ieee_nmea",
                  "apply_preprocessing": "false"},
        )
        assert resp.status_code == 200, resp.text
        from database.records_store import load_records
        records = load_records(resp.json()["dataset_id"], use_cache=False)
        assert records[0].latitude == IEEE_NMEA_LAT  # position still decoded
        assert records[0].elevation is None  # elevation genuinely absent, not zero

    def test_decoding_a_position_never_sets_a_verified_assumption(self, env, tmp_path):
        segy_path = _ieee_nmea_segy(tmp_path / "verify.sgy")
        client = signed_in()
        resp = client.post(
            "/api/datasets/ingest",
            files={"file": ("verify.sgy", segy_path.read_bytes(), "application/octet-stream")},
            data={"sensor_type": "gpr", "coordinate_encoding": "ieee_nmea",
                  "apply_preprocessing": "false"},
        )
        dataset_id = resp.json()["dataset_id"]
        from database.frames_store import load_frames
        frames = load_frames(dataset_id)
        encoding_claim = frames[0].assumption("segy_coordinate_encoding")
        elevation_claim = frames[0].assumption("acquisition_elevation_datum")
        assert encoding_claim is not None and encoding_claim.verified is False
        assert elevation_claim is not None and elevation_claim.verified is False
        assert elevation_claim.value is None  # no datum is claimed, ever


# ---------------------------------------------------------------------------
# 9. The evidence chain: ingest -> DEM align -> topographic correction -> report
# ---------------------------------------------------------------------------

class TestTopographicCorrectionChainReachable:
    """
    The acceptance question this whole milestone exists to answer: is the
    topographic correction's DERIVED path now reachable from data that went
    through REAL product ingestion, not a research script. Builds a real
    (synthetic) DEM GeoTIFF whose ground elevation genuinely varies under
    the ingested traces' real decoded positions -- no fabricated match, a
    real bilinear sample against a real raster.
    """

    def _write_dem(self, path, west, north, pixel_size, size, base, slope_per_pixel):
        rasterio = pytest.importorskip("rasterio")
        import numpy as np
        from rasterio.transform import from_origin

        transform = from_origin(west, north, pixel_size, pixel_size)
        data = np.fromfunction(
            lambda r, c: base + c * slope_per_pixel, (size, size), dtype="float32")
        with rasterio.open(
            str(path), "w", driver="GTiff", height=size, width=size, count=1,
            dtype="float32", crs="EPSG:4326", transform=transform,
        ) as dst:
            dst.write(data.astype("float32"), 1)
        return path

    def test_the_full_chain_is_reachable_through_real_ingest(self, env, tmp_path):
        client = signed_in()

        # Three traces at slightly different longitudes (still ieee_nmea-decoded,
        # same latitude) so the DEM's own real east-west slope gives each trace a
        # genuinely different ground elevation -- a real height-above-ground
        # variation, not an invented one.
        lons_raw = [IEEE_NMEA_SOURCE_X, IEEE_NMEA_SOURCE_X + 20000, IEEE_NMEA_SOURCE_X + 40000]
        antenna_elev = 12.5
        segy_path = tmp_path / "chain.sgy"
        s = "<"
        out = bytearray(b"\x00" * 3200)
        bh = bytearray(b"\x00" * 400)
        bh[16:18] = struct.pack(s + "h", 98)
        bh[20:22] = struct.pack(s + "h", 8)
        bh[24:26] = struct.pack(s + "h", 3)
        out += bh
        for i, raw_x in enumerate(lons_raw):
            th = bytearray(b"\x00" * 240)
            th[40:44] = struct.pack(s + "i", _int32_for_float(antenna_elev, s))
            th[68:70] = struct.pack(s + "h", 1)
            th[70:72] = struct.pack(s + "h", -1000)
            th[72:76] = struct.pack(s + "i", raw_x)
            th[76:80] = struct.pack(s + "i", IEEE_NMEA_SOURCE_Y)
            th[108:110] = struct.pack(s + "h", 0)
            th[114:116] = struct.pack(s + "h", 8)
            out += th
            out += struct.pack(f"{s}8h", *[(i * 10 + k) for k in range(8)])
        segy_path.write_bytes(bytes(out))

        resp = client.post(
            "/api/datasets/ingest",
            files={"file": ("chain.sgy", segy_path.read_bytes(), "application/octet-stream")},
            data={"sensor_type": "gpr", "coordinate_encoding": "ieee_nmea",
                  "apply_preprocessing": "false"},
        )
        assert resp.status_code == 200, resp.text
        dataset_id = resp.json()["dataset_id"]

        from database.records_store import load_records
        records = load_records(dataset_id, use_cache=False)
        assert all(r.elevation == pytest.approx(antenna_elev) for r in records)
        lons = sorted({r.longitude for r in records if r.longitude is not None})
        assert len(lons) == 3  # three genuinely different decoded positions

        # A real DEM covering all three traces, with a real east-west slope
        # (0.3 m per 0.001 degree ~ steep but physically arbitrary -- the point
        # is only that it is REAL raster sampling, not an invented number).
        dem_path = self._write_dem(
            tmp_path / "dem.tif", west=lons[0] - 0.01, north=52.2389 + 0.01,
            pixel_size=0.0001, size=600, base=10.0, slope_per_pixel=0.003,
        )

        align_resp = client.post(
            f"/api/datasets/{dataset_id}/align_dem",
            params={"dem_filename": str(dem_path)},
        )
        assert align_resp.status_code == 200, align_resp.text
        assert align_resp.json()["records_aligned"] > 0

        records_after_align = load_records(dataset_id, use_cache=False)
        assert any(r.metadata.get("pre_dem_elevation_m") == pytest.approx(antenna_elev)
                  for r in records_after_align)
        # record.elevation is now DEM ground elevation, genuinely different per trace.
        ground_elevations = {r.elevation for r in records_after_align}
        assert len(ground_elevations) > 1

        topo_resp = client.post(f"/api/datasets/{dataset_id}/apply_topographic_correction")
        assert topo_resp.status_code == 200, topo_resp.text
        frame_id = next(iter(topo_resp.json()["frames"]))
        result = topo_resp.json()["frames"][frame_id]
        # The evidence chain reached a real, non-UNAVAILABLE conclusion --
        # derived or not_material, either is a genuine answer computed from
        # real ingested + real DEM-sampled data, never UNAVAILABLE (which
        # would mean the chain never actually connected).
        assert result["status"] in ("derived", "not_material")
        assert result["status"] != "unavailable"

        # And the dataset report's own signal chain reflects it, exactly the
        # honesty surface this milestone exists to make reachable.
        chain_resp = client.get(f"/api/datasets/{dataset_id}/signal-chain")
        assert chain_resp.status_code == 200, chain_resp.text
        steps = {s["step"]: s for s in chain_resp.json()["steps"]}
        assert "topographic_correction" in steps
        assert steps["topographic_correction"]["parameters"]["topographic_correction_status"] \
            == result["status"]


# ---------------------------------------------------------------------------
# 10. Regression: /align_dem's own reporting must not claim success for
#     records it never actually matched against the DEM
# ---------------------------------------------------------------------------

class TestAlignDemReportingReflectsRealMatches:
    """
    A record ingested with coordinate_encoding=ieee_nmea already carries an
    antenna elevation BEFORE /align_dem ever runs. The endpoint's own
    records_aligned count used to be `sum(1 for r in records if r.elevation
    is not None)` -- true for every one of these records regardless of
    whether the DEM tile covered them at all, so a DEM that matched nothing
    still reported full success. Fixed to use the real per-call count
    `align_records_with_dem_with_count` returns.
    """

    def test_a_dem_that_covers_nothing_reports_zero_not_the_record_count(self, env, tmp_path):
        rasterio = pytest.importorskip("rasterio")
        import numpy as np
        from rasterio.transform import from_origin

        client = signed_in()
        segy_path = _ieee_nmea_segy(tmp_path / "unmatched.sgy")
        resp = client.post(
            "/api/datasets/ingest",
            files={"file": ("unmatched.sgy", segy_path.read_bytes(), "application/octet-stream")},
            data={"sensor_type": "gpr", "coordinate_encoding": "ieee_nmea",
                  "apply_preprocessing": "false"},
        )
        dataset_id = resp.json()["dataset_id"]

        from database.records_store import load_records
        before = load_records(dataset_id, use_cache=False)
        assert all(r.elevation is not None for r in before)  # the pre-existing antenna elevation

        # A real DEM tile, real distance away from every real decoded position.
        dem_path = tmp_path / "far_away.tif"
        transform = from_origin(-179.0, 89.0, 0.01, 0.01)
        data = np.full((10, 10), 5.0, dtype="float32")
        with rasterio.open(
            str(dem_path), "w", driver="GTiff", height=10, width=10, count=1,
            dtype="float32", crs="EPSG:4326", transform=transform,
        ) as dst:
            dst.write(data, 1)

        align_resp = client.post(
            f"/api/datasets/{dataset_id}/align_dem", params={"dem_filename": str(dem_path)},
        )
        assert align_resp.status_code == 200, align_resp.text
        assert align_resp.json()["records_aligned"] == 0

        after = load_records(dataset_id, use_cache=False)
        # untouched -- still the antenna elevation, not silently claimed aligned
        assert after[0].elevation == pytest.approx(before[0].elevation)
        assert "pre_dem_elevation_m" not in after[0].metadata
