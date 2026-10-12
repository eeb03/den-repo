"""
Real-data helpers of the detector-saturation experiment (no data files read).
"""
import numpy as np

from scripts.bam_detector_saturation import PRODUCTION_DEV_FP_PER_LINE, TARGET_RECALL, freeze_threshold
from scripts.real_data_detector_saturation import count, detector_jobs, dominant_frequency


def _pt(recall, fp):
    return {"recall": recall, "false_positives_per_line": fp}


def test_bam_freeze_prefers_lowest_fp_at_target_recall():
    curve = {"2.0": _pt(0.95, 9.0), "3.0": _pt(0.85, 3.0), "4.0": _pt(0.81, 3.0), "5.0": _pt(0.5, 0.5)}
    thr, rule = freeze_threshold(curve)
    assert thr == 4.0 and str(TARGET_RECALL) in rule  # tie on FP -> the higher threshold


def test_bam_freeze_falls_back_to_production_fp_budget():
    curve = {"2.0": _pt(0.6, 9.0), "3.0": _pt(0.4, PRODUCTION_DEV_FP_PER_LINE), "4.0": _pt(0.2, 0.5)}
    thr, rule = freeze_threshold(curve)
    assert thr == 3.0 and "unreachable" in rule


def test_bam_freeze_reports_when_nothing_qualifies():
    assert freeze_threshold({"2.0": _pt(0.1, 50.0)})[0] is None


def test_count_uses_the_component_rule_and_measures_width():
    z = np.zeros((20, 10))
    z[2, 2] = z[3, 2] = z[4, 2] = 5.0            # 3 cells, 1 trace column
    z[10, 3:7] = 5.0                              # 4 cells, 4 trace columns
    z[15, 8] = 5.0                                # 1 cell: below min_cells
    assert count(z, 3.0) == (2, 1)


def test_dominant_frequency_is_the_spectral_peak():
    dt = 1e-10
    t = np.arange(512) * dt
    traces = np.tile(np.sin(2 * np.pi * 200e6 * t), (5, 1))
    assert abs(dominant_frequency(traces, dt) - 200e6) < 1 / (512 * dt)


def test_real_data_jobs_include_production_at_three():
    freeze = {"detectors": {"ring": {"config": {}, "threshold": 2.5},
                            "hyperbola_stack": {"config": {"cone_half_angle_deg": 45.0}, "threshold": 6.0},
                            "ring_widened": {"config": {}, "threshold": None},
                            "ring_production_threshold": {"config": {}, "threshold": 3.0}}}
    names = [j[0] for j in detector_jobs(freeze)]
    assert names == ["ring@3.0_production", "ring@2.5_synthetic_frozen", "hyperbola_stack@6.0_synthetic_frozen"]
