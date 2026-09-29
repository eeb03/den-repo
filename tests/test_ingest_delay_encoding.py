"""
`delay_encoding` through real product ingest.

The converter accepts `delay_encoding` (tests/test_segy_time_axis.py); these
tests prove a user can actually reach it -- the upload route, the local-file
route and the review/accept flow -- and that an invalid or inapplicable value
is refused rather than silently ignored. Mirrors coordinate_encoding's own
tests (tests/test_ingest_coordinate_encoding.py), whose live-HTTP harness this
reuses.
"""
import pydantic
import pytest
from fastapi import HTTPException

from tests.test_ingest_coordinate_encoding import env, signed_in  # noqa: F401
from tests.test_segy_time_axis import write_segy


class TestAcceptRequest:
    def test_a_known_value_is_accepted(self):
        from api.routes.imports import AcceptRequest
        assert AcceptRequest(delay_encoding="sample_interval_unit").delay_encoding == \
            "sample_interval_unit"

    def test_none_is_the_default(self):
        from api.routes.imports import AcceptRequest
        assert AcceptRequest().delay_encoding is None

    def test_an_unknown_value_fails_at_construction(self):
        from api.routes.imports import AcceptRequest
        with pytest.raises(pydantic.ValidationError, match="unknown delay_encoding"):
            AcceptRequest(delay_encoding="picoseconds")


class TestValidatedIngestOptions:
    def _job(self, fmt):
        from database.models import ImportJob
        return ImportJob(id="j", identification={"detected_format": fmt})

    def test_segy_accepts_it_alongside_coordinate_encoding(self):
        from api import acquisition
        from api.routes.imports import AcceptRequest
        body = AcceptRequest(delay_encoding="sample_interval_unit",
                             coordinate_encoding="int32_scalar_exponent")
        assert acquisition.validated_ingest_options(self._job("segy"), body) == {
            "delay_encoding": "sample_interval_unit",
            "coordinate_encoding": "int32_scalar_exponent",
        }

    def test_a_non_segy_format_refuses_it(self):
        from api import acquisition
        from api.routes.imports import AcceptRequest
        with pytest.raises(HTTPException) as exc:
            acquisition.validated_ingest_options(
                self._job("mala"), AcceptRequest(delay_encoding="sample_interval_unit"))
        assert "cannot be applied to a mala file" in exc.value.detail


def _upload(client, path, **data):
    return client.post(
        "/api/datasets/ingest",
        files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
        data={"sensor_type": "gpr", "apply_preprocessing": "false", **data},
    )


class TestUploadEndpoint:
    def test_the_declared_dialect_reaches_the_records_and_frame(self, env, tmp_path):
        client = signed_in("delay-owner@example.test")
        resp = _upload(client, write_segy(tmp_path / "fn.segy", n_samples=40, delay=10342),
                       delay_encoding="sample_interval_unit")
        assert resp.status_code == 200, resp.text
        dataset_id = resp.json()["dataset_id"]

        from database.frames_store import load_frames
        from database.records_store import load_records
        first = load_records(dataset_id, use_cache=False)[0]
        assert first.metadata["two_way_time_ns"] == pytest.approx(10.342)
        frame = load_frames(dataset_id)[0]
        assert frame.source_metadata["segy_delay_encoding"] == "sample_interval_unit"
        assert frame.assumption("segy_delay_encoding").value == "sample_interval_unit"

    def test_omitting_it_keeps_the_standard_reading(self, env, tmp_path):
        client = signed_in("delay-default@example.test")
        resp = _upload(client, write_segy(tmp_path / "fn.segy", n_samples=40, delay=10342))
        assert resp.status_code == 200, resp.text
        from database.records_store import load_records
        first = load_records(resp.json()["dataset_id"], use_cache=False)[0]
        assert first.metadata["two_way_time_ns"] == pytest.approx(10342.0)

    def test_an_unknown_value_is_a_clean_422(self, env, tmp_path):
        client = signed_in("delay-bad@example.test")
        resp = _upload(client, write_segy(tmp_path / "fn.segy", n_samples=40),
                       delay_encoding="picoseconds")
        assert resp.status_code == 422
        assert "unknown delay_encoding" in resp.json()["detail"]

    def test_it_is_refused_on_a_non_segy_upload(self, env, tmp_path):
        client = signed_in("delay-csv@example.test")
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("latitude,longitude,value\n52.0,6.0,1.0\n52.1,6.1,2.0\n")
        resp = client.post(
            "/api/datasets/ingest",
            files={"file": ("data.csv", csv_path.read_bytes(), "text/csv")},
            data={"sensor_type": "gpr", "delay_encoding": "sample_interval_unit"},
        )
        assert resp.status_code == 422
        assert "cannot be applied" in resp.json()["detail"]


def test_the_local_file_request_validates_it():
    from api.routes.datasets import IngestLocalFileRequest
    with pytest.raises(pydantic.ValidationError, match="unknown delay_encoding"):
        IngestLocalFileRequest(path="x.segy", sensor_type="gpr", delay_encoding="bad")
