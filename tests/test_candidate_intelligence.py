"""
Candidate intelligence: what a candidate may claim, and what it may never.

WHY THESE TESTS EXIST. Every other protection in this stage is a docstring or a
default, and both can be edited away by somebody who does not know why they were
there. These are the ones that must fail loudly instead. The invariants below
are not stylistic: each corresponds to a specific false claim the platform would
otherwise be able to make -- that a candidate is an object, that an anomaly
magnitude is a probability, that a region has a depth when no velocity was ever
declared, that a stored set still describes a dataset it no longer matches.

THE MEASURED CONTEXT. This method is at approximately chance on both benchmarks
(see `artifacts/bam/score_*.json` and `artifacts/4tu/leakage.json`). Tests here
therefore assert that performance TRAVELS with the data, because a candidate
list served without it reads as a finding.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from interpretation.anomaly_candidates import (
    AnomalyCandidate, AnomalyCharacteristics, AnomalyConfidence, AnomalyEvidence,
    AnomalyInterpretation,
)
from interpretation.candidate_intelligence import (
    CANDIDATE_METHOD_VERSION, CLASSIFICATION_STATUS, BenchmarkContext,
    CandidateGeneration, CandidateStatus, DepthCertainty, GenerationParameters,
    LocalisationCertainty, assess_staleness, blocked, build_intelligence,
    depth_of, inspectable, input_fingerprint, localisation_of, utcnow,
)


def make_candidate(*, lat=None, lon=None, velocity=None, peak=7.5,
                   trace_range=(10, 14), lateral_source=None,
                   anomaly_class="compact", candidate_id="c1") -> AnomalyCandidate:
    """A candidate whose fields are set explicitly, so each test states its case."""
    return AnomalyCandidate(
        id=candidate_id,
        dataset_id="d",
        evidence=AnomalyEvidence(
            source_file="Line1.sgy", trace_range=trace_range, depth_range=(0.5, 0.9),
            n_supporting_cells=12, peak_value=peak, peak_trace=12, peak_depth=0.7,
            mean_value=4.1),
        characteristics=AnomalyCharacteristics(
            area_cells=12.0, continuity_across_traces=0.8, continuity_across_depth=0.6,
            approx_depth_extent_m=0.4, centroid_lat=lat, centroid_lon=lon,
            lateral_extent_source=lateral_source),
        interpretation=AnomalyInterpretation(
            anomaly_class=anomaly_class, note="neutral geometric description"),
        confidence=AnomalyConfidence(
            reliable_fraction=0.9, touches_trace_boundary=False,
            touches_depth_boundary=False, velocity_m_per_ns=velocity),
    )


def a_generation(**kwargs) -> CandidateGeneration:
    defaults = dict(generated_at=utcnow(), dataset_id="d", input_fingerprint="fp0")
    return CandidateGeneration(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# candidate is not detection
# ---------------------------------------------------------------------------

def test_object_classification_is_structurally_blocked():
    """No code path sets this to anything else. Changing it is a deliberate edit."""
    assert CLASSIFICATION_STATUS == "BLOCKED"
    assert inspectable(make_candidate()).classification_status == "BLOCKED"
    assert build_intelligence("d", []).classification_status == "BLOCKED"


def test_a_candidate_carries_no_object_class_field():
    """
    The model must not have somewhere to put "pipe".

    A field that exists will eventually be filled, so the protection has to be
    the absence of the field rather than a rule about its contents.
    """
    fields = set(AnomalyCandidate.model_fields) | set(
        inspectable(make_candidate()).model_fields)
    for forbidden in ("object_type", "object_class", "object_probability",
                      "object_confidence", "buried_depth", "physical_size",
                      "geometry_3d", "material"):
        assert forbidden not in fields


def test_classified_object_count_is_zero():
    intelligence = build_intelligence("d", [inspectable(make_candidate())])
    assert intelligence.classified_object_count == 0


def test_the_shape_class_is_the_detectors_own_neutral_geometry():
    """Never a material or an object name."""
    intelligence = build_intelligence("d", [
        inspectable(make_candidate(anomaly_class="trace-elongated"))])
    assert intelligence.shape_classes == {"trace-elongated": 1}


# ---------------------------------------------------------------------------
# the score is not a probability
# ---------------------------------------------------------------------------

def test_candidate_score_is_the_peak_magnitude_and_says_what_it_is():
    c = inspectable(make_candidate(peak=-8.25))
    assert c.candidate_score == 8.25          # magnitude: a strong negative is strong
    assert "not a probability" in c.candidate_score_meaning
    assert "not comparable between datasets" in c.candidate_score_meaning


def test_no_field_is_named_like_a_calibrated_quantity():
    fields = set(inspectable(make_candidate()).model_fields)
    assert "probability" not in fields
    assert "confidence" not in fields
    assert "likelihood" not in fields


def test_candidates_are_ranked_by_score_descending():
    low = inspectable(make_candidate(peak=3.2, candidate_id="low"))
    high = inspectable(make_candidate(peak=9.9, candidate_id="high"))
    intelligence = build_intelligence("d", [low, high])
    assert [c.candidate.id for c in intelligence.candidates] == ["high", "low"]


# ---------------------------------------------------------------------------
# localisation -- §14
# ---------------------------------------------------------------------------

def test_geographic_centroid_makes_a_candidate_spatially_registered():
    level, basis = localisation_of(make_candidate(lat=52.0, lon=4.3))
    assert level is LocalisationCertainty.SPATIALLY_REGISTERED
    assert "geographic" in basis


def test_odometry_without_coordinates_is_frame_relative():
    level, _ = localisation_of(make_candidate(lateral_source="odometry"))
    assert level is LocalisationCertainty.FRAME_RELATIVE


def test_without_any_position_a_candidate_is_trace_relative_not_unknown():
    """
    Naming the file and the traces IS a location -- somebody can open it. What
    it is not is a coordinate, and the level says which.
    """
    level, basis = localisation_of(make_candidate(trace_range=(10, 14)))
    assert level is LocalisationCertainty.TRACE_RELATIVE
    assert "10-14" in basis and "Line1.sgy" in basis


def test_no_coordinate_is_invented_for_an_unregistered_candidate():
    c = inspectable(make_candidate())
    assert c.candidate.characteristics.centroid_lat is None
    assert c.candidate.characteristics.centroid_lon is None


# ---------------------------------------------------------------------------
# depth -- §15, and Stage 12's limit
# ---------------------------------------------------------------------------

def test_without_a_velocity_there_is_no_physical_depth():
    level, basis = depth_of(make_candidate(velocity=None))
    assert level is DepthCertainty.UNAVAILABLE
    assert "not a physical depth" in basis


def test_a_velocity_makes_depth_derived_never_measured():
    level, basis = depth_of(make_candidate(velocity=0.1))
    assert level is DepthCertainty.DERIVED
    assert "assumption" in basis
    assert level is not DepthCertainty.MEASURED


def test_no_code_path_reports_measured_depth_from_a_velocity():
    """
    Stage 12 established that relating the origin to the ground does not create
    a physical depth. A velocity is an assumption about the ground, and an
    assumption's consequence cannot be a measurement.
    """
    for velocity in (None, 0.01, 0.1, 0.3):
        level, _ = depth_of(make_candidate(velocity=velocity))
        assert level is not DepthCertainty.MEASURED


# ---------------------------------------------------------------------------
# provenance, versioning and determinism -- §17, §18
# ---------------------------------------------------------------------------

def test_a_generation_records_method_version_and_parameters():
    g = a_generation()
    assert g.method_version == CANDIDATE_METHOD_VERSION
    assert g.parameters.threshold == 3.0
    assert g.deterministic is True
    assert g.seed is None


def test_the_default_parameters_reproduce_the_published_baseline():
    """
    min_trace_span=1 admits every component, which is what the baseline did.
    `artifacts/experiment/trace_span.json` measured the alternatives and none
    was promoted -- so the default must still be the baseline.
    """
    assert GenerationParameters().min_trace_span == 1


def test_identical_inputs_produce_an_identical_fingerprint():
    a = input_fingerprint("d", ["b.sgy", "a.sgy"], 100, "gpr_local_anomaly")
    b = input_fingerprint("d", ["a.sgy", "b.sgy"], 100, "gpr_local_anomaly")
    assert a == b, "source-file ORDER must not change the fingerprint"


def test_a_changed_input_changes_the_fingerprint():
    base = input_fingerprint("d", ["a.sgy"], 100, "gpr_local_anomaly")
    assert input_fingerprint("d", ["a.sgy"], 101, "gpr_local_anomaly") != base
    assert input_fingerprint("d", ["a.sgy", "b.sgy"], 100, "gpr_local_anomaly") != base
    assert input_fingerprint("d", ["a.sgy"], 100, "raw") != base


def test_parameter_changes_change_the_parameter_fingerprint():
    assert GenerationParameters().fingerprint() != \
        GenerationParameters(threshold=3.5).fingerprint()
    assert GenerationParameters().fingerprint() != \
        GenerationParameters(min_trace_span=2).fingerprint()


# ---------------------------------------------------------------------------
# staleness -- §17
# ---------------------------------------------------------------------------

def test_a_method_version_bump_makes_a_stored_set_stale():
    g = a_generation(method_version="0.9.0")
    staleness = assess_staleness(g, current_fingerprint="fp0")
    assert staleness.is_stale
    assert any("method version" in r for r in staleness.reasons)


def test_changed_records_make_a_stored_set_stale():
    staleness = assess_staleness(a_generation(), current_fingerprint="different")
    assert staleness.is_stale
    assert any("records have changed" in r for r in staleness.reasons)


def test_a_later_spatial_declaration_makes_a_stored_set_stale():
    """
    Stage 8's rule, applied to candidates: a declaration changes what the data
    MEANS, so a set computed before it describes a different world.
    """
    generated = datetime(2026, 8, 1, tzinfo=timezone.utc)
    g = a_generation(generated_at=generated, declared_reference_at=generated)
    staleness = assess_staleness(
        g, current_fingerprint="fp0", check_declarations=True,
        newest_declaration_at=generated + timedelta(days=1))
    assert staleness.is_stale
    assert any("spatial declaration" in r for r in staleness.reasons)


def test_an_earlier_declaration_does_not_make_a_set_stale():
    generated = datetime(2026, 8, 2, tzinfo=timezone.utc)
    g = a_generation(generated_at=generated, declared_reference_at=generated)
    staleness = assess_staleness(
        g, current_fingerprint="fp0", check_declarations=True,
        newest_declaration_at=generated - timedelta(days=1))
    assert not staleness.is_stale


def test_a_skipped_check_is_reported_rather_than_counted_as_passed():
    """
    "Not stale" and "not known to be stale" are different claims, and a caller
    that could not see the declarations has only established the second.
    """
    staleness = assess_staleness(a_generation())
    assert not staleness.is_stale
    assert "records" in staleness.checks_skipped
    assert "spatial declarations" in staleness.checks_skipped
    assert "method version" in staleness.checks_performed


def test_staleness_recomputes_nothing():
    """It states the fact; regenerating is a decision for a person."""
    staleness = assess_staleness(a_generation(), current_fingerprint="different")
    assert "nothing is recomputed automatically" in staleness.note


# ---------------------------------------------------------------------------
# the honest framing travels with the data -- §12, §21, §25
# ---------------------------------------------------------------------------

def test_the_benchmark_context_states_chance_performance():
    context = BenchmarkContext()
    assert "chance" in context.summary
    bam = [m for m in context.measurements if m["benchmark"] == "bam-concrete-gpr"]
    assert len(bam) == 2
    for arm in bam:
        assert arm["times_chance"] < 1.2, "a claim of skill would need evidence"


def test_the_4tu_interval_is_reported_and_spans_chance():
    fourtu = next(m for m in BenchmarkContext().measurements
                  if m["benchmark"] == "4tu-nl-utility")
    assert fourtu["contains_chance"] is True
    assert fourtu["n_negative"] == 7
    assert fourtu["ci95"][0] < 0.5 < fourtu["ci95"][1]


def test_every_intelligence_payload_carries_the_benchmark_and_the_definition():
    intelligence = build_intelligence("d", [inspectable(make_candidate())])
    assert intelligence.benchmark.measurements
    assert "not a detected object" in intelligence.definition


# ---------------------------------------------------------------------------
# blocked states, and review
# ---------------------------------------------------------------------------

def test_a_blocked_state_must_name_what_is_missing():
    """The one invariant every assessment in this platform maintains."""
    with pytest.raises(ValueError, match="must name what is missing"):
        blocked("d", "cannot generate", [])


def test_a_blocked_state_names_something_actionable():
    state = blocked("d", "no records", ["an ingested dataset with records to analyse"])
    assert state.status == "blocked"
    assert state.missing


def test_review_statuses_do_not_include_a_promotion_to_fact():
    values = {s.value for s in CandidateStatus}
    assert values == {"proposed", "reviewed", "accepted", "rejected"}
    for forbidden in ("confirmed", "detected", "validated", "verified", "true_positive"):
        assert forbidden not in values


def test_a_candidate_starts_proposed():
    assert inspectable(make_candidate()).status is CandidateStatus.PROPOSED


# ---------------------------------------------------------------------------
# burden -- §23
# ---------------------------------------------------------------------------

def test_candidate_burden_is_reported_per_traces_examined():
    intelligence = build_intelligence(
        "d", [inspectable(make_candidate(candidate_id=str(i))) for i in range(20)],
        n_traces=2000)
    assert intelligence.candidate_burden == pytest.approx(10.0)


def test_burden_is_none_rather_than_zero_when_traces_are_unknown():
    """Absence is not zero -- a burden of 0.0 would claim nothing to inspect."""
    intelligence = build_intelligence("d", [inspectable(make_candidate())])
    assert intelligence.candidate_burden is None
