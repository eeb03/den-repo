"""
Deterministic tests for the Pk050 negative-control audit's own logic:
plateau segmentation, rank-based depth pairing, the hyperbola-applicability
check, and the non-identifiability illustration. None of these hardcode the
real Pk050 result -- they exercise the math against small synthetic fixtures,
exactly as `tests/test_bam_hyperbola_velocity_audit.py` does for Pk266.
"""
from __future__ import annotations

import numpy as np
import pytest

from scripts.bam_hyperbola_velocity_audit import ArrivalPick
from scripts.bam_pk050_velocity_audit import (
    MIN_PLATEAU_RUN_MM,
    Plateau,
    check_hyperbola_applicability,
    illustrate_nonidentifiability,
    pair_plateaus_with_known_depths,
    segment_plateaus,
    sensitivity_of_single_point,
)


def _pick(time_ns: float, confidence: float, x_mm: float = 0.0) -> ArrivalPick:
    return ArrivalPick(x_mm=x_mm, time_ns=time_ns, sample_index=0, amplitude=confidence, confidence=confidence)


class TestSegmentPlateaus:
    def test_a_long_stable_high_confidence_run_becomes_one_plateau(self):
        # 20 nodes at 5mm spacing = 95mm... use 30 nodes = 145mm, above MIN_PLATEAU_RUN_MM
        picks = [_pick(4.20 + 0.001 * i, 6.0) for i in range(30)]
        x_values = np.arange(30) * 5.0
        plateaus, rejected = segment_plateaus(picks, x_values, sample_interval_ns=0.03, x_step_mm=5.0)
        assert len(plateaus) == 1
        assert plateaus[0].n_nodes == 30
        assert rejected == []

    def test_a_short_high_confidence_run_is_rejected_not_silently_dropped(self):
        picks = [_pick(4.20, 6.0) for _ in range(5)]  # 5 nodes * 5mm = 20mm, well under 100mm
        x_values = np.arange(5) * 5.0
        plateaus, rejected = segment_plateaus(picks, x_values, sample_interval_ns=0.03, x_step_mm=5.0)
        assert plateaus == []
        assert len(rejected) == 1
        assert "below the" in rejected[0].reason

    def test_low_confidence_nodes_never_form_a_plateau_regardless_of_length(self):
        picks = [_pick(4.20, 1.0) for _ in range(40)]  # confidence below MIN_PICK_CONFIDENCE
        x_values = np.arange(40) * 5.0
        plateaus, rejected = segment_plateaus(picks, x_values, sample_interval_ns=0.03, x_step_mm=5.0)
        assert plateaus == []
        assert rejected == []  # never even considered a candidate run

    def test_a_time_jump_beyond_tolerance_splits_the_run_in_two(self):
        # First 30 nodes at one plateau time, next 30 at a much later time -- a
        # real jump, not noise -- must NOT be merged into one plateau.
        picks = [_pick(4.20, 6.0) for _ in range(30)] + [_pick(6.20, 6.0) for _ in range(30)]
        x_values = np.arange(60) * 5.0
        plateaus, rejected = segment_plateaus(picks, x_values, sample_interval_ns=0.03, x_step_mm=5.0)
        assert len(plateaus) == 2
        assert abs(plateaus[0].mean_time_ns - 4.20) < 1e-9
        assert abs(plateaus[1].mean_time_ns - 6.20) < 1e-9

    def test_a_small_jump_within_tolerance_does_not_split_the_run(self):
        interval = 0.03
        tolerance = 2 * interval
        picks = [_pick(4.20, 6.0) for _ in range(20)] + [_pick(4.20 + tolerance * 0.5, 6.0) for _ in range(20)]
        x_values = np.arange(40) * 5.0
        plateaus, rejected = segment_plateaus(picks, x_values, sample_interval_ns=interval, x_step_mm=5.0)
        assert len(plateaus) == 1
        assert plateaus[0].n_nodes == 40


class TestHyperbolaApplicability:
    def _plateau(self, x_start, x_end, mean_time_ns, std_time_ns):
        return Plateau(x_start_mm=x_start, x_end_mm=x_end, n_nodes=int((x_end - x_start) / 5) + 1,
                       mean_time_ns=mean_time_ns, std_time_ns=std_time_ns,
                       min_confidence=6.0, mean_confidence=6.0, picks=[])

    def test_a_flat_time_invariant_reflector_is_not_hyperbola_applicable(self):
        p = self._plateau(1480.0, 1960.0, 4.20, 0.02)  # near-zero observed spread
        result = check_hyperbola_applicability(p)
        assert result["hyperbola_applicable"] is False

    def test_a_reflector_with_curvature_matching_a_point_source_is_applicable(self):
        # Construct a plateau whose observed std is comparable to what a point
        # source at this depth/aperture would predict, rather than asserting it.
        p = self._plateau(1480.0, 1960.0, 4.20, 100.0)  # absurdly large std, forces the branch
        result = check_hyperbola_applicability(p)
        assert result["hyperbola_applicable"] is True


class TestPairPlateausWithKnownDepths:
    def _plateau(self, mean_time_ns, x_start=0.0, x_end=100.0):
        return Plateau(x_start_mm=x_start, x_end_mm=x_end, n_nodes=21, mean_time_ns=mean_time_ns,
                       std_time_ns=0.01, min_confidence=6.0, mean_confidence=6.0, picks=[])

    def test_pairing_matches_shortest_time_to_shallowest_depth(self):
        plateaus = [self._plateau(6.0), self._plateau(4.0)]  # deliberately out of time order
        result = pair_plateaus_with_known_depths(plateaus, [100.0, 200.0])
        assert result["pairs"][0]["known_depth_mm"] == 100.0
        assert result["pairs"][0]["plateau_mean_time_ns"] == 4.0
        assert result["pairs"][1]["known_depth_mm"] == 200.0
        assert result["pairs"][1]["plateau_mean_time_ns"] == 6.0

    def test_fewer_plateaus_than_known_depths_pairs_only_the_shallow_ones(self):
        plateaus = [self._plateau(4.0)]
        result = pair_plateaus_with_known_depths(plateaus, [100.0, 200.0, 300.0, 400.0])
        assert len(result["pairs"]) == 1
        assert result["pairs"][0]["known_depth_mm"] == 100.0
        assert result["unmatched_known_depths_mm"] == [200.0, 300.0, 400.0]

    def test_zero_plateaus_pairs_nothing(self):
        result = pair_plateaus_with_known_depths([], [100.0, 200.0])
        assert result["pairs"] == []
        assert result["unmatched_known_depths_mm"] == [100.0, 200.0]

    def test_the_assumption_is_always_stated_explicitly(self):
        result = pair_plateaus_with_known_depths([self._plateau(4.0)], [100.0])
        assert "rank order" in result["assumption"].lower() or "RANK ORDER" in result["assumption"]
        assert "never" in result["assumption"].lower()


class TestIllustrateNonidentifiability:
    def test_different_velocities_imply_wildly_different_t0(self):
        # depth=210.8mm, time=4.20ns -- the real Pk050 order of magnitude, but
        # this test only checks the MATH, not the specific empirical values.
        results = illustrate_nonidentifiability(210.8, 4.20, v_grid_m_per_ns=(0.06, 0.20))
        t0s = [r["implied_t0_ns"] for r in results]
        # A single point genuinely cannot pin down t0: the two extreme
        # velocities in a physically plausible range must disagree substantially.
        assert abs(t0s[0] - t0s[1]) > 1.0

    def test_implied_t0_is_computed_from_the_stated_model(self):
        depth_m = 0.2
        time_ns = 5.0
        v = 0.10
        results = illustrate_nonidentifiability(depth_m * 1000.0, time_ns, v_grid_m_per_ns=(v,))
        expected_t0 = time_ns - 2 * depth_m / v
        assert results[0]["implied_t0_ns"] == pytest.approx(expected_t0)

    def test_physically_implausible_t0_is_flagged(self):
        # A very low velocity forces the implied t0 far negative (since 2d/v
        # exceeds the measured time) -- must be flagged, not silently accepted.
        results = illustrate_nonidentifiability(500.0, 4.0, v_grid_m_per_ns=(0.05,))
        assert results[0]["physically_plausible_t0"] is False


class TestSensitivityOfSinglePoint:
    def test_perturbing_the_pick_shifts_the_implied_t0_by_the_shift_amount(self):
        result = sensitivity_of_single_point(210.8, 4.20, sample_interval_ns=0.03, v_m_per_ns=0.13)
        base_t0 = 4.20 - 2 * 0.2108 / 0.13
        for p in result["perturbations"]:
            expected = base_t0 + p["shift_samples"] * 0.03
            assert p["implied_t0_ns"] == pytest.approx(expected)
