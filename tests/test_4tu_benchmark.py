"""
The 4TU activity-level utility benchmark.

What is protected here is mostly the *scope* of the claims, because that is
where this benchmark can go wrong. 4TU withholds trench coordinates, so:

  * a blank count must never be read as zero;
  * an attested zero must never be read as a blank;
  * an unmatched detector response must never be called a false positive,
    because a trial trench covers only part of the surveyed ground;
  * object-level metrics must be refused rather than approximated.

The scoring maths is tested on synthetic activities so it runs without the
corpus; the parsing tests skip when `Metadata.csv` is not present locally.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from benchmark import gates
from benchmark.fourtu_scoring import (
    MIN_ACTIVITIES_FOR_A_RATE, ActivityObservation, score_activities, score_object_level,
)
from benchmark.fourtu_truth import (
    COUNT_DEFINITION, DEFAULT_METADATA, ActivityTruth, FourTuTruth,
    normalise_location_id,
)

REAL_METADATA = pytest.mark.skipif(
    not DEFAULT_METADATA.exists(), reason="4TU Metadata.csv not present locally")


def _truth(**counts) -> FourTuTruth:
    acts = {
        loc: ActivityTruth(location_id=loc, n_utilities=n, disciplines=(), materials=(),
                           diameters=(), crossing=None, path_linear=None,
                           relative_permittivity=None)
        for loc, n in counts.items()
    }
    return FourTuTruth(activities=acts, source="synthetic")


def _obs(**spec) -> dict:
    return {loc: ActivityObservation(location_id=loc, candidates=c, traces=t)
            for loc, (c, t) in spec.items()}


# ------------------------------------------------- zero is not blank

def test_an_attested_zero_is_not_the_same_as_an_unrecorded_count():
    t = _truth(a=0, b=None)
    assert t.activities["a"].attested_zero is True
    assert t.activities["a"].unrecorded is False
    assert t.activities["b"].unrecorded is True
    assert t.activities["b"].attested_zero is False


def test_a_blank_count_never_becomes_a_negative_activity():
    """A blank is missing information; treating it as empty ground would invent truth."""
    t = _truth(a=None, b=None)
    assert t.attested_zeros == []


def test_the_count_definition_is_carried_verbatim_from_the_codebook():
    assert COUNT_DEFINITION == "The number of utilities found. Integer value."
    assert _truth(a=1).count_provenance == "declared_by_source"


def test_the_trench_subset_caveat_is_attached_to_the_truth():
    assert "outside the trench" in _truth(a=1).trench_scope_caveat


def test_coordinates_are_recorded_as_unavailable():
    t = _truth(a=1)
    assert t.coordinates_available is False
    assert "confidentiality" in t.coordinates_note


def test_project_13_location_ids_are_normalised_to_match_directories():
    assert normalise_location_id("13.4") == "013.4"
    assert normalise_location_id("01.4") == "01.4"


# ------------------------------------------------- grouping and counting

def test_activities_split_into_positive_zero_and_unrecorded():
    s = score_activities(_truth(a=2, b=0, c=None),
                         _obs(a=(10, 1000), b=(5, 1000), c=(1, 1000)))
    assert (s.n_positive, s.n_attested_zero, s.n_unrecorded) == (1, 1, 1)
    assert s.n_activities_scored == 3


def test_activities_missing_from_either_side_are_excluded_and_counted():
    s = score_activities(_truth(a=1, b=1), _obs(a=(3, 100)))
    assert s.n_activities_scored == 1


def test_density_is_per_thousand_traces():
    o = ActivityObservation(location_id="a", candidates=25, traces=5000)
    assert o.per_1k_traces == 5.0


def test_zero_traces_gives_no_density_rather_than_a_division_error():
    assert ActivityObservation(location_id="a", candidates=1, traces=0).per_1k_traces is None


# ------------------------------------------------- separation and agreement

def test_perfect_separation_scores_auc_one():
    truth = _truth(**{f"p{i}": 2 for i in range(4)}, **{f"z{i}": 0 for i in range(4)})
    obs = _obs(**{f"p{i}": (100, 1000) for i in range(4)},
               **{f"z{i}": (1, 1000) for i in range(4)})
    assert score_activities(truth, obs).density_separation["auc"] == 1.0


def test_identical_groups_score_auc_one_half():
    truth = _truth(**{f"p{i}": 2 for i in range(3)}, **{f"z{i}": 0 for i in range(3)})
    obs = _obs(**{f"p{i}": (10, 1000) for i in range(3)},
               **{f"z{i}": (10, 1000) for i in range(3)})
    assert score_activities(truth, obs).density_separation["auc"] == 0.5


def test_separation_is_not_computable_without_a_zero_group():
    s = score_activities(_truth(a=1, b=2), _obs(a=(1, 100), b=(2, 100)))
    assert s.density_separation["auc"] is None
    assert "not computable" in s.density_separation["interpretation"]


def test_count_agreement_detects_a_monotonic_relationship():
    truth = _truth(a=1, b=2, c=3, d=4)
    obs = _obs(a=(10, 1000), b=(20, 1000), c=(30, 1000), d=(40, 1000))
    assert score_activities(truth, obs).count_agreement["spearman_rho"] == pytest.approx(1.0)


def test_count_agreement_detects_an_inverse_relationship():
    truth = _truth(a=1, b=2, c=3, d=4)
    obs = _obs(a=(40, 1000), b=(30, 1000), c=(20, 1000), d=(10, 1000))
    assert score_activities(truth, obs).count_agreement["spearman_rho"] == pytest.approx(-1.0)


def test_count_agreement_is_none_when_there_is_too_little_to_correlate():
    s = score_activities(_truth(a=1, b=2), _obs(a=(1, 100), b=(2, 100)))
    assert s.count_agreement["spearman_rho"] is None


# ------------------------------------------------- honesty of the rate

def test_a_small_zero_population_refuses_a_rate_but_keeps_the_counts():
    n = MIN_ACTIVITIES_FOR_A_RATE - 1
    truth = _truth(**{f"z{i}": 0 for i in range(n)}, p=3)
    obs = _obs(**{f"z{i}": (4, 1000) for i in range(n)}, p=(10, 1000))
    s = score_activities(truth, obs)
    assert s.sufficient_for_a_rate is False
    assert s.unexplained_response_rate is None
    assert s.attested_zero_group.n_candidates == 4 * n     # measurable part survives
    assert "below the" in s.limitation


def test_a_large_enough_zero_population_reports_a_rate():
    n = MIN_ACTIVITIES_FOR_A_RATE
    truth = _truth(**{f"z{i}": 0 for i in range(n)}, p=3)
    obs = _obs(**{f"z{i}": (4, 1000) for i in range(n)}, p=(10, 1000))
    s = score_activities(truth, obs)
    assert s.sufficient_for_a_rate is True
    assert s.unexplained_response_rate == 4.0


def test_the_zero_group_measure_is_not_called_a_false_alarm_rate():
    """On real ground an unmatched response may be a utility the trench missed."""
    s = score_activities(_truth(z=0), _obs(z=(1, 100)))
    assert not hasattr(s, "false_alarm_rate")
    assert "unexplained" in s.unexplained_response_basis or s.unexplained_response_basis == "not computed"


def test_the_activity_level_response_rate_is_labelled_uninformative():
    s = score_activities(_truth(a=1), _obs(a=(5, 100)))
    assert s.activity_level_response_rate == 1.0
    assert "is not evidence of skill" in s.activity_level_note


def test_no_object_or_positional_metric_is_reported():
    s = score_activities(_truth(a=1), _obs(a=(5, 100)))
    assert s.object_level_scored is False
    assert s.positional_accuracy_scored is False
    assert s.depth_accuracy_scored is False
    d = s.as_dict()
    for banned in ("iou", "precision", "recall", "f1", "detection_distance"):
        assert banned not in d


def test_every_score_carries_the_scope_and_the_trench_caveat():
    s = score_activities(_truth(a=1), _obs(a=(5, 100)))
    assert "activity-level only" in s.scope
    assert "outside the trench" in s.trench_scope_caveat


# ------------------------------------------------- the gate

def test_object_level_scoring_is_blocked():
    assert gates.OBJECT_LEVEL_STATUS == gates.BLOCKED
    assert "no trench coordinates" in gates.OBJECT_LEVEL_BLOCKED_REASON


def test_activity_level_scoring_is_not_blocked():
    assert gates.ACTIVITY_LEVEL_STATUS == gates.RESOLVED


def test_asking_for_object_level_scoring_raises_and_names_the_blocker():
    with pytest.raises(gates.ObjectLevelBlocked) as e:
        score_object_level()
    msg = str(e.value)
    assert "trench-coordinates" in msg
    assert "Activity-level scoring remains available" in msg


def test_the_trench_subset_question_is_recorded_as_open():
    q = next(q for q in gates.FOURTU_OPEN_QUESTIONS if q.id == "trench-is-a-subset-of-the-survey")
    assert q.blocks.startswith("calling an unmatched detector response a false positive")


def test_the_bam_gate_is_untouched_by_the_4tu_gate():
    """Two corpora, two different blockers; neither may leak into the other."""
    assert gates.LOCALIZATION_BLOCKED_REASON == "absolute origin is not verified"
    assert gates.OBJECT_LEVEL_BLOCKED_REASON != gates.LOCALIZATION_BLOCKED_REASON


# ------------------------------------------------- real metadata

@REAL_METADATA
def test_the_real_metadata_parses_into_125_activities():
    from benchmark.fourtu_truth import load_truth
    t = load_truth()
    assert len(t.activities) == 125


@REAL_METADATA
def test_the_real_corpus_has_attested_zero_activities():
    """These are what make any negative measurement possible at all."""
    from benchmark.fourtu_truth import load_truth
    t = load_truth()
    assert len(t.attested_zeros) == 7
    assert len(t.positives) == 112
    assert len(t.unrecorded) == 6
    assert len(t.positives) + len(t.attested_zeros) + len(t.unrecorded) == 125


@REAL_METADATA
def test_the_real_zero_population_is_too_small_for_a_rate():
    from benchmark.fourtu_truth import load_truth
    assert len(load_truth().attested_zeros) < MIN_ACTIVITIES_FOR_A_RATE


# ------------------------------------------------- the join

def test_observation_keys_are_normalised_the_same_way_as_truth_keys(tmp_path):
    """
    The two sources spell project 13 differently. Normalising only one side
    silently drops six activities, which is a wrong answer that looks like a
    right one -- it happened, and this is the guard.
    """
    import json

    from scripts.score_4tu_benchmark import load_observations

    p = tmp_path / "characterisation.json"
    p.write_text(json.dumps({"activities": {
        "13.4": {"location_id": "13.4", "candidates": 7, "traces": 1000},
        "01.4": {"location_id": "01.4", "candidates": 3, "traces": 1000},
    }}))
    obs = load_observations(p)
    assert set(obs) == {"013.4", "01.4"}


@REAL_METADATA
def test_the_real_join_covers_every_activity():
    import json
    from pathlib import Path

    from benchmark.fourtu_truth import load_truth
    from scripts.score_4tu_benchmark import load_observations

    art = Path("artifacts/4tu/characterisation.json")
    if not art.exists():
        pytest.skip("4TU characterisation artifact not present")
    truth, obs = load_truth(), load_observations(art)
    assert set(truth.activities) == set(obs)
    assert len(obs) == 125
