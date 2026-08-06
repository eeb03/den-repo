"""
Tests for the detector validation harness, and the scientific findings it
pins.

These run on small synthetic grids so they are fast; the same functions
scale to real survey lines unchanged. Everything asserted here is an
ALGORITHM property -- a known input through a known filter. None of it is
field validation, and none of it says anything about what is in the ground.
"""
import numpy as np
import pytest

from validation.null_models import (
    assert_trace_permutation_equivalence, benjamini_hochberg, empirical_p_value,
    lateral_permutation, null_distribution, trace_permutation,
)
from validation.synthetic_targets import (
    STAGE_ORDER, amplitude_saturation_curve, anomaly_grid, make_target,
    measure_detectability, processed_stages,
)

N_TRACES, N_SAMPLES, DEPTH = 40, 160, 80


@pytest.fixture
def rng():
    return np.random.default_rng(20260806)


@pytest.fixture
def background(rng):
    return rng.normal(0.0, 1000.0, (N_TRACES, N_SAMPLES))


# --- harness mechanics ---

def test_processed_stages_returns_every_stage_in_pipeline_order(background):
    stages = processed_stages(background)
    assert list(stages) == ["raw"] + list(STAGE_ORDER[1:])
    assert all(stages[s].shape == background.shape for s in stages)


def test_anomaly_grid_is_transposed_and_finite(background):
    z = anomaly_grid(processed_stages(background)["gained"])
    assert z.shape == (N_SAMPLES, N_TRACES)   # (n_depths, n_traces)
    assert np.isfinite(z).all()               # unreliable cells become 0.0


def test_make_target_has_the_requested_lateral_width(rng):
    for width in (1, 3, 7):
        target, (lo, hi) = make_target("reflector", N_TRACES, N_SAMPLES, width, DEPTH, 1.0, rng)
        assert hi - lo == width
        occupied = np.flatnonzero(np.abs(target).max(axis=1) > 0)
        assert occupied.min() == lo and occupied.max() == hi - 1


def test_target_kinds_are_distinct(rng):
    flat, _ = make_target("reflector", N_TRACES, N_SAMPLES, 9, DEPTH, 1.0, rng)
    hyp, _ = make_target("hyperbola", N_TRACES, N_SAMPLES, 9, DEPTH, 1.0, rng)
    # A hyperbola's peak time varies across traces; a flat reflector's does not.
    assert np.ptp(np.argmax(np.abs(hyp), axis=1)) > np.ptp(np.argmax(np.abs(flat), axis=1))


def test_unknown_target_kind_is_rejected(rng):
    with pytest.raises(ValueError, match="Unknown target kind"):
        make_target("pipe", N_TRACES, N_SAMPLES, 3, DEPTH, 1.0, rng)


# --- sensitivity: the detector does find a narrow, strong target ---

def test_a_narrow_strong_target_is_detected(background, rng):
    result = measure_detectability(background, "reflector", width=1,
                                   depth_index=DEPTH, amplitude_sigma=10.0, rng=rng)
    assert result.detected_at(3.0)
    assert result.peak_abs_z > result.peak_abs_z_background_only
    assert result.cells_over_threshold[3.0] > 0


def test_attenuation_is_reported_for_every_stage(background, rng):
    result = measure_detectability(background, "reflector", width=3,
                                   depth_index=DEPTH, amplitude_sigma=5.0, rng=rng)
    assert set(result.attenuation_by_stage) == set(STAGE_ORDER)
    assert result.attenuation_by_stage["raw"] == pytest.approx(1.0)
    assert all(v > 0 for v in result.attenuation_by_stage.values())


def test_background_removal_attenuates_in_proportion_to_target_width(background, rng):
    """
    Subtracting the survey-mean trace removes W/N of a W-of-N-trace target.
    Harmless when W << N; severe for a target spanning much of a short line.
    """
    narrow = measure_detectability(background, "reflector", 1, DEPTH, 5.0, rng)
    broad = measure_detectability(background, "reflector", N_TRACES, DEPTH, 5.0, rng)
    assert narrow.attenuation_by_stage["background_removed"] > 0.95
    assert broad.attenuation_by_stage["background_removed"] < 0.5


# --- the headline finding: |z| saturates with width ---

def test_peak_z_saturates_with_amplitude_for_a_wide_target(background, rng):
    """
    A target wider than the ring's trace exclusion contaminates its own
    background estimate, so its z-score stops responding to amplitude.
    Raising the target 100x must not meaningfully raise its score.
    """
    curve = amplitude_saturation_curve(background, "reflector", width=9,
                                       depth_index=DEPTH,
                                       amplitudes=(3.0, 30.0, 300.0), rng=rng)
    scores = list(curve.values())
    assert max(scores) / min(scores) < 1.5, f"expected saturation, got {curve}"


def test_a_narrow_target_does_respond_to_amplitude(background, rng):
    """The contrast case: without self-contamination the score does grow."""
    curve = amplitude_saturation_curve(background, "reflector", width=1,
                                       depth_index=DEPTH,
                                       amplitudes=(1.0, 30.0), rng=rng)
    scores = list(curve.values())
    assert scores[-1] > scores[0] * 1.5, f"expected growth, got {curve}"


def test_wide_targets_score_lower_than_narrow_ones_at_equal_amplitude(background, rng):
    """
    Detectability DECREASES with lateral extent, which is the opposite of
    what a physical intuition would predict and is a property of the ring
    geometry, not of the data.
    """
    narrow = measure_detectability(background, "reflector", 1, DEPTH, 30.0, rng)
    wide = measure_detectability(background, "reflector", 9, DEPTH, 30.0, rng)
    assert wide.peak_abs_z < narrow.peak_abs_z


# --- null models ---

def test_trace_permutation_shortcut_is_exact(background, rng):
    """
    Permuting raw traces then processing must equal processing then permuting
    columns, or the cheap null is invalid.
    """
    assert assert_trace_permutation_equivalence(background, rng) < 1e-6


def test_trace_permutation_preserves_the_exact_multiset_of_values(background, rng):
    processed = processed_stages(background)["gained"]
    drawn = trace_permutation(processed, rng)
    assert np.array_equal(np.sort(drawn, axis=None), np.sort(processed, axis=None))
    assert drawn.shape == processed.shape


def test_lateral_permutation_preserves_each_depth_rows_marginal(background, rng):
    processed = processed_stages(background)["gained"]
    drawn = lateral_permutation(processed, rng)
    # axis 0 is traces in this orientation, so each column is one depth row.
    assert np.allclose(np.sort(drawn, axis=0), np.sort(processed, axis=0))


def test_null_distribution_returns_one_value_per_draw(background, rng):
    processed = processed_stages(background)["gained"]
    draws = null_distribution(processed, lambda z: float(np.abs(z).max()),
                              n_draws=5, rng=rng)
    assert draws.shape == (5,) and np.isfinite(draws).all()


def test_unknown_null_model_is_rejected(background, rng):
    with pytest.raises(ValueError, match="Unknown null model"):
        null_distribution(background, lambda z: 0.0, n_draws=1, rng=rng, null_model="shuffle")


def test_pure_noise_does_not_beat_its_own_null(background, rng):
    """A background with no target must not look significant against itself."""
    processed = processed_stages(background)["gained"]
    stat = lambda z: float(np.abs(z).max())  # noqa: E731
    observed = stat(anomaly_grid(processed))
    draws = null_distribution(processed, stat, n_draws=20, rng=rng)
    assert empirical_p_value(observed, draws) > 0.05


# --- multiple comparisons ---

def test_empirical_p_value_is_never_zero():
    """A finite number of draws cannot prove impossibility."""
    assert empirical_p_value(1e9, np.zeros(100)) == pytest.approx(1 / 101)


def test_empirical_p_value_is_one_when_every_draw_exceeds_observed():
    assert empirical_p_value(0.0, np.ones(9)) == pytest.approx(1.0)


def test_benjamini_hochberg_rejects_a_lone_marginal_result_among_many():
    """
    50 lines at alpha=0.05 yield ~2.5 nominal hits by chance, so p=0.03 in a
    family of 50 is not a discovery.
    """
    ps = [0.03] + [0.6] * 49
    assert benjamini_hochberg(ps, alpha=0.05) == []


def test_benjamini_hochberg_keeps_a_strong_result():
    ps = [0.0001] + [0.6] * 49
    assert benjamini_hochberg(ps, alpha=0.05) == [0]


def test_benjamini_hochberg_handles_empty_input():
    assert benjamini_hochberg([]) == []


# --- the harness must not touch the detector ---

def test_validation_package_is_not_imported_by_any_production_module():
    """
    The dependency arrow points one way: validation imports production, never
    the reverse, so an experiment cannot change a scientific result.
    """
    import pathlib
    import re

    roots = ["preprocessing", "interpretation", "converters", "api", "schemas",
             "database", "fusion", "ingestion", "training", "validators"]
    # Matches both `import validation...` and `from validation... import ...`
    pattern = re.compile(r"^\s*(?:from|import)\s+validation\b", re.MULTILINE)
    offenders = [
        str(p) for root in roots for p in pathlib.Path(root).rglob("*.py")
        if pattern.search(p.read_text())
    ]
    assert offenders == [], f"production modules must not import validation: {offenders}"
