"""
The read-only benchmark artifacts endpoint.

The point of this endpoint is that a client can show the validated BAM and
4TU results without keeping a second copy of the numbers. That is only
worth anything if what comes back is byte-identical to what the scoring
script wrote, so most of what is asserted here is a form of "nothing
happened to it": same bytes, same key order, same float formatting, no
extra fields, no file touched.

The other half is that a name cannot be used to read a file that is not a
benchmark artifact.
"""
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.routes.benchmark as bench
from api.main import app


#: A realistic artifact: unsorted keys, a long float, a nested structure and
#: a BLOCKED gate, so "verbatim" is actually testable rather than trivially
#: true for a one-key file.
SAMPLE = (
    '{\n'
    '  "benchmark": "bam-concrete-gpr",\n'
    '  "localization_status": "BLOCKED",\n'
    '  "localization_blocked_reason": "absolute origin is not verified",\n'
    '  "threshold": 3.0,\n'
    '  "open_questions": ["absolute-origin", "coordinate-units"],\n'
    '  "detection": {"recall": 0.06521739130434782, "precision": 0.13513513513513514,\n'
    '                "true_positives": 45, "false_negatives": 602},\n'
    '  "aaa_sorts_last_on_purpose": true\n'
    '}\n'
)


@pytest.fixture()
def artifacts(tmp_path, monkeypatch):
    """Points the endpoint at a temporary artifacts tree."""
    root = tmp_path / "artifacts"
    (root / "bam").mkdir(parents=True)
    (root / "4tu").mkdir(parents=True)
    (root / "bam" / "score_1_5_GHz_Rot00.json").write_text(SAMPLE)
    (root / "4tu" / "benchmark.json").write_text('{"benchmark": "4tu-nl-utility"}')
    monkeypatch.setattr(bench, "_artifacts_root", lambda: root)
    return root


@pytest.fixture()
def client(artifacts):
    return TestClient(app)


# --- listing ---------------------------------------------------------------

def test_listing_reports_the_artifacts_that_exist(client):
    body = client.get("/api/benchmark/artifacts").json()
    names = {a["name"] for a in body["artifacts"]}
    assert names == {"bam/score_1_5_GHz_Rot00", "4tu/benchmark"}
    assert body["count"] == 2
    assert {a["group"] for a in body["artifacts"]} == {"bam", "4tu"}


def test_an_ungenerated_artifact_is_omitted_rather_than_invented(client, artifacts):
    """
    artifacts/ is gitignored and regenerable, so "not generated yet" is a
    normal state. It must read as absence, not as an error and not as an
    empty result that could be mistaken for a real one.
    """
    (artifacts / "bam" / "score_1_5_GHz_Rot00.json").unlink()
    body = client.get("/api/benchmark/artifacts").json()
    assert {a["name"] for a in body["artifacts"]} == {"4tu/benchmark"}
    assert body["count"] == 1


def test_an_absent_artifacts_directory_lists_empty_and_does_not_create_it(
    client, artifacts, monkeypatch, tmp_path
):
    missing = tmp_path / "not_generated_at_all"
    monkeypatch.setattr(bench, "_artifacts_root", lambda: missing)
    r = client.get("/api/benchmark/artifacts")
    assert r.status_code == 200
    assert r.json()["artifacts"] == [] and r.json()["count"] == 0
    assert not missing.exists(), "listing must not create the artifacts directory"


def test_listing_carries_no_scientific_content(client):
    """Names and file facts only -- no metric is lifted out of the artifact."""
    entry = next(a for a in client.get("/api/benchmark/artifacts").json()["artifacts"]
                 if a["name"] == "bam/score_1_5_GHz_Rot00")
    assert set(entry) == {"name", "group", "filename", "size_bytes"}


# --- verbatim retrieval ----------------------------------------------------

def test_an_artifact_is_returned_byte_for_byte(client):
    """
    Not "equal as parsed JSON" -- byte-identical. Key order and float
    formatting are part of what the scoring script produced, and a
    re-serialised copy is a different artifact.
    """
    r = client.get("/api/benchmark/artifacts/bam/score_1_5_GHz_Rot00")
    assert r.status_code == 200
    assert r.content.decode() == SAMPLE
    assert r.headers["content-type"].startswith("application/json")


def test_key_order_survives_and_nothing_is_sorted(client):
    r = client.get("/api/benchmark/artifacts/bam/score_1_5_GHz_Rot00")
    keys = list(json.loads(r.content).keys())
    assert keys[0] == "benchmark"
    assert keys[-1] == "aaa_sorts_last_on_purpose"


def test_no_field_is_added_removed_or_derived(client):
    got = json.loads(client.get(
        "/api/benchmark/artifacts/bam/score_1_5_GHz_Rot00").content)
    assert got == json.loads(SAMPLE)


def test_metrics_and_gate_status_pass_through_untransformed(client):
    """
    The recall the BAM scorer recorded is what a reader must see -- not a
    rounded, rescaled or percentage-ised version of it, and BLOCKED must
    still say BLOCKED.
    """
    got = json.loads(client.get(
        "/api/benchmark/artifacts/bam/score_1_5_GHz_Rot00").content)
    assert got["detection"]["recall"] == 0.06521739130434782
    assert got["detection"]["precision"] == 0.13513513513513514
    assert got["localization_status"] == "BLOCKED"
    assert got["localization_blocked_reason"] == "absolute origin is not verified"
    assert got["threshold"] == 3.0
    assert got["open_questions"] == ["absolute-origin", "coordinate-units"]


# --- missing ---------------------------------------------------------------

def test_a_missing_artifact_is_404_and_nothing_is_generated(client, artifacts):
    r = client.get("/api/benchmark/artifacts/bam/never_scored")
    assert r.status_code == 404
    assert "not have been generated" in r.json()["detail"]
    assert not (artifacts / "bam" / "never_scored.json").exists()


def test_a_missing_group_is_404(client):
    assert client.get("/api/benchmark/artifacts/nosuch/benchmark").status_code == 404


# --- the name cannot escape the artifacts directory ------------------------

@pytest.mark.parametrize("name", [
    "../../../etc/passwd",
    "bam/../../etc/passwd",
    "bam/../../../.env",
    "..%2f..%2f.env",
    "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "/etc/passwd",
    "bam/./../../requirements.txt",
    "....//....//.env",
    "bam/score_1_5_GHz_Rot00/../../../.env",
])
def test_traversal_cannot_read_anything_outside_the_artifacts_directory(client, name):
    r = client.get(f"/api/benchmark/artifacts/{name}")
    assert r.status_code == 404, f"{name!r} returned {r.status_code}"
    body = r.content.decode()
    for leak in ("root:", "DATABASE_URL", "fastapi==", "PATH="):
        assert leak not in body


def test_a_file_outside_a_group_directory_is_not_reachable(client, artifacts, tmp_path):
    """A JSON file beside the artifacts tree is not an artifact."""
    secret = tmp_path / "secret.json"
    secret.write_text('{"credential": "hunter2"}')
    for attempt in ("../secret", "secret", "./secret"):
        r = client.get(f"/api/benchmark/artifacts/{attempt}")
        assert r.status_code == 404
        assert "hunter2" not in r.content.decode()


def test_only_json_files_are_served(client, artifacts):
    (artifacts / "bam" / "notes.txt").write_text("not an artifact")
    (artifacts / "bam" / "model.bin").write_bytes(b"\x00\x01")
    names = {a["name"] for a in client.get("/api/benchmark/artifacts").json()["artifacts"]}
    assert "bam/notes" not in names and "bam/model" not in names
    assert client.get("/api/benchmark/artifacts/bam/notes").status_code == 404


def test_traversal_is_blocked_at_the_handler_not_by_the_http_client(artifacts):
    """
    The parametrised traversal test above goes through TestClient, which
    normalises a URL before it is ever dispatched -- so on its own it could
    pass without the handler doing anything. This drives the ASGI app
    directly with an un-normalised raw path, so what is asserted is the
    endpoint's own behaviour.
    """
    import asyncio

    async def raw_get(raw_path: str) -> tuple[int, bytes]:
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "path": raw_path, "raw_path": raw_path.encode(),
            "query_string": b"", "headers": [(b"host", b"test")],
            "client": ("t", 1), "server": ("t", 80), "scheme": "http", "root_path": "",
        }
        captured: dict = {"body": b""}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
            elif message["type"] == "http.response.body":
                captured["body"] += message.get("body", b"")

        await app(scope, receive, send)
        return captured["status"], captured["body"]

    async def run():
        for raw in (
            "/api/benchmark/artifacts/../../../etc/passwd",
            "/api/benchmark/artifacts/bam/../../.env",
            "/api/benchmark/artifacts/bam/../../requirements.txt",
            "/api/benchmark/artifacts//etc/passwd",
            "/api/benchmark/artifacts/....//....//.env",
        ):
            status, body = await raw_get(raw)
            assert status == 404, f"{raw!r} returned {status}"
            text = body.decode(errors="replace")
            for leak in ("root:", "DATABASE_URL", "fastapi==", "PATH="):
                assert leak not in text, f"{raw!r} leaked {leak!r}"

        # control: a legitimate name still resolves through the same path
        status, body = await raw_get("/api/benchmark/artifacts/bam/score_1_5_GHz_Rot00")
        assert status == 200
        assert json.loads(body)["localization_status"] == "BLOCKED"

    asyncio.run(run())


def test_a_symlinked_artifact_is_not_followed(client, artifacts, tmp_path):
    """A symlink into the tree must not become a way out of it."""
    outside = tmp_path / "outside.json"
    outside.write_text('{"credential": "hunter2"}')
    link = artifacts / "bam" / "sneaky.json"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    names = {a["name"] for a in client.get("/api/benchmark/artifacts").json()["artifacts"]}
    assert "bam/sneaky" not in names
    r = client.get("/api/benchmark/artifacts/bam/sneaky")
    assert r.status_code == 404 and "hunter2" not in r.content.decode()


# --- read-only -------------------------------------------------------------

def test_the_endpoint_mutates_nothing_on_disk(client, artifacts):
    """
    Snapshot every path, size and content under artifacts/ before and after
    exercising both endpoints. Nothing may be created, removed or rewritten.
    """
    def snapshot():
        return {
            str(p.relative_to(artifacts)): p.read_bytes()
            for p in sorted(artifacts.rglob("*")) if p.is_file()
        }

    before = snapshot()
    client.get("/api/benchmark/artifacts")
    client.get("/api/benchmark/artifacts/bam/score_1_5_GHz_Rot00")
    client.get("/api/benchmark/artifacts/4tu/benchmark")
    client.get("/api/benchmark/artifacts/bam/does_not_exist")
    client.get("/api/benchmark/artifacts/../../etc/passwd")
    assert snapshot() == before


def test_repeated_reads_are_identical(client):
    a = client.get("/api/benchmark/artifacts/bam/score_1_5_GHz_Rot00").content
    b = client.get("/api/benchmark/artifacts/bam/score_1_5_GHz_Rot00").content
    assert a == b == SAMPLE.encode()


def test_only_get_is_exposed(client):
    """No write verb reaches an artifact."""
    for verb in ("post", "put", "patch", "delete"):
        r = getattr(client, verb)("/api/benchmark/artifacts/bam/score_1_5_GHz_Rot00")
        assert r.status_code == 405, f"{verb.upper()} returned {r.status_code}"


def test_a_truncated_artifact_is_refused_rather_than_served(client, artifacts):
    """Half a result must not be presented as a whole one."""
    (artifacts / "bam" / "partial.json").write_text('{"benchmark": "bam", "detec')
    r = client.get("/api/benchmark/artifacts/bam/partial")
    assert r.status_code == 500
    assert "not well-formed JSON" in r.json()["detail"]


# --- the real artifacts, when they are present ------------------------------

def test_the_real_artifacts_are_served_unchanged_when_present(monkeypatch):
    """
    Runs against the repository's own artifacts/ rather than a fixture.
    Skipped when they have not been generated, which is a normal state.
    """
    real = Path("artifacts")
    if not real.is_dir():
        pytest.skip("artifacts/ has not been generated")
    monkeypatch.setattr(bench, "_artifacts_root", lambda: real.resolve())
    c = TestClient(app)

    listed = c.get("/api/benchmark/artifacts").json()["artifacts"]
    if not listed:
        pytest.skip("artifacts/ contains no scoring artifacts")

    for entry in listed:
        on_disk = (real / entry["group"] / entry["filename"]).read_bytes()
        served = c.get(f"/api/benchmark/artifacts/{entry['name']}").content
        assert served == on_disk, f"{entry['name']} was not served verbatim"
