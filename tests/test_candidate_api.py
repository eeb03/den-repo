"""
The candidate API and its store, end to end on real records.

WHAT THIS COVERS THAT THE SCHEMA TESTS DO NOT. `test_candidate_intelligence.py`
holds the rules a candidate must obey. This holds that the pipeline actually
obeys them when driven through the API on records that went through the real
preprocessing path -- including the two states that matter most in practice: a
dataset that has not been preprocessed (BLOCKED, with something actionable), and
a stored set that no longer matches its dataset (LIMITED, with a reason).
"""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import app
from configs.settings import settings
from database.candidates_store import (
    StoredCandidateSet, delete_candidates, load_candidates, save_candidates, set_status,
)
from interpretation.candidate_intelligence import (
    CandidateGeneration, CandidateStatus, GenerationParameters, inspectable, utcnow,
)
from preprocessing.spatial_grid import preprocess_trace_local_anomaly
from schemas.subterra_record import SensorType, SubterraRecord

from tests.test_candidate_intelligence import make_candidate

client = TestClient(app)
DATASET = "candidate-api-test"


@pytest.fixture(autouse=True)
def clean_store(tmp_path, monkeypatch):
    """
    Each test gets its own processed_dir and its own database.

    The routes take a session because staleness depends on the spatial
    declarations, so a real (if empty) database is part of the surface under
    test rather than something to mock away.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database.session import Base, get_db

    monkeypatch.setattr(type(settings), "processed_dir", property(lambda self: tmp_path))

    engine = create_engine(f"sqlite:///{tmp_path / 'candidates.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    delete_candidates(DATASET)


def a_stored_set(dataset_id=DATASET, n=3, **generation_kwargs) -> StoredCandidateSet:
    generation = CandidateGeneration(
        generated_at=utcnow(), dataset_id=dataset_id,
        input_fingerprint="fp0", **generation_kwargs)
    return StoredCandidateSet(
        dataset_id=dataset_id, generation=generation, n_traces=1000,
        candidates=[inspectable(make_candidate(candidate_id=f"c{i}", peak=3.0 + i))
                    for i in range(n)])


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------

def test_a_saved_set_round_trips():
    save_candidates(a_stored_set())
    loaded = load_candidates(DATASET)
    assert loaded is not None
    assert len(loaded.candidates) == 3
    assert loaded.generation.dataset_id == DATASET


def test_a_dataset_with_no_generation_has_no_set():
    assert load_candidates("never-generated") is None


def test_regenerating_replaces_rather_than_accumulates():
    save_candidates(a_stored_set(n=3))
    save_candidates(a_stored_set(n=2))
    assert len(load_candidates(DATASET).candidates) == 2


def test_a_review_decision_survives_regeneration():
    """
    A candidate id encodes its dataset, file, cluster and parameters, so an id
    that survives refers to the same region found the same way. Discarding a
    reviewer's work in that case would be losing information for nothing.
    """
    save_candidates(a_stored_set(n=3))
    set_status(DATASET, "c1", CandidateStatus.ACCEPTED)

    save_candidates(a_stored_set(n=3))
    kept = {c.candidate.id: c.status for c in load_candidates(DATASET).candidates}
    assert kept["c1"] is CandidateStatus.ACCEPTED
    assert kept["c0"] is CandidateStatus.PROPOSED


def test_accepting_a_candidate_changes_only_its_status():
    save_candidates(a_stored_set())
    before = load_candidates(DATASET).candidates[0].model_dump()
    set_status(DATASET, "c0", CandidateStatus.ACCEPTED)
    after = load_candidates(DATASET).candidates[0].model_dump()

    assert after.pop("status") != before.pop("status")
    assert after == before, "review must not alter evidence, score or certainty"


def test_reviewing_an_unknown_candidate_reports_nothing_changed():
    save_candidates(a_stored_set())
    assert set_status(DATASET, "no-such-id", CandidateStatus.ACCEPTED) is None


# ---------------------------------------------------------------------------
# the API surface
# ---------------------------------------------------------------------------

def test_the_vocabulary_states_that_acceptance_is_not_ground_truth():
    body = client.get("/api/candidates/vocabulary").json()
    assert "NOT ground truth" in body["review_status"]["accepted"]
    assert body["classification_status"] == "BLOCKED"
    assert "not a probability" in body["candidate_score"]


def test_the_vocabulary_carries_the_measured_performance():
    body = client.get("/api/candidates/vocabulary").json()
    assert "chance" in body["benchmark"]["summary"]


def test_reading_a_dataset_without_candidates_is_blocked_with_an_action():
    body = client.get(f"/api/candidates/{DATASET}").json()
    assert body["status"] == "blocked"
    assert body["missing"], "a blocked state nobody can act on is a dead end"


def test_a_stored_set_is_served_with_its_generation_and_benchmark():
    save_candidates(a_stored_set())
    body = client.get(f"/api/candidates/{DATASET}").json()

    assert body["candidate_count"] == 3
    assert body["generation"]["method_version"]
    assert body["classification_status"] == "BLOCKED"
    assert body["benchmark"]["measurements"]
    assert "not a detected object" in body["definition"]


def test_candidates_come_back_ranked_by_score():
    save_candidates(a_stored_set(n=3))
    body = client.get(f"/api/candidates/{DATASET}").json()
    scores = [c["candidate_score"] for c in body["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_inspecting_a_candidate_returns_its_evidence_chain():
    save_candidates(a_stored_set())
    body = client.get(f"/api/candidates/{DATASET}/c0").json()

    chain = body["evidence_chain"]
    assert chain["source_file"] == "Line1.sgy"
    assert chain["trace_range"] == [10, 14]
    assert body["classification_status"] == "BLOCKED"


def test_inspecting_an_unknown_candidate_is_a_404():
    save_candidates(a_stored_set())
    assert client.get(f"/api/candidates/{DATASET}/nope").status_code == 404


def test_reviewing_through_the_api_says_what_acceptance_does_not_mean():
    save_candidates(a_stored_set())
    body = client.post(f"/api/candidates/{DATASET}/c0/status?status=accepted").json()
    assert body["status"] == "accepted"
    assert "does not make this candidate a detection" in body["note"]


def test_a_trace_span_below_one_is_refused():
    """K=1 admits everything; below that is not a weaker filter, it is nonsense."""
    response = client.post(f"/api/candidates/{DATASET}/generate?min_trace_span=0")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# generation on real preprocessed records
# ---------------------------------------------------------------------------

def a_survey_line(n_traces=40, n_samples=60, seed=0) -> list[SubterraRecord]:
    """
    A synthetic B-scan, used ONLY to exercise the pipeline's plumbing.

    Nothing measured is claimed from it and no result derived from it is
    reported as science -- it exists so that generation can be driven over
    records that carry genuine `anomaly_reliable` metadata from the real
    preprocessing function rather than hand-set flags.
    """
    rng = np.random.default_rng(seed)
    amplitudes = rng.normal(0.0, 1.0, size=(n_traces, n_samples))
    amplitudes[20:24, 30:34] += 25.0          # something for the rule to find

    records = []
    for t in range(n_traces):
        for s in range(n_samples):
            records.append(SubterraRecord(
                dataset_id=DATASET, sensor_type=SensorType.GPR,
                depth=s * 0.01, signal=[float(amplitudes[t, s])],
                # source_file and trace_index live in metadata: trace_index is
                # only unique within one file, so the pipeline groups on both.
                metadata={"source_file": "Line1.sgy", "trace_index": t,
                          "sample_index": s}))
    return records


def test_generation_over_unpreprocessed_records_is_blocked_not_an_error(monkeypatch):
    """
    The detector raises on raw amplitude, correctly -- reading it as a z-score
    would misinterpret physical units as statistical evidence. An exception is
    not a useful answer to a user, so the service turns it into a named state.
    """
    from api import candidates as service

    monkeypatch.setattr(service, "load_records", lambda *a, **k: a_survey_line())
    result = service.generate(db=None, dataset_id=DATASET)

    assert result.status == "blocked"
    assert any("gpr_local_anomaly" in m for m in result.missing)


def test_a_grid_mode_anomaly_dataset_is_blocked_rather_than_crashing(monkeypatch):
    """
    FOUND BY BROWSER VERIFICATION on the Lazaresti depth slice.

    That dataset carries `anomaly_reliable` from the (lat, lon) GRID anomaly
    mode -- a genuine z-score over a different geometry -- but its records have
    no trace index. Checking only the reliability flag let it through to a
    ValueError deep in the grid builder, which reaches the user as a 500.
    Two preprocessing modes are two capabilities, and the difference has to be
    an answer rather than a stack trace.
    """
    from api import candidates as service

    grid_mode = [
        SubterraRecord(
            dataset_id=DATASET, sensor_type=SensorType.GPR,
            latitude=45.9 + i * 1e-4, longitude=25.8, depth=0.25,
            signal=[1.0], metadata={"anomaly_reliable": True})
        for i in range(10)
    ]
    monkeypatch.setattr(service, "load_records", lambda *a, **k: grid_mode)
    result = service.generate(db=None, dataset_id=DATASET)

    assert result.status == "blocked"
    assert "no trace index" in result.status_reason
    assert result.missing


def test_generation_over_preprocessed_records_produces_a_provenanced_set(monkeypatch):
    from api import candidates as service

    processed = preprocess_trace_local_anomaly(a_survey_line())
    monkeypatch.setattr(service, "load_records", lambda *a, **k: processed)
    monkeypatch.setattr(service, "_newest_declaration_at", lambda db, d: None)

    result = service.generate(db=None, dataset_id=DATASET)

    assert result.status == "available"
    assert result.generation is not None
    assert result.generation.method_version
    assert result.generation.n_records == len(processed)
    assert result.generation.deterministic is True
    assert result.candidate_burden is not None


def test_generation_is_reproducible(monkeypatch):
    """Same records, same parameters, same method: the same candidate set."""
    from api import candidates as service

    processed = preprocess_trace_local_anomaly(a_survey_line())
    monkeypatch.setattr(service, "load_records", lambda *a, **k: processed)
    monkeypatch.setattr(service, "_newest_declaration_at", lambda db, d: None)

    first = service.generate(db=None, dataset_id=DATASET)
    second = service.generate(db=None, dataset_id=DATASET)

    assert [c.candidate.id for c in first.candidates] == \
           [c.candidate.id for c in second.candidates]
    assert first.generation.input_fingerprint == second.generation.input_fingerprint


def test_a_stricter_trace_span_never_adds_candidates(monkeypatch):
    """
    The filter is a post-filter, so it can only remove. This is the property the
    BAM experiment relied on when it evaluated every arm from one detection pass.
    """
    from api import candidates as service

    processed = preprocess_trace_local_anomaly(a_survey_line())
    monkeypatch.setattr(service, "load_records", lambda *a, **k: processed)
    monkeypatch.setattr(service, "_newest_declaration_at", lambda db, d: None)

    baseline = service.generate(db=None, dataset_id=DATASET,
                                parameters=GenerationParameters(min_trace_span=1))
    stricter = service.generate(db=None, dataset_id=DATASET,
                                parameters=GenerationParameters(min_trace_span=3))
    assert stricter.candidate_count <= baseline.candidate_count


def test_changed_records_make_the_stored_set_report_itself_stale(monkeypatch):
    from api import candidates as service

    processed = preprocess_trace_local_anomaly(a_survey_line())
    monkeypatch.setattr(service, "load_records", lambda *a, **k: processed)
    monkeypatch.setattr(service, "_newest_declaration_at", lambda db, d: None)
    service.generate(db=None, dataset_id=DATASET)

    # The dataset is reprocessed and now holds different records.
    monkeypatch.setattr(service, "load_records",
                        lambda *a, **k: preprocess_trace_local_anomaly(
                            a_survey_line(n_traces=30, seed=1)))
    result = service.current(db=None, dataset_id=DATASET)

    assert result.staleness.is_stale
    assert result.status == "limited"
    assert any("records have changed" in r for r in result.staleness.reasons)


def test_a_stale_set_is_still_returned_rather_than_hidden(monkeypatch):
    """Concealing it would replace a visible problem with an invisible one."""
    from api import candidates as service

    processed = preprocess_trace_local_anomaly(a_survey_line())
    monkeypatch.setattr(service, "load_records", lambda *a, **k: processed)
    monkeypatch.setattr(service, "_newest_declaration_at", lambda db, d: None)
    generated = service.generate(db=None, dataset_id=DATASET)

    monkeypatch.setattr(service, "load_records",
                        lambda *a, **k: preprocess_trace_local_anomaly(
                            a_survey_line(n_traces=30, seed=1)))
    stale = service.current(db=None, dataset_id=DATASET)
    assert stale.candidate_count == generated.candidate_count


def test_the_candidate_store_is_cleaned_up_with_its_dataset():
    """
    Stage 7 found 167 MB of orphaned artifacts because a store was added and
    quietly not cleaned up. The suffix registry exists to stop that recurring.
    """
    from api.dataset_lifecycle import ARTIFACT_SUFFIXES

    assert ".candidates.json" in ARTIFACT_SUFFIXES
