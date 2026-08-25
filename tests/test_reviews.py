"""
Human-in-the-Loop Anomaly Verification V1: schema, store, corpus conversion,
and the API end to end.

Default (non-`real_auth`) tests use conftest's fixed test identity and a
seeded Dataset row whose ownership is not enforced -- appropriate for
everything that is not itself about authorisation. The ownership/cross-user
tests are `real_auth`, mirroring `tests/test_auth_and_ownership.py` exactly:
real registration, real sessions, real per-user datasets.
"""
from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import app
from configs.settings import settings
from database.candidates_store import StoredCandidateSet, save_candidates
from database.reviews_store import delete_reviews, load_reviews, upsert_review
from interpretation.candidate_intelligence import CandidateGeneration, inspectable, utcnow
from schemas.review import (
    AnnotationGeometry, AnnotationGeometryKind, CandidateReview, ReviewStatus, make_review_id,
)
from schemas.segmentation import EvidenceGrade, LabelSource
from tests.test_candidate_intelligence import make_candidate

client = TestClient(app)
DATASET = "review-api-test"


@pytest.fixture(autouse=True)
def clean_store(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database.session import Base, get_db

    monkeypatch.setattr(type(settings), "processed_dir", property(lambda self: tmp_path))

    engine = create_engine(f"sqlite:///{tmp_path / 'reviews.db'}",
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
    delete_reviews(DATASET)


def _seed_candidate(dataset_id=DATASET, candidate_id="c0", peak=4.2) -> str:
    generation = CandidateGeneration(
        generated_at=utcnow(), dataset_id=dataset_id, input_fingerprint="fp0",
        method="ring_local_anomaly_connected_components", method_version="1.0.0")
    stored = StoredCandidateSet(
        dataset_id=dataset_id, generation=generation, n_traces=1000,
        candidates=[inspectable(make_candidate(candidate_id=candidate_id, peak=peak))])
    save_candidates(stored)
    return candidate_id


# ---------------------------------------------------------------------------
# 1-5: review states + semantic labels (schema + API)
# ---------------------------------------------------------------------------

def test_create_review_confirmed():
    candidate_id = _seed_candidate()
    r = client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}",
                    json={"review_status": "confirmed"})
    assert r.status_code == 200
    assert r.json()["review_status"] == "confirmed"


def test_rejected_candidate():
    candidate_id = _seed_candidate()
    r = client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}",
                    json={"review_status": "rejected"})
    assert r.status_code == 200
    assert r.json()["review_status"] == "rejected"


def test_uncertain_candidate():
    candidate_id = _seed_candidate()
    r = client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}",
                    json={"review_status": "uncertain"})
    assert r.status_code == 200
    assert r.json()["review_status"] == "uncertain"


def test_confirmed_without_semantic_identity_is_first_class():
    """Section 4's own 'critical valid state': CONFIRMED with no operator_label."""
    candidate_id = _seed_candidate()
    r = client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}",
                    json={"review_status": "confirmed", "operator_label": None})
    assert r.status_code == 200
    body = r.json()
    assert body["review_status"] == "confirmed"
    assert body["operator_label"] is None


def test_semantic_operator_label():
    candidate_id = _seed_candidate()
    r = client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}",
                    json={"review_status": "confirmed", "operator_label": "pipe"})
    assert r.status_code == 200
    assert r.json()["operator_label"] == "pipe"


def test_operator_label_outside_vocabulary_is_rejected():
    with pytest.raises(Exception):
        CandidateReview(
            dataset_id=DATASET, source_file="f.sgy", trace_range=(0, 1),
            reviewer_id="u", operator_label="dinosaur_bone",
        )


# ---------------------------------------------------------------------------
# 6-8: detector output immutable, provenance, history
# ---------------------------------------------------------------------------

def test_detector_output_unchanged_across_reviews():
    """Section 9: re-reviewing must never alter the frozen detector_snapshot."""
    candidate_id = _seed_candidate(peak=5.5)
    r1 = client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}",
                     json={"review_status": "uncertain"})
    snapshot_1 = r1.json()["detector_snapshot"]
    assert snapshot_1["candidate_score"] == pytest.approx(5.5)

    r2 = client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}",
                     json={"review_status": "confirmed", "operator_label": "pipe"})
    snapshot_2 = r2.json()["detector_snapshot"]
    assert snapshot_2 == snapshot_1


def test_provenance_is_always_grade_c_operator_reviewed():
    candidate_id = _seed_candidate()
    r = client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}",
                    json={"review_status": "confirmed"})
    body = r.json()
    assert body["evidence_grade"] == EvidenceGrade.C_OPERATOR_REVIEWED.value
    assert body["label_source"] == LabelSource.OPERATOR_REVIEWED.value
    assert body["ground_truth_status"] == "not_independently_validated"


def test_review_history_preserves_prior_state():
    """Section 10: UNCERTAIN -> CONFIRMED must not silently erase the prior state."""
    candidate_id = _seed_candidate()
    client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}",
               json={"review_status": "uncertain", "notes": "not sure yet"})
    r = client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}",
                    json={"review_status": "confirmed", "notes": "now sure"})
    body = r.json()
    assert body["review_status"] == "confirmed"
    assert len(body["history"]) == 1
    assert body["history"][0]["review_status"] == "uncertain"
    assert body["history"][0]["notes"] == "not sure yet"


# ---------------------------------------------------------------------------
# 9-11: dataset review summary + ownership + cross-user denial
# ---------------------------------------------------------------------------

def test_dataset_review_summary():
    c1 = _seed_candidate(candidate_id="c1")
    client.post(f"/api/reviews/{DATASET}/candidate/{c1}", json={"review_status": "confirmed"})
    r = client.get(f"/api/reviews/{DATASET}/summary")
    assert r.status_code == 200
    summary = r.json()["summary"]
    assert summary["total_reviews"] == 1
    assert summary["by_status"]["confirmed"] == 1
    assert summary["by_status"]["unreviewed"] == 0


@pytest.mark.real_auth
def test_owner_can_annotate_and_foreign_user_cannot():
    from database.models import Dataset, gen_uuid
    from database.session import Base, get_db
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    from configs import settings as settings_mod
    settings_mod.settings.data_root = tmp
    (tmp / "raw").mkdir(exist_ok=True)
    (tmp / "processed").mkdir(exist_ok=True)

    engine = create_engine(f"sqlite:///{tmp / 'auth.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db

    owner = TestClient(app)
    stranger = TestClient(app)
    owner.post("/api/auth/register", json={"email": "owner@example.test", "password": "correct-horse-battery"})
    stranger.post("/api/auth/register", json={"email": "stranger@example.test", "password": "correct-horse-battery"})

    from database.models import User
    with Session() as s:
        owner_id = s.query(User).filter(User.email == "owner@example.test").one().id
        ds_id = gen_uuid()
        s.add(Dataset(id=ds_id, name="owner's survey", sensor_type="gpr",
                      original_format="sgy", owner_id=owner_id))
        s.commit()

    candidate_id = _seed_candidate(dataset_id=ds_id)

    # owner can annotate
    r_owner = owner.post(f"/api/reviews/{ds_id}/candidate/{candidate_id}",
                         json={"review_status": "confirmed"})
    assert r_owner.status_code == 200

    # foreign user cannot annotate a private dataset
    r_stranger = stranger.post(f"/api/reviews/{ds_id}/candidate/{candidate_id}",
                               json={"review_status": "rejected"})
    assert r_stranger.status_code == 404

    # foreign user cannot even read the review
    r_read = stranger.get(f"/api/reviews/{ds_id}")
    assert r_read.status_code == 404

    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 12-15: missed-event annotation, geometry validation, ridge serialization
# ---------------------------------------------------------------------------

def test_missed_event_annotation():
    r = client.post(f"/api/reviews/{DATASET}/missed_event",
                    json={"source_file": "Path8.sgy", "trace_range": [50, 55],
                          "review_status": "confirmed", "notes": "visible hyperbola, no candidate flagged it"})
    assert r.status_code == 200
    body = r.json()
    assert body["candidate_id"] is None
    assert body["review_status"] == "confirmed"


def test_missed_event_inverted_trace_range_rejected():
    r = client.post(f"/api/reviews/{DATASET}/missed_event",
                    json={"source_file": "Path8.sgy", "trace_range": [55, 50], "review_status": "confirmed"})
    assert r.status_code == 422


def test_rectangle_geometry_validation():
    with pytest.raises(Exception):
        AnnotationGeometry(kind=AnnotationGeometryKind.RECTANGLE,
                           trace_start=10, trace_end=5, sample_start=0, sample_end=10)


def test_ridge_path_geometry_validation_mismatched_lengths():
    with pytest.raises(Exception):
        AnnotationGeometry(kind=AnnotationGeometryKind.RIDGE_PATH,
                           trace_indices=[1, 2, 3], sample_indices=[1, 2])


def test_ridge_path_serialization_round_trip():
    candidate_id = _seed_candidate()
    geometry = {"kind": "ridge_path", "trace_indices": [0, 1, 2], "sample_indices": [10, 11, 12]}
    r = client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}",
                    json={"review_status": "confirmed", "annotation_geometry": geometry})
    assert r.status_code == 200
    saved = client.get(f"/api/reviews/{DATASET}/candidate/{candidate_id}").json()
    assert saved["annotation_geometry"]["trace_indices"] == [0, 1, 2]
    assert saved["annotation_geometry"]["sample_indices"] == [10, 11, 12]


# ---------------------------------------------------------------------------
# 16-18: evidence grade / ground-truth-status guarantees
# ---------------------------------------------------------------------------

def test_evidence_grade_remains_c_regardless_of_status():
    for status in ("confirmed", "rejected", "uncertain"):
        candidate_id = _seed_candidate(candidate_id=f"c-{status}")
        r = client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}", json={"review_status": status})
        assert r.json()["evidence_grade"] == "operator_reviewed"


def test_operator_confirmed_does_not_become_externally_validated():
    candidate_id = _seed_candidate()
    r = client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}",
                    json={"review_status": "confirmed", "operator_label": "pipe"})
    assert r.json()["ground_truth_status"] == "not_independently_validated"


def test_rejected_candidate_does_not_become_verified_empty_ground_truth():
    from training.review_corpus import review_to_training_example

    candidate_id = _seed_candidate()
    client.post(f"/api/reviews/{DATASET}/candidate/{candidate_id}", json={"review_status": "rejected"})
    review = load_reviews(DATASET).for_candidate(candidate_id)
    example = review_to_training_example(
        review, signal=[[0.0] * 5 for _ in range(5)],
        window_trace_range=(0, 4), window_sample_range=(0, 4),
        preprocessing_version="test-v1",
    )
    assert example.evidence_grade == EvidenceGrade.C_OPERATOR_REVIEWED
    assert example.evidence_grade != EvidenceGrade.A_INDEPENDENTLY_VERIFIED
    assert example.mask.n_cells == 0  # empty, but real evidence about the detector -- not fabricated ground truth


# ---------------------------------------------------------------------------
# 19-20: corpus conversion + export serialization
# ---------------------------------------------------------------------------

def test_corpus_conversion_ridge_path():
    from training.review_corpus import geometry_to_mask_region

    review = CandidateReview(
        dataset_id=DATASET, source_file="f.sgy", trace_range=(100, 110),
        reviewer_id="u", review_status=ReviewStatus.CONFIRMED,
        annotation_geometry=AnnotationGeometry(
            kind=AnnotationGeometryKind.RIDGE_PATH,
            trace_indices=[100, 101, 102], sample_indices=[20, 21, 22]),
    )
    mask = geometry_to_mask_region(review.annotation_geometry, window_trace_start=100, window_sample_start=0)
    assert mask.trace_indices == [0, 1, 2]
    assert mask.sample_indices == [20, 21, 22]
    assert "no invented width" in mask.rule


def test_corpus_conversion_rectangle():
    from training.review_corpus import geometry_to_mask_region

    geometry = AnnotationGeometry(kind=AnnotationGeometryKind.RECTANGLE,
                                  trace_start=5, trace_end=6, sample_start=10, sample_end=11)
    mask = geometry_to_mask_region(geometry, window_trace_start=5, window_sample_start=10)
    assert mask.n_cells == 4  # 2x2 box
    assert set(zip(mask.trace_indices, mask.sample_indices)) == {(0, 0), (0, 1), (1, 0), (1, 1)}


def test_export_serialization_excludes_unreviewed():
    from training.review_corpus import review_to_training_example

    review = CandidateReview(
        dataset_id=DATASET, source_file="f.sgy", trace_range=(0, 4),
        reviewer_id="u", review_status=ReviewStatus.UNREVIEWED,
    )
    example = review_to_training_example(
        review, signal=[[0.0] * 5 for _ in range(5)],
        window_trace_range=(0, 4), window_sample_range=(0, 4),
        preprocessing_version="test-v1",
    )
    assert example is None


def _make_gpr_records(dataset_id, source_file, n_traces=20, n_samples=20, seed=0):
    """
    Real-shaped multi-sample GPR records, run through the ACTUAL production
    anomaly-preprocessing step -- mirrors SEGYConverter's own output shape
    AND `find_anomaly_candidates`' own pipeline (see
    test_anomaly_candidate_integration.py). Without this, `pre_anomaly_signal`
    is never populated in metadata and corpus export's real grid fetch (field=
    "pre_anomaly_signal") divides by nothing and returns NaN -- a real bug this
    fixture exists specifically to keep caught (see the milestone's own final
    report for the live-browser 500 this originally surfaced from).
    """
    from preprocessing.spatial_grid import preprocess_trace_local_anomaly
    from schemas.subterra_record import SensorType, SubterraRecord

    rng = np.random.default_rng(seed)
    records = []
    for t in range(n_traces):
        for s in range(n_samples):
            records.append(SubterraRecord(
                dataset_id=dataset_id, sensor_type=SensorType.GPR,
                latitude=0.0, longitude=0.0, depth=float(s),
                signal=[float(rng.normal())],
                metadata={"source_file": source_file, "trace_index": t, "sample_index": s},
            ))
    return preprocess_trace_local_anomaly(records)


def test_corpus_export_end_to_end_against_a_real_live_dataset():
    """
    The full route, not just the pure converter: real records saved through
    the real store, a real review against them, exported through the real
    `GET .../corpus_export` endpoint. This is the exact path a live click
    on the frontend's export link exercises.
    """
    from database.records_store import save_records

    dataset_id = "review-corpus-export-live-test"
    # make_candidate's own defaults: source_file="Line1.sgy", trace_range=(10, 14).
    save_records(dataset_id, _make_gpr_records(dataset_id, "Line1.sgy", n_traces=20))
    candidate_id = _seed_candidate(dataset_id=dataset_id)
    client.post(f"/api/reviews/{dataset_id}/candidate/{candidate_id}",
               json={"review_status": "confirmed", "operator_label": "pipe"})

    r = client.get(f"/api/reviews/{dataset_id}/corpus_export")
    assert r.status_code == 200
    body = r.json()
    assert body["n_eligible_reviews"] == 1
    assert body["errors"] == []
    assert body["n_examples_exported"] == 1
    assert body["manifest"]["n_examples"] == 1
    delete_reviews(dataset_id)


def test_export_serialization_confirmed_with_no_geometry_is_existence_only():
    """Section 4's critical valid state, carried into the corpus format: confirmed real, no marked extent."""
    from training.review_corpus import review_to_training_example
    from schemas.segmentation import LabelLevel

    review = CandidateReview(
        dataset_id=DATASET, source_file="f.sgy", trace_range=(0, 4),
        reviewer_id="u", review_status=ReviewStatus.CONFIRMED,
    )
    example = review_to_training_example(
        review, signal=[[0.0] * 5 for _ in range(5)],
        window_trace_range=(0, 4), window_sample_range=(0, 4),
        preprocessing_version="test-v1",
    )
    assert example is not None
    assert example.mask is None
    assert example.label_level == LabelLevel.D_EXISTENCE
