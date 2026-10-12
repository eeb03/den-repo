"""
Measure a simulated B-scan against the travel times its truth predicts.

The picker is deliberately naive and BLIND to the prediction: mean-trace
background removal, Hilbert envelope, global maximum per trace. It is never
given a search window centred on the predicted time, because a window drawn
around the answer would make agreement partly self-fulfilling.

PRE-REGISTERED TOLERANCES. Fixed here before the first solver run, from the
wavelet and sampling alone, never adjusted afterwards to pass:

* apex time        |measured - predicted| <= half the dominant period, 1/(2 f).
                   A band-limited peak cannot be located more finely than its
                   own half-cycle without modelling the pulse shape.
* apex position    |measured - predicted| <= 2 traces. HOW the measured apex
                   is located changed once; see APEX POSITION below.
* hyperbola shape  RMS time error over the 21 traces centred on the
                   predicted apex <= the same half period.

Known bias: mean-trace removal subtracts the hyperbola's own average along
with the direct wave, pulling picks slightly late (+15.7 ps at the apex of
the analytic reference fixture, ~5% of the tolerance; see tests).

BACKGROUND METHODS, and why there are two.

* "mean_trace" -- subtract the mean trace. The method pre-registered before
  the first run. On the reference scene it FAILED the apex-position check:
  the target's hyperbola spans the whole 60-trace scan, so the mean trace
  carries the hyperbola's own average, and subtracting it leaves a ghost
  (~2.37 ns) that dominates the weak flanks; the strongest pick landed on
  trace 0, not 30. That verdict stands and is kept in every artifact.
* "target_free_reference" -- subtract the same model simulated with no
  targets: the exact direct wave and nothing else, available only in
  simulation. Adopted AFTER that diagnostic (apex trace 30, apex error
  -7 ps, RMS 11 ps over all 60 traces), so on the reference scene it is
  post hoc; it is pre-registered for every scene run after it.

APEX POSITION, and why it is kinematic.

* v1 "strongest return" (argmax of picked amplitude) -- pre-registered before
  the first run. It FAILED on the first generated scene, gen_s0_00004, with
  travel times agreeing to 27 ps RMS: amplitude is lowest near the apex
  (0.86) and peaks in two symmetric lobes ~33 deg off vertical (1.00 at
  traces 23 and 71; apex 47). That is the radiation pattern of an antenna on
  a dielectric interface, which sends its energy obliquely, not a picker
  error. The premise "strongest return = apex" was physically wrong. Kept as
  a recorded diagnostic, never again a pass criterion.
* v2 "kinematic vertex" -- fit t^2 as a quadratic in midpoint position over
  the whole scan and take its vertex: the geometric definition of a
  hyperbola's apex, blind to amplitude and so to antenna pattern. Post hoc
  for gen_s0_00004 and the reference scene; pre-registered for every scene
  run after it.

A miss is a finding, not a bug to be tuned away: the likeliest physical
causes (the 2D line-source pulse, the specular phase of a PEC, the antennas
sitting on the interface) are each worth knowing about before this corpus is
used for anything.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import hilbert

# Bumped whenever a scoring rule changes; artifacts scored under an older
# version are rescored (simulation.run_gprmax.rescore), old verdicts archived.
ANALYSIS_VERSION = 2
APEX_TRACE_TOLERANCE = 2
SHAPE_HALF_WIDTH = 10  # traces either side of the predicted apex


def remove_background(bscan: np.ndarray) -> np.ndarray:
    """Subtract the mean trace. bscan is (samples, traces)."""
    return bscan - bscan.mean(axis=1, keepdims=True)


def envelope(bscan: np.ndarray) -> np.ndarray:
    return np.abs(hilbert(bscan, axis=0))


def pick_peaks(
    bscan: np.ndarray, dt: float, time_offset: float = 0.0, background: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Per-trace (time, amplitude) of the background-removed envelope maximum.

    With `background` (a target-free twin of the same shape) that is
    subtracted; without it, the mean trace is."""
    if background is None:
        cleaned = remove_background(bscan)
    else:
        if background.shape != bscan.shape:
            raise ValueError(f"background shape {background.shape} != B-scan shape {bscan.shape}")
        cleaned = bscan - background
    env = envelope(cleaned)
    idx = env.argmax(axis=0)
    times = idx * dt + time_offset
    amps = env[idx, np.arange(env.shape[1])]
    return times, amps


def kinematic_apex_x(times: np.ndarray, midpoints: np.ndarray) -> float:
    """Vertex of the least-squares quadratic t^2 = a x^2 + b x + c."""
    a, b, _ = np.polyfit(midpoints, times ** 2, 2)
    if a <= 0:
        raise ValueError("picked times do not open upward; no hyperbola to take a vertex of")
    return float(-b / (2 * a))


def assess_against_truth(
    bscan: np.ndarray, dt: float, time_offset: float, truth: dict,
    background: np.ndarray | None = None,
) -> dict:
    """Score one single-target scene. Returns a JSON-serialisable verdict."""
    if len(truth["targets"]) != 1:
        raise ValueError("assess_against_truth scores single-target scenes only")
    target = truth["targets"][0]
    predicted = np.asarray(target["predicted"]["two_way_time_s"])
    if bscan.shape[1] != predicted.size:
        raise ValueError(f"B-scan has {bscan.shape[1]} traces, truth predicts {predicted.size}")

    half_period = 1.0 / (2.0 * truth["wavelet"]["centre_frequency_hz"])
    times, amps = pick_peaks(bscan, dt, time_offset, background)

    pred_apex = int(target["predicted"]["apex_trace"])
    midpoints = (np.asarray(truth["antennas"]["tx_x_m"]) + np.asarray(truth["antennas"]["rx_x_m"])) / 2
    try:
        vertex_x = kinematic_apex_x(times, midpoints)
        meas_apex = int(np.argmin(np.abs(midpoints - vertex_x)))
        no_hyperbola = None
    except ValueError as exc:
        # The picks do not trace a hyperbola at all: the target was not
        # recovered. That is a failed verdict, never a crash.
        vertex_x, meas_apex, no_hyperbola = None, None, str(exc)
    amplitude_apex = int(np.argmax(amps))
    apex_time_error = float(times[pred_apex] - predicted[pred_apex])

    lo = max(0, pred_apex - SHAPE_HALF_WIDTH)
    hi = min(predicted.size, pred_apex + SHAPE_HALF_WIDTH + 1)
    residual = times[lo:hi] - predicted[lo:hi]
    rms = float(np.sqrt(np.mean(residual ** 2)))

    checks = {
        "apex_time": {
            "error_s": apex_time_error,
            "tolerance_s": half_period,
            "pass": abs(apex_time_error) <= half_period,
        },
        "apex_trace": {
            "method": "kinematic_vertex_v2",
            "predicted": pred_apex,
            "measured": meas_apex,
            "vertex_x_m": vertex_x,
            "error_traces": None if meas_apex is None else meas_apex - pred_apex,
            "tolerance_traces": APEX_TRACE_TOLERANCE,
            "pass": meas_apex is not None and abs(meas_apex - pred_apex) <= APEX_TRACE_TOLERANCE,
            "failure": no_hyperbola,
        },
        "hyperbola_shape": {
            "traces": [lo, hi - 1],
            "rms_error_s": rms,
            "mean_error_s": float(residual.mean()),
            "tolerance_s": half_period,
            "pass": rms <= half_period,
        },
    }
    return {
        "analysis_version": ANALYSIS_VERSION,
        "target_id": target["target_id"],
        "background_method": "mean_trace" if background is None else "target_free_reference",
        "picker": "background removal, Hilbert envelope, global max per trace; blind to prediction",
        "tolerances_preregistered": True,
        "checks": checks,
        "pass": all(c["pass"] for c in checks.values()),
        "diagnostics": {
            # v1 apex rule, physically invalid on an interface antenna; see
            # the module docstring. Recorded, never scored.
            "amplitude_apex_trace_v1": amplitude_apex,
            "amplitude_apex_v1_would_pass": abs(amplitude_apex - pred_apex) <= APEX_TRACE_TOLERANCE,
        },
        "picked_times_s": times.tolist(),
    }
