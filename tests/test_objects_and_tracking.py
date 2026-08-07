"""
SubsurfaceObjects, association records, and tracking.

The risk here is an association quietly becoming an identity, and an object
quietly becoming a thing. So the tests are mostly refusals and earnings:

  - an object's status must be EARNED: `corroborated` needs two independent
    acquisitions, `attested` needs a ground-truth label;
  - an object's position is DERIVED from members, never invented, and stays
    `NoPosition` when the members cannot be placed;
  - an association must carry the criteria that were applied and the
    measurements they were applied to;
  - `score` is the fraction of criteria satisfied, never a probability;
  - cross-survey tracking reports that it is UNVALIDATED, because no held
    dataset has repeat coverage.

Adjacent-trace and adjacent-profile association are exercised against real
4TU candidates where the data supports it.
"""
import glob
import os
from pathlib import Path

import pytest

from schemas.associations import (
    AssociationCriteria, AssociationEvidence, AssociationMethod, AssociationRecord,
    AssociationSet,
)
from schemas.objects import (
    ObjectStatus, ObservationKind, ObservationRef, SubsurfaceObject, build_object,
    derive_position,
)
from schemas.provenance import ProvenanceClass
from schemas.spatial import GeographicPosition, NoPosition, OdometryPosition

GPR_ACT = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted/01/01/01.4")
REAL = pytest.mark.skipif(not GPR_ACT.exists(), reason="4TU activity 01.4 not present")


def _obs(oid, frame="ds:l1", lat=None, lon=None, trace=10):
    pos = (GeographicPosition(lat=lat, lon=lon) if lat is not None
           else NoPosition(reason="no geographic position"))
    return ObservationRef(kind=ObservationKind.CANDIDATE, dataset_id="ds",
                          observation_id=oid, frame_id=frame, trace_index=trace,
                          position=pos)


def _criteria(**kw):
    kw.setdefault("supplied_by", "test")
    kw.setdefault("max_trace_gap", 3)
    return AssociationCriteria(**kw)


def _assoc(a="c1", b="c2", method=AssociationMethod.ADJACENT_TRACE,
           frame_a="ds:l1", frame_b="ds:l1", score=1.0, evidence=None, **kw):
    return AssociationRecord(
        dataset_id="ds", method=method,
        observation_a=_obs(a, frame_a), observation_b=_obs(b, frame_b),
        criteria=_criteria(**kw),
        evidence=evidence or AssociationEvidence(trace_gap=1, depth_overlap_m=0.05),
        criteria_satisfied=["max_trace_gap"], score=score)


# --- an object's status must be earned ---

def test_a_single_acquisition_object_is_only_hypothesised():
    o = build_object("ds", [_obs("c1", "ds:l1", 52.0, 6.0),
                            _obs("c2", "ds:l1", 52.0, 6.0)])
    assert o.status == ObjectStatus.HYPOTHESISED
    assert o.acquisition_count == 1


def test_two_independent_acquisitions_earn_corroborated():
    o = build_object("ds", [_obs("c1", "ds:l1", 52.0, 6.0),
                            _obs("c2", "ds:l2", 52.0, 6.0)])
    assert o.status == ObjectStatus.CORROBORATED
    assert o.acquisition_count == 2


def test_corroborated_cannot_be_claimed_from_one_acquisition():
    """Repeated observations on one line are not independent evidence."""
    with pytest.raises(ValueError) as e:
        SubsurfaceObject(dataset_id="ds", status=ObjectStatus.CORROBORATED,
                         members=[_obs("c1", "ds:l1"), _obs("c2", "ds:l1")])
    assert "not independent evidence" in str(e.value)


def test_attested_requires_a_ground_truth_label():
    with pytest.raises(ValueError) as e:
        SubsurfaceObject(dataset_id="ds", status=ObjectStatus.ATTESTED,
                         members=[_obs("c1")])
    assert "A detector cannot attest to its own findings" in str(e.value)


def test_an_attested_object_names_what_attested_it():
    o = build_object("ds", [_obs("c1", "ds:l1", 52.0, 6.0)],
                     attested_by=["lbl_trench7"])
    assert o.status == ObjectStatus.ATTESTED
    assert o.attested_by == ["lbl_trench7"]


def test_an_objects_position_can_never_be_measured():
    with pytest.raises(ValueError) as e:
        SubsurfaceObject(dataset_id="ds", members=[_obs("c1")],
                         position_provenance=ProvenanceClass.MEASURED)
    assert "the object itself measured nothing" in str(e.value)


# --- position is derived, or absent ---

def test_a_position_is_the_centroid_of_geographic_members():
    pos, basis = derive_position([_obs("a", lat=52.0, lon=6.0),
                                  _obs("b", lat=52.2, lon=6.4)])
    assert pos.kind == "geographic"
    assert pos.lat == pytest.approx(52.1) and pos.lon == pytest.approx(6.2)
    assert "centroid of 2 geographic member" in basis


def test_members_with_no_geographic_position_yield_no_position():
    """An object is never given a coordinate so that it can be drawn."""
    members = [ObservationRef(kind=ObservationKind.CANDIDATE, dataset_id="ds",
                              observation_id="c1", frame_id="ds:l1",
                              position=OdometryPosition(along_track_m=3.0, path_id="l"))]
    o = build_object("ds", members)
    assert o.is_placed is False
    assert "cannot be placed on Earth" in o.position.reason
    assert "odometry" in o.position.reason


def test_only_geographic_members_contribute_to_the_centroid():
    """Averaging metres with degrees would be meaningless."""
    pos, basis = derive_position([
        _obs("a", lat=52.0, lon=6.0),
        ObservationRef(kind=ObservationKind.CANDIDATE, dataset_id="ds",
                       observation_id="b", position=OdometryPosition(
                           along_track_m=99.0, path_id="l")),
    ])
    assert pos.lat == pytest.approx(52.0)
    assert "1 geographic member observation(s) out of 2" in basis


def test_object_identity_is_stable_across_reruns():
    a = build_object("ds", [_obs("c1", "ds:l1", 52.0, 6.0), _obs("c2", "ds:l2", 52.0, 6.0)])
    b = build_object("ds", [_obs("c2", "ds:l2", 52.0, 6.0), _obs("c1", "ds:l1", 52.0, 6.0)])
    assert a.id == b.id           # member order must not create a new object


# --- associations are evidence-backed hypotheses ---

def test_criteria_with_no_threshold_applied_is_refused():
    with pytest.raises(ValueError) as e:
        AssociationCriteria(supplied_by="me")
    assert "an assertion, not a hypothesis" in str(e.value)


def test_an_observation_cannot_be_associated_with_itself():
    with pytest.raises(ValueError) as e:
        _assoc(a="c1", b="c1")
    assert "cannot be associated with itself" in str(e.value)


@pytest.mark.parametrize("bad", [ProvenanceClass.MEASURED,
                                 ProvenanceClass.DECLARED_BY_SOURCE])
def test_an_association_is_never_measured_or_declared(bad):
    with pytest.raises(ValueError) as e:
        _assoc(provenance=bad) if False else AssociationRecord(
            dataset_id="ds", method=AssociationMethod.ADJACENT_TRACE,
            observation_a=_obs("c1"), observation_b=_obs("c2"),
            criteria=_criteria(), evidence=AssociationEvidence(trace_gap=1),
            score=1.0, provenance=bad)
    assert "no instrument observes that two observations are one object" in str(e.value)


def test_an_adjacent_profile_association_requires_a_measured_distance():
    with pytest.raises(ValueError) as e:
        AssociationRecord(
            dataset_id="ds", method=AssociationMethod.ADJACENT_PROFILE,
            observation_a=_obs("c1", "ds:l1"), observation_b=_obs("c2", "ds:l2"),
            criteria=_criteria(max_distance_m=5.0), evidence=AssociationEvidence(),
            score=1.0)
    assert "they cannot be associated by this method" in str(e.value)


def test_association_identity_is_order_independent():
    a = _assoc("c1", "c2")
    b = _assoc("c2", "c1")
    assert a.id == b.id


def test_same_acquisition_is_distinguished_from_independent():
    assert _assoc(frame_a="ds:l1", frame_b="ds:l1").is_independent_evidence is False
    assert _assoc(frame_a="ds:l1", frame_b="ds:l2").is_independent_evidence is True


def test_the_score_declares_it_is_not_a_probability():
    assert "NOT a probability" in _assoc().score_basis


# --- grouping ---

def test_connected_components_are_transitive_and_permissive():
    s = AssociationSet(dataset_id="ds", associations=[
        _assoc("a", "b"), _assoc("b", "c")])
    groups = [g for g in s.connected_components() if len(g) > 1]
    assert groups == [["a", "b", "c"]]


def test_raising_the_score_threshold_splits_a_group():
    s = AssociationSet(dataset_id="ds", associations=[
        _assoc("a", "b", score=1.0), _assoc("b", "c", score=0.5)])
    assert [g for g in s.connected_components(min_score=0.9) if len(g) > 1] == [["a", "b"]]


# --- tracking on real data ---

@pytest.fixture(scope="module")
def real_candidates():
    from converters.segy_converter import SEGYConverter
    from interpretation.anomaly_candidates import find_anomaly_candidates
    from preprocessing.spatial_grid import preprocess_trace_local_anomaly
    from preprocessing.trace_processing import process_gpr_traces
    from schemas.subterra_record import SensorType
    out, frames = [], []
    for f in sorted(glob.glob(str(GPR_ACT / "**/*.sgy"), recursive=True),
                    key=os.path.getsize)[:4]:
        r = SEGYConverter().load(Path(f), dataset_id="trk", sensor_type=SensorType.GPR,
                                 coordinate_encoding="ieee_nmea",
                                 velocity_m_per_ns=0.0999)
        recs = preprocess_trace_local_anomaly(process_gpr_traces(r.records))
        out += find_anomaly_candidates(recs, source_file=Path(f).name)
        frames += r.frames
    return out, frames


@REAL
def test_real_candidates_become_observations_carrying_their_own_centroid(real_candidates):
    from interpretation.tracking import observation_from_candidate
    cands, _ = real_candidates
    assert cands, "expected candidates from activity 01.4"
    refs = [observation_from_candidate(c, "trk") for c in cands]
    assert all(r.position.kind == "geographic" for r in refs)
    assert all(51.0 < r.position.lat < 54.0 for r in refs)


@REAL
def test_adjacent_trace_association_fires_on_real_data_when_criteria_allow(real_candidates):
    """
    The mechanism is exercised on real candidates. With a strict trace gap AND
    required depth overlap it yields nothing on this activity -- these
    candidates are near-point components (~0.01 m tall) at distinct depths, so
    none overlap. That is a property of the detector output, not a failure, and
    the trace-gap path is verified separately by relaxing the criterion.
    """
    from interpretation.tracking import associate_adjacent_traces
    cands, _ = real_candidates
    strict = associate_adjacent_traces(cands, "trk", max_trace_gap=3,
                                       require_depth_overlap=True, supplied_by="test")
    assert strict == []
    relaxed = associate_adjacent_traces(cands, "trk", max_trace_gap=200,
                                        require_depth_overlap=False, supplied_by="test")
    assert relaxed, "the trace-gap mechanism should fire when depth overlap is not required"
    assert all(a.same_acquisition for a in relaxed)
    assert all(a.criteria.max_trace_gap == 200 for a in relaxed)


@REAL
def test_adjacent_profile_association_works_and_reports_coverage(real_candidates):
    from interpretation.tracking import associate_adjacent_profiles
    cands, _ = real_candidates
    recs, coverage = associate_adjacent_profiles(cands, "trk", max_distance_m=5.0,
                                                 supplied_by="test")
    assert coverage["candidates_unplaceable"] == 0
    assert recs, "expected cross-acquisition associations within 5 m"
    assert all(a.is_independent_evidence for a in recs)
    assert all(a.evidence.distance_m <= 5.0 for a in recs)
    assert all(a.evidence.distance_basis.startswith("haversine") for a in recs)


@REAL
def test_real_associations_resolve_into_corroborated_objects(real_candidates):
    from interpretation.tracking import (
        associate_adjacent_profiles, observation_from_candidate,
    )
    cands, _ = real_candidates
    recs, _ = associate_adjacent_profiles(cands, "trk", max_distance_m=5.0,
                                          supplied_by="test")
    s = AssociationSet(dataset_id="trk", associations=recs)
    by_id = {c.id: c for c in cands}
    groups = [g for g in s.connected_components(min_score=1.0) if len(g) > 1]
    assert groups
    objs = [build_object("trk", [observation_from_candidate(by_id[i], "trk") for i in g])
            for g in groups]
    assert all(o.status == ObjectStatus.CORROBORATED for o in objs)
    assert all(o.is_placed for o in objs)
    assert all(o.acquisition_count >= 2 for o in objs)


@REAL
def test_cross_survey_is_reported_as_not_ready_on_the_held_data(real_candidates):
    """No acquired dataset has repeat coverage; the code says so rather than
    returning an empty result that reads as 'no matches'."""
    from interpretation.tracking import cross_survey_readiness
    _, frames = real_candidates
    r = cross_survey_readiness(frames)
    assert r["ready"] is False
    assert r["missing"]
    assert "has NOT been validated" in r["note"]


def test_a_time_criterion_without_times_is_refused():
    from interpretation.tracking import associate_cross_survey
    with pytest.raises(ValueError) as e:
        associate_cross_survey([], [], "ds", max_distance_m=5.0,
                               max_time_separation_days=30.0,
                               time_a_iso=None, time_b_iso="2024-01-01T00:00:00",
                               supplied_by="test")
    assert "nothing here guesses when a survey happened" in str(e.value)


# --- storage ---

@pytest.fixture()
def store(tmp_path, monkeypatch):
    import database.objects_store as os_
    monkeypatch.setattr(os_, "_assoc_path",
                        lambda d: tmp_path / f"{d}.associations.json")
    monkeypatch.setattr(os_, "_object_path", lambda d: tmp_path / f"{d}.objects.json")
    return tmp_path


def test_associations_upsert_by_identity(store):
    from database.objects_store import load_associations, upsert_associations
    upsert_associations("ds", [_assoc("a", "b")])
    upsert_associations("ds", [_assoc("a", "b", score=0.5)])
    got = load_associations("ds")
    assert len(got.associations) == 1
    assert got.associations[0].score == 0.5


def test_objects_are_replaced_wholesale_not_merged(store):
    """Merging resolutions from different thresholds would produce a set no
    single threshold could have produced."""
    from database.objects_store import load_objects, replace_objects
    o1 = build_object("ds", [_obs("c1", "ds:l1", 52.0, 6.0)])
    o2 = build_object("ds", [_obs("c9", "ds:l9", 52.0, 6.0)])
    replace_objects("ds", [o1])
    replace_objects("ds", [o2])
    got = load_objects("ds")
    assert [o.id for o in got] == [o2.id]


def test_an_object_cannot_be_stored_under_another_dataset(store):
    from database.objects_store import replace_objects
    with pytest.raises(ValueError) as e:
        replace_objects("other", [build_object("ds", [_obs("c1", "ds:l1", 52.0, 6.0)])])
    assert "belongs to dataset" in str(e.value)
