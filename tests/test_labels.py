"""
Semantic labels.

The risk this milestone carries is a label quietly becoming a fact. So the
tests are mostly about refusals:

  - ground truth without an attestation is rejected;
  - nothing but ground truth may carry an attestation;
  - a confidence without a stated basis is rejected;
  - a label can never be `measured`;
  - a machine labeller must declare its version;
  - disagreement between labellers is preserved, never resolved.

Storage is asserted to UPSERT by identity, so re-running a detector updates
its own labels instead of accumulating near-duplicates -- while a second
labeller's disagreement survives.
"""
import pytest

from schemas.labels import (
    LabelKind, LabelSet, LabelSource, LabelTarget, LabelTargetKind, SemanticLabel,
    make_label_id,
)
from schemas.provenance import ProvenanceClass
from schemas.spatial import GeographicPosition, NoPosition


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """
    Isolates label storage. settings.processed_dir is a read-only property, so
    the seam is the store's own path function -- which is also the seam a real
    backend swap would use.
    """
    import database.labels_store as ls
    monkeypatch.setattr(ls, "_path_for",
                        lambda dataset_id: tmp_path / f"{dataset_id}.labels.json")
    return tmp_path


def _target(target_id="cand1", kind=LabelTargetKind.CANDIDATE, **kw):
    return LabelTarget(kind=kind, dataset_id="ds", target_id=target_id, **kw)


def _source(kind="human", name="analyst-a", version=None):
    return LabelSource(kind=kind, name=name, version=version)


def _label(**kw):
    base = dict(kind=LabelKind.HUMAN_INTERPRETATION, target=_target(),
                source=_source(), value="pipe-like hyperbola",
                processing_stage="interpretation")
    base.update(kw)
    return SemanticLabel(**base)


# --- what a label may not become ---

def test_ground_truth_without_an_attestation_is_refused():
    with pytest.raises(ValueError) as e:
        _label(kind=LabelKind.GROUND_TRUTH, source=_source(kind="survey", name="trench-7"))
    assert "attestation" in str(e.value)
    assert "human_interpretation or model_prediction" in str(e.value)


def test_ground_truth_with_an_attestation_is_accepted():
    l = _label(kind=LabelKind.GROUND_TRUTH,
               source=_source(kind="survey", name="trench-7"),
               attestation="trial trench 7, excavated 2021-03-04, sewer at 1.2 m")
    assert l.is_ground_truth is True


def test_only_ground_truth_may_carry_an_attestation():
    """Stops an opinion being dressed up as an excavation record."""
    with pytest.raises(ValueError) as e:
        _label(attestation="I am fairly sure")
    assert "only a ground_truth label may carry an attestation" in str(e.value)


def test_a_label_can_never_be_measured():
    with pytest.raises(ValueError) as e:
        _label(provenance=ProvenanceClass.MEASURED)
    assert "naming a thing is not measuring it" in str(e.value)


@pytest.mark.parametrize("provenance", [
    ProvenanceClass.DERIVED, ProvenanceClass.SUPPLIED_BY_CALLER,
    ProvenanceClass.DECLARED_BY_SOURCE, ProvenanceClass.INFERRED,
    ProvenanceClass.ASSUMED,
])
def test_every_other_provenance_class_is_allowed(provenance):
    assert _label(provenance=provenance).provenance == provenance


# --- confidence must mean something ---

def test_a_confidence_without_a_basis_is_refused():
    with pytest.raises(ValueError) as e:
        _label(confidence=0.8)
    assert "confidence_basis" in str(e.value)
    assert "not comparable" in str(e.value)


def test_a_confidence_with_a_basis_is_accepted():
    l = _label(confidence=0.8, confidence_basis="analyst 5-point scale, normalised")
    assert l.confidence == 0.8


@pytest.mark.parametrize("bad", [-0.1, 1.5, 42.0])
def test_a_confidence_outside_zero_to_one_is_refused(bad):
    with pytest.raises(ValueError) as e:
        _label(confidence=bad, confidence_basis="x")
    assert "outside [0, 1]" in str(e.value)


def test_no_confidence_at_all_is_legitimate():
    """A detector that reports no comparable score should say nothing."""
    assert _label().confidence is None


# --- the labeller must be identifiable ---

@pytest.mark.parametrize("kind", ["detector", "model"])
def test_a_machine_labeller_must_declare_a_version(kind):
    with pytest.raises(ValueError) as e:
        LabelSource(kind=kind, name="thing")
    assert "not reproducible" in str(e.value)


def test_a_human_labeller_needs_no_version():
    assert LabelSource(kind="human", name="analyst-a").version is None


# --- targets ---

def test_a_trace_range_target_must_name_its_frame():
    """A trace index means nothing without the acquisition it belongs to."""
    with pytest.raises(ValueError) as e:
        LabelTarget(kind=LabelTargetKind.TRACE_RANGE, dataset_id="ds",
                    target_id="t", trace_range=(1, 5))
    assert "only meaningful within one acquisition" in str(e.value)


def test_an_inverted_trace_range_is_refused():
    with pytest.raises(ValueError) as e:
        LabelTarget(kind=LabelTargetKind.TRACE_RANGE, dataset_id="ds", target_id="t",
                    frame_id="ds:line", trace_range=(9, 2))
    assert "inverted" in str(e.value)


def test_a_label_defaults_to_no_position_with_a_reason():
    """A label on a whole line has no single coordinate, and says so."""
    l = _label()
    assert l.position.kind == "none"
    assert "not to a single coordinate" in l.position.reason


def test_a_label_may_carry_a_real_position_via_the_existing_union():
    l = _label(position=GeographicPosition(lat=52.0, lon=6.0))
    assert l.position.kind == "geographic"


# --- identity and upsert ---

def test_the_same_labeller_asserting_the_same_value_is_the_same_label():
    a = _label()
    b = _label()
    assert a.id == b.id


def test_a_different_value_or_labeller_is_a_different_label():
    base = _label()
    assert _label(value="void").id != base.id
    assert _label(source=_source(name="analyst-b")).id != base.id


def test_upsert_replaces_by_identity_but_keeps_disagreement(store):
    from database.labels_store import load_labels, upsert_labels

    upsert_labels("ds", [_label(value="pipe-like hyperbola")])
    upsert_labels("ds", [_label(value="pipe-like hyperbola", notes="revised")])
    got = load_labels("ds")
    assert len(got.labels) == 1                       # replaced, not duplicated
    assert got.labels[0].notes == "revised"

    upsert_labels("ds", [_label(source=_source(name="analyst-b"), value="void")])
    got = load_labels("ds")
    assert len(got.labels) == 2                       # disagreement kept


def test_a_label_cannot_be_written_to_a_dataset_it_does_not_target(store):
    from database.labels_store import upsert_labels
    with pytest.raises(ValueError) as e:
        upsert_labels("other", [_label()])
    assert "belongs to the dataset it labels" in str(e.value)


def test_deleting_reports_ids_that_were_not_there(store):
    from database.labels_store import delete_labels, upsert_labels
    l = _label()
    upsert_labels("ds", [l])
    remaining, missing = delete_labels("ds", [l.id, "lbl_nope"])
    assert remaining.labels == []
    assert missing == ["lbl_nope"]


# --- disagreement is reported, not resolved ---

def test_disagreements_lists_targets_with_more_than_one_value():
    ls = LabelSet(dataset_id="ds", labels=[
        _label(value="pipe"),
        _label(source=_source(name="analyst-b"), value="void"),
        _label(target=_target("cand2"), value="pipe"),
    ])
    d = ls.disagreements()
    assert set(d) == {"cand1"}
    assert {l.value for l in d["cand1"]} == {"pipe", "void"}


def test_two_labellers_agreeing_is_not_a_disagreement():
    ls = LabelSet(dataset_id="ds", labels=[
        _label(value="pipe"),
        _label(source=_source(name="analyst-b"), value="pipe"),
    ])
    assert ls.disagreements() == {}


# --- the API ---

@pytest.fixture()
def client(store):
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def test_the_vocabulary_states_which_kinds_are_truth(client):
    body = client.get("/api/labels/vocabulary").json()
    truth = {k["value"] for k in body["kinds"] if k["is_truth"]}
    assert truth == {"ground_truth"}
    assert any("never a property of the ground" in r for r in body["rules"])


def test_writing_and_listing_labels_round_trips(client):
    l = _label()
    r = client.post("/api/labels/ds", json={"labels": [l.model_dump(mode="json")]})
    assert r.status_code == 200 and r.json()["total_after_write"] == 1
    got = client.get("/api/labels/ds").json()
    assert got["summary"]["count"] == 1
    assert got["summary"]["ground_truth_count"] == 0


def test_the_api_rejects_an_unattested_ground_truth_label(client):
    bad = _label().model_dump(mode="json")
    bad["kind"] = "ground_truth"
    r = client.post("/api/labels/ds", json={"labels": [bad]})
    assert r.status_code == 422        # refused by the model, before storage


def test_min_confidence_keeps_labels_that_state_no_confidence(client):
    """An unscored label is not a low-confidence one."""
    scored = _label(value="a", confidence=0.2, confidence_basis="s")
    unscored = _label(value="b")
    client.post("/api/labels/ds", json={
        "labels": [scored.model_dump(mode="json"), unscored.model_dump(mode="json")]})
    got = client.get("/api/labels/ds?min_confidence=0.5").json()
    values = {l["value"] for l in got["labels"]}
    assert values == {"b"}
    assert "not a low-confidence one" in got["note"]


def test_disagreements_endpoint_reports_without_resolving(client):
    client.post("/api/labels/ds", json={"labels": [
        _label(value="pipe").model_dump(mode="json"),
        _label(source=_source(name="analyst-b"), value="void").model_dump(mode="json"),
    ]})
    body = client.get("/api/labels/ds/disagreements").json()
    assert body["disagreeing_targets"] == 1
    assert body["note"] == "disagreement is preserved, not resolved"
    assert "winner" not in str(body).lower()


def test_candidates_become_detector_labels_without_gaining_semantics(client):
    from tests.test_provenance_projection import _candidate
    c = _candidate(lateral=1.0, velocity=0.1)
    r = client.post("/api/labels/ds/from_candidates?detector_version=1.0",
                    json=[c.model_dump(mode="json")])
    body = r.json()
    assert body["created"] == 1
    lab = body["labels"][0]
    assert lab["kind"] == "detector_candidate"
    assert lab["value"] == "compact"              # the detector's own class, unchanged
    assert lab["confidence"] is None              # no comparable score is invented
    assert lab["provenance"] == "derived"
    assert "not ground truth" in lab["notes"]


def test_a_detector_label_requires_the_detector_version(client):
    from tests.test_provenance_projection import _candidate
    r = client.post("/api/labels/ds/from_candidates",
                    json=[_candidate().model_dump(mode="json")])
    assert r.status_code == 422       # detector_version is required
