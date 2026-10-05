"""
Time-zero correction: resolving a `TimeZeroResult` (see `schemas.time_zero`)
and applying it to real GPR records, honestly.

THREE METHODS, EACH WITH A NARROW, STATED CONDITION FOR FIRING.

    metadata_instrument_time_zero    fires ONLY for a standard, documented
                                      acquisition field a converter already
                                      parses (SEG-Y `DelayRecordingTime`,
                                      recorded as the frame's own
                                      `time_axis_origin_offset` assumption).
                                      It explicitly REFUSES vendor fields of
                                      unestablished meaning (GSSI
                                      `rhf_position`, MALA `SIGNAL POSITION`)
                                      -- these remain `time_zero_offset_not_applied`,
                                      unchanged, exactly as before this module
                                      existed.

    operator_declared_time_zero      wraps whatever a human supplies via the
                                      `DeclarationKind.TIME_ZERO` spatial
                                      declaration (`api/spatial.py`). Never
                                      computes anything; only packages a
                                      caller-supplied number with its source.

    direct_wave_consensus_time_zero  the one ALGORITHMIC method. Picks the
                                      first sustained, high-confidence
                                      deviation from the pre-signal noise
                                      floor on EVERY trace in a line
                                      independently (never using a "known"
                                      arrival to bias the search -- the same
                                      discipline `scripts/bam_hyperbola_
                                      velocity_audit.py` and
                                      `scripts/testum_crosshole_velocity_audit.py`
                                      already use for a different quantity),
                                      then takes a ROBUST (median + MAD)
                                      consensus across traces. A single
                                      GLOBAL SHIFT, never a per-sample warp:
                                      see the module docstring section below
                                      for why DTW was considered and rejected.

WHY NOT DTW. Dynamic Time Warping aligns two signals by a nonlinear,
per-sample path, which is the right tool when the underlying physical
process itself stretches or compresses in time between the two signals
(e.g. two performances of the same speech at different paces). A time-zero
SHIFT is not that: the acquisition clock runs at one rate for every trace
in a line, so the correction relating any two traces' onsets is a single
constant offset, not a warp. Using DTW here would let it silently absorb
real amplitude/shape differences between traces (genuine subsurface
variation) into a fake per-sample time correction -- manufacturing
structure the ground never produced. Cross-correlation (which finds the
single best GLOBAL lag) is the physically appropriate tool, and it is what
`direct_wave_consensus_time_zero` uses, by finding each trace's own onset
independently rather than warping one trace onto another at all.

WHAT THIS MODULE NEVER DOES. It never overwrites the raw time axis --
`original_time_ns` is always the untouched value a converter wrote, and
`corrected_time_ns` is a NEW key, added, not substituted. It never turns a
negative corrected time into a valid depth (see `apply_time_zero_correction`).
It never upgrades a `TimeZeroResult`'s status because a caller wanted one.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Optional

from schemas.dataset_report import DECLARED_TIME_ZERO_KEY
from schemas.depth_model import two_way_time_to_depth
from schemas.subterra_record import SubterraRecord
from schemas.time_zero import TimeZeroMethod, TimeZeroResult, TimeZeroStatus

#: The one SEG-Y frame assumption this module treats as a genuine,
#: documented instrument time-zero source -- see
#: `converters/segy_converter.py`'s own `time_axis_origin_offset`
#: assumption, built from the SEG-Y standard's `DelayRecordingTime` field.
SEGY_ORIGIN_OFFSET_KEY = "time_axis_origin_offset"

#: Vendor fields this module explicitly REFUSES to treat as time-zero,
#: named here (not just by omission) so the refusal is visible and testable.
#: GSSI's `rhf_position` (recorded as `time_zero_offset_not_applied`) and
#: MALA/Grimsel's `SIGNAL POSITION` / `RAW SIGNAL POSITION` have no
#: independently established meaning -- see docs/grimsel-*.md and the
#: existing `TIME_ZERO_ASSUMPTION_KEY` docstring in `schemas/dataset_report.py`.
UNRESOLVED_VENDOR_FIELDS = ("rhf_position", "signal_position", "raw_signal_position")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Method A -- metadata/instrument-derived
# ---------------------------------------------------------------------------

def metadata_instrument_time_zero(frame) -> TimeZeroResult:
    """
    A time zero stated by the acquisition's own metadata -- and today, no
    format Subterra reads states one.

    THE SEG-Y RECORDING DELAY IS NOT A TIME ZERO. `DelayRecordingTime`
    (recorded by `converters/segy_converter.py` as the frame's
    `time_axis_origin_offset` assumption) says where the recorded window
    starts on the instrument clock, and the raw axis already includes it:
    sample 0 is AT the delay. This method used to return it as a MEASURED
    correction, making corrected time = time since recording began -- as if
    the pulse left the antenna the moment recording started -- and, being
    ranked first, overriding an operator's declaration. The delay is now
    reported in the basis and never applied. Vendor fields of unestablished
    meaning (GSSI `rhf_position`, MALA `SIGNAL POSITION`) stay refused too.

    The method remains in the hierarchy for a future format whose metadata
    genuinely documents a time zero; it never resolves until one exists.
    """
    claim = frame.assumption(SEGY_ORIGIN_OFFSET_KEY)
    if claim is None:
        return TimeZeroResult(
            status=TimeZeroStatus.UNAVAILABLE, method=TimeZeroMethod.METADATA_INSTRUMENT,
            basis="no acquisition metadata field documents a radar time zero for this frame; "
                  "this method does not reinterpret vendor fields of unestablished meaning",
        )
    return TimeZeroResult(
        status=TimeZeroStatus.UNAVAILABLE, method=TimeZeroMethod.METADATA_INSTRUMENT,
        basis=(f"the SEG-Y recording delay ({claim.value} ns, {SEGY_ORIGIN_OFFSET_KEY}) is where "
               f"the recorded window starts on the instrument clock and is already part of the "
               f"raw time axis; it is not a time zero. A time zero must be declared or picked "
               f"(first break / direct wave)."),
        source="SEG-Y DelayRecordingTime (reported, not applied)",
    )


# ---------------------------------------------------------------------------
# Method B -- operator-declared
# ---------------------------------------------------------------------------

def operator_declared_time_zero(correction_ns: float, source: str, evidence: str,
                                supplied_by: Optional[str] = None) -> TimeZeroResult:
    """
    Packages a human-supplied correction. NEVER computes or validates the
    physical correctness of the number -- only that it is finite and that
    evidence was actually given, mirroring `api/spatial.py`'s existing
    declaration validators (e.g. `_validated_depth_conversion`).
    """
    if not math.isfinite(correction_ns):
        return TimeZeroResult(
            status=TimeZeroStatus.FAILED, method=TimeZeroMethod.OPERATOR_DECLARED,
            basis=f"declared correction {correction_ns!r} is not a finite number",
        )
    basis = f"SUPPLIED BY CALLER: declared from {source}. Evidence: {evidence}"
    return TimeZeroResult(
        status=TimeZeroStatus.DECLARED, method=TimeZeroMethod.OPERATOR_DECLARED,
        correction_ns=float(correction_ns), basis=basis,
        source=f"{source} (declared by {supplied_by})" if supplied_by else source,
        applied=False, generated_utc=_now(),
    )


# ---------------------------------------------------------------------------
# Method C -- direct-wave consensus (the one algorithmic method)
# ---------------------------------------------------------------------------

#: A pick's confidence (peak deviation / local noise floor) below this is
#: not trusted at all. Matches `MIN_PICK_CONFIDENCE` in
#: `scripts/bam_hyperbola_velocity_audit.py` and
#: `scripts/testum_crosshole_velocity_audit.py` -- the same physical
#: reasoning (a real coupling/direct-wave arrival is a strong, coherent
#: event, not a marginal one), reused rather than re-tuned.
MIN_PICK_CONFIDENCE = 5.0
#: How many of a quiet window's leading samples establish the noise floor,
#: before ANY physically possible direct-wave arrival. A direct/coupling
#: wave at typical GPR antenna spacings arrives within the first handful of
#: nanoseconds; the first several samples of any trace are pre-arrival by
#: construction of the acquisition (the emitted pulse has not yet reached
#: the receiver antenna).
QUIET_SAMPLES = 8
#: A trace's own consensus is rejected as an outlier if its pick deviates
#: from the running median by more than this many Median Absolute
#: Deviations -- the same robust-outlier philosophy
#: `scripts/testum_air_warr_t0.py::analyse` already uses, not a new one.
MAX_MAD_MULTIPLE = 5.0
#: The whole dataset's consensus is only DERIVED if surviving picks agree
#: to within this spread (ns) -- looser than a single sample interval would
#: be, tight enough that "everyone roughly picked the same real event" is a
#: defensible claim rather than noise averaging to a number.
MAX_CONSENSUS_SPREAD_NS = 2.0
#: At least this fraction of evaluated traces must produce a usable pick,
#: or the result is INCONCLUSIVE rather than DERIVED from a minority.
MIN_SUCCESS_FRACTION = 0.5


#: VALIDITY CHECKS (refusal-only). They can turn a pick into "no pick" and
#: never move or create one. Each targets a failure MECHANISM documented in
#: docs/timezero-method-c-validation.md section 3, and was developed on
#: synthetic traces only (tests/test_time_zero_validity.py) -- never on the
#: operator-reference corpus, which must be re-scored once with them
#: (`scripts/validate_timezero_method_c.py`) before any accuracy is quoted.
#:
#: Mode 2, "arrival inside the quiet window": the late half of the quiet
#: window departs from the early half's mean by more than this many early-half
#: sigmas. Simulated on Gaussian noise (4-sample sigma): ~2.4% of noise-only
#: traces are flagged; a line is refused only when flagged and failed traces
#: together leave fewer than MIN_SUCCESS_FRACTION usable picks.
QUIET_WINDOW_CONTAMINATION_SIGMA = 8.0
#: Mode 3, "slow drift read as an onset": a radar arrival is TRANSIENT -- an
#: antenna cannot radiate a DC component, so within a few rise times of its
#: first lobe's peak the trace reverses or falls back to at most this
#: fraction of that peak. A monotone drift or a baseline step does neither.
TRANSIENT_FALLBACK_FRACTION = 0.5
#: ...within `TRANSIENT_RISE_MULTIPLE` x rise (+3 samples of slack) after onset.
TRANSIENT_RISE_MULTIPLE = 6
#: ...and its rise (onset -> first-lobe peak, about a quarter period) must be
#: under this fraction of the recorded window. A first lobe rising for more
#: than a tenth of the window leaves under ~2.5 periods of record, which is a
#: drift or a wow, not a direct wave. HEURISTIC; it cannot separate a slow
#: oscillating drift from a genuinely very-low-frequency antenna.
MAX_RISE_FRACTION_OF_WINDOW = 0.1

#: A leading run of at least this many EXACTLY identical samples is a
#: processing overwrite (readgssi copies sample 2 into samples 0-1; BAM,
#: docs/research/bam_quantitative_validation.md section 3), not noise, and is
#: excluded from the quiet window. Three identical floats in real noise are rare.
MIN_OVERWRITTEN_RUN = 3
#: ...and at most this long. A longer flat lead (zero padding, a noise-free
#: baseline) is genuine pre-signal and stays in the quiet window.
MAX_OVERWRITTEN_RUN = 4

#: Reasons a single trace's candidate pick is refused (counted per line).
REJECT_NO_ONSET = "no_onset_above_threshold"
#: The onset is the FIRST sample the picker may return: the signal was already
#: above threshold when the search began, so the true onset lies inside or
#: before the quiet window and the pick is the method's own floor (BAM 2.6 GHz).
REJECT_FLOOR_PINNED = "onset_at_search_floor"
REJECT_QUIET_CONTAMINATED = "quiet_window_contaminated"
REJECT_NOT_TRANSIENT = "onset_not_transient"
REJECT_SLOW_RISE = "onset_rise_too_slow"


def _quiet_window_contaminated(quiet: list[float]) -> bool:
    half = len(quiet) // 2
    early, late = quiet[:half], quiet[half:]
    if len(early) < 2 or not late:
        return False
    m = statistics.mean(early)
    sd = statistics.pstdev(early) or 1e-9
    return max(abs(x - m) for x in late) > QUIET_WINDOW_CONTAMINATION_SIGMA * sd


def _overwritten_lead(trace: list[float]) -> int:
    """Length of a leading run of exactly identical samples, if it is an overwrite."""
    k = 1
    while k < len(trace) and trace[k] == trace[0]:
        k += 1
    return k if MIN_OVERWRITTEN_RUN <= k <= MAX_OVERWRITTEN_RUN else 0


def _first_lobe_peak(trace: list[float], onset_i: int, mean: float) -> int:
    """Index of the extreme sample of the lobe that starts at `onset_i`."""
    dev = [x - mean for x in trace]
    sign = 1.0 if dev[onset_i] >= 0 else -1.0
    end = onset_i
    while end + 1 < len(trace) and sign * dev[end + 1] > 0:
        end += 1
    return max(range(onset_i, end + 1), key=lambda j: sign * dev[j])


def _onset_transient_problem(trace: list[float], onset_i: int, mean: float) -> Optional[str]:
    """None when the event starting at `onset_i` behaves like a radar arrival."""
    n = len(trace)
    dev = [x - mean for x in trace]
    sign = 1.0 if dev[onset_i] >= 0 else -1.0
    end = onset_i
    while end + 1 < n and sign * dev[end + 1] > 0:
        end += 1
    peak_i = max(range(onset_i, end + 1), key=lambda j: sign * dev[j])
    peak = sign * dev[peak_i]
    rise = max(peak_i - onset_i, 1)
    if rise > MAX_RISE_FRACTION_OF_WINDOW * n:
        return REJECT_SLOW_RISE
    limit = min(n - 1, onset_i + TRANSIENT_RISE_MULTIPLE * rise + 3)
    if any(sign * dev[j] <= TRANSIENT_FALLBACK_FRACTION * peak
           for j in range(peak_i + 1, limit + 1)):
        return None
    return REJECT_NOT_TRANSIENT


def _pick_onset_checked(trace: list[float], sample_interval_ns: float,
                        quiet_samples: int = QUIET_SAMPLES):
    """
    `(time_ns, confidence, None, peak_ns)` for a valid pick, or
    `(None, None, reason, None)`. The pick is `_pick_onset_ns`'s, with one
    data-driven difference: a leading run of identical (overwritten) samples is
    excluded from the quiet window. Otherwise the checks only refuse.
    `peak_ns` is the first lobe's extreme -- the PEAK convention for the same
    arrival, reported beside the onset, never substituted for it.
    """
    lead = _overwritten_lead(trace)
    quiet = trace[lead:lead + quiet_samples]
    if len(trace) - lead >= quiet_samples + 10 and _quiet_window_contaminated(quiet):
        return None, None, REJECT_QUIET_CONTAMINATED, None
    picked = _pick_onset_ns(trace, sample_interval_ns, quiet_samples, lead=lead)
    if picked is None:
        return None, None, REJECT_NO_ONSET, None
    onset_i = int(round(picked[0] / sample_interval_ns))
    if onset_i <= lead + quiet_samples:
        return None, None, REJECT_FLOOR_PINNED, None
    mean = statistics.mean(quiet)
    problem = _onset_transient_problem(trace, onset_i, mean)
    if problem is not None:
        return None, None, problem, None
    return (picked[0], picked[1], None,
            _first_lobe_peak(trace, onset_i, mean) * sample_interval_ns)


def _pick_onset_ns(trace: list[float], sample_interval_ns: float,
                   quiet_samples: int = QUIET_SAMPLES,
                   lead: int = 0) -> Optional[tuple[float, float]]:
    """
    The first sustained, high-confidence deviation from the pre-signal
    noise floor, in nanoseconds -- purely from this ONE trace's own
    amplitude structure. Returns (time_ns, confidence) or None. Mirrors
    `bam_hyperbola_velocity_audit.py::_direct_arrival_extent`'s "sustained
    run" philosophy: a single sample crossing a threshold can be a
    zero-crossing artefact; three consecutive samples cannot.

    This is the raw picker; `direct_wave_consensus_time_zero` only uses its
    output after the validity checks in `_pick_onset_checked`.
    """
    n = len(trace)
    if n - lead < quiet_samples + 10:
        return None
    quiet = trace[lead:lead + quiet_samples]
    mean = statistics.mean(quiet)
    sd = statistics.pstdev(quiet) or 1e-9
    run = 0
    for i in range(lead + quiet_samples, n - 2):
        dev = abs(trace[i] - mean) / sd
        if dev > MIN_PICK_CONFIDENCE:
            run += 1
            if run >= 3:
                onset_i = i - 2
                onset_dev = abs(trace[onset_i] - mean) / sd
                return onset_i * sample_interval_ns, onset_dev
        else:
            run = 0
    return None


def direct_wave_consensus_time_zero(
    records: list[SubterraRecord], sample_interval_ns: float,
    start_time_ns: float = 0.0,
) -> TimeZeroResult:
    """
    Picks the direct/coupling-wave onset on every trace in `records`
    independently, then takes a robust consensus.

    `records` must be RAW multi-sample traces (one record per trace, whole
    `signal`) -- the same shape `preprocessing.trace_processing.process_gpr_traces`
    expects for its "original shape" path. Per-sample records (SEGYConverter's
    other shape) are not supported here; a caller with that shape must
    reconstruct traces first, exactly as `process_gpr_traces` itself does.

    `start_time_ns` is the raw time of each trace's first sample (the
    normalised recording delay). The consensus onset is reported ON THE RAW
    AXIS -- start + index x interval -- because it is subtracted from raw
    times; reported as index x interval alone it would be off by the delay.
    """
    traces = [r.signal for r in records if len(r.signal) > 4]
    n_traces = len(traces)
    if n_traces == 0:
        return TimeZeroResult(
            status=TimeZeroStatus.UNAVAILABLE, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
            basis="no multi-sample traces were supplied; this method needs raw whole-trace "
                 "records, not depth-slice samples",
        )

    picks: list[float] = []
    confidences: list[float] = []
    peaks: list[float] = []
    rejections: dict[str, int] = {}
    for trace in traces:
        time_ns, confidence, reason, peak_ns = _pick_onset_checked(trace, sample_interval_ns)
        if reason is None:
            picks.append(time_ns)
            confidences.append(confidence)
            peaks.append(peak_ns)
        else:
            rejections[reason] = rejections.get(reason, 0) + 1

    if len(picks) < max(3, int(MIN_SUCCESS_FRACTION * n_traces)):
        refused = {k: v for k, v in rejections.items() if k != REJECT_NO_ONSET}
        why = (f"; candidate onsets refused by validity checks: "
               + ", ".join(f"{k}={v}" for k, v in sorted(refused.items()))
               if refused else "")
        return TimeZeroResult(
            status=TimeZeroStatus.INCONCLUSIVE, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
            basis=(f"only {len(picks)} of {n_traces} traces produced a valid pick above the "
                  f"confidence threshold ({MIN_PICK_CONFIDENCE}); too few for a defensible "
                  f"consensus{why}"),
            traces_evaluated=n_traces, successful_picks=len(picks),
            pick_rejections=rejections or None, generated_utc=_now(),
        )

    med = statistics.median(picks)
    deviations = sorted(abs(p - med) for p in picks)
    mad = deviations[len(deviations) // 2] or 0.05
    kept = [p for p in picks if abs(p - med) <= max(MAX_MAD_MULTIPLE * mad, 0.5)]
    n_outliers = len(picks) - len(kept)

    if len(kept) < 3:
        return TimeZeroResult(
            status=TimeZeroStatus.INCONCLUSIVE, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
            basis=(f"after robust outlier rejection, only {len(kept)} of {len(picks)} picks "
                  f"remain -- too few and too scattered for a defensible consensus"),
            traces_evaluated=n_traces, successful_picks=len(picks),
            outliers_rejected=n_outliers, pick_rejections=rejections or None,
            generated_utc=_now(),
        )

    consensus = start_time_ns + statistics.median(kept)
    spread = max(kept) - min(kept)

    if spread > MAX_CONSENSUS_SPREAD_NS:
        return TimeZeroResult(
            status=TimeZeroStatus.INCONCLUSIVE, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
            basis=(f"{len(kept)} traces agree within outlier rejection, but their picks span "
                  f"{spread:.3f} ns, exceeding the {MAX_CONSENSUS_SPREAD_NS} ns consistency "
                  f"bound this method requires to call the result a genuine consensus"),
            traces_evaluated=n_traces, successful_picks=len(picks),
            outliers_rejected=n_outliers, spread_ns=round(spread, 4),
            pick_rejections=rejections or None, generated_utc=_now(),
        )

    kept_peaks = [pk for p, pk in zip(picks, peaks) if p in kept]
    peak_consensus = start_time_ns + statistics.median(kept_peaks) if kept_peaks else None
    return TimeZeroResult(
        status=TimeZeroStatus.DERIVED, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
        correction_ns=round(consensus, 4), pick_convention="onset",
        direct_wave_peak_ns=None if peak_consensus is None else round(peak_consensus, 4),
        basis=(f"derived from a robust median consensus of {len(kept)} independently-picked "
              f"direct/coupling-wave onsets (of {n_traces} traces evaluated, "
              f"{n_outliers} rejected as outliers), agreeing within {spread:.3f} ns"),
        source="direct_wave_consensus", applied=False,
        traces_evaluated=n_traces, successful_picks=len(picks),
        outliers_rejected=n_outliers, spread_ns=round(spread, 4),
        pick_rejections=rejections or None, generated_utc=_now(),
    )


# ---------------------------------------------------------------------------
# applying a result: raw axis preserved, corrected axis added, never destructive
# ---------------------------------------------------------------------------

def apply_time_zero_correction(
    records: list[SubterraRecord], result: TimeZeroResult,
    time_field: str = "two_way_time_ns",
) -> list[SubterraRecord]:
    """
    Adds `original_time_ns` (an explicit copy of the untouched raw value)
    and `corrected_time_ns` to every record's metadata, and stamps
    `processing_applied` with `result.as_processing_applied()` so
    `schemas.dataset_report`'s EXISTING time-zero reporting reads it with
    no change to that module.

    `result.resolved` False (NOT_RUN / UNAVAILABLE / INCONCLUSIVE / FAILED)
    still stamps the honest status -- `corrected_time_ns` is left unset
    (never a copy of the raw value dressed up as "corrected") and `depth`
    is untouched.

    A record whose `corrected_time_ns` would be negative is EXCLUDED from
    depth eligibility here, not silently clamped -- see
    `TIME_ZERO_EXCLUDED_KEY`. It keeps `original_time_ns` and
    `corrected_time_ns` (the negative value itself, for auditability) but
    is marked so `recompute_depth_with_time_zero` skips it.
    """
    stamp = result.as_processing_applied()
    for r in records:
        raw = r.metadata.get(time_field)
        r.metadata["original_time_ns"] = raw
        if result.resolved and result.correction_ns is not None and raw is not None:
            corrected = raw - result.correction_ns
            r.metadata["corrected_time_ns"] = corrected
            r.metadata["time_zero_excluded"] = corrected < 0
        else:
            r.metadata["corrected_time_ns"] = None
            r.metadata["time_zero_excluded"] = False
        existing = r.metadata.get("processing_applied") or {}
        r.metadata["processing_applied"] = {**existing, **stamp}
        _invalidate_topographic_time(r)
    return records


def recompute_depth_with_time_zero(
    records: list[SubterraRecord], velocity_m_per_ns: float,
    velocity_source: str = "supplied_by_caller",
) -> list[SubterraRecord]:
    """
    `depth = corrected_time_ns * velocity / 2`, using the CORRECTED axis
    `apply_time_zero_correction` already computed -- never re-deriving it.

    NOT A PRODUCTION PATH. It takes a velocity of its own and stamps no
    derivation, so it cannot keep stored depth and provenance in step.
    Production code derives depth with `schemas.depth_model.rederive_depth`,
    from the frame's active velocity; this remains for the arithmetic tests.

    A record with no `corrected_time_ns` (correction unresolved) or one
    excluded for being negative keeps `depth = None` -- explicit absence,
    never a depth computed from an uncorrected or invalid time. This does
    NOT change what provenance class the resulting depth reports as:
    `schemas.provenance.record_provenance` already classifies any non-None
    depth as DERIVED regardless of velocity or time-zero source, and that
    is correct here too -- see that function's docstring. What changes is
    only the depth VALUE and the basis sentence explaining it (via
    `metadata["time_zero_status"]`, already stamped).
    """
    for r in records:
        corrected = r.metadata.get("corrected_time_ns")
        excluded = r.metadata.get("time_zero_excluded", False)
        if corrected is None or excluded:
            r.depth = None
            continue
        r.depth = two_way_time_to_depth(corrected, velocity_m_per_ns)
        r.metadata["velocity_m_per_ns"] = velocity_m_per_ns
        r.metadata["velocity_source"] = velocity_source
    return records


# ---------------------------------------------------------------------------
# production wiring: the method hierarchy, per frame, then applied and saved
# ---------------------------------------------------------------------------

def reconstruct_traces_by_time(
    records: list[SubterraRecord],
) -> tuple[Optional[dict], Optional[str]]:
    """
    Whole traces for time-zero picking, from quantities that exist WITHOUT a
    velocity: (source_file, trace_index) -> samples in raw two-way-time order.
    Returns (traces, None), or (None, reason) when the records cannot be
    reassembled without guessing.

    DEPTH IS NEVER READ. The shared `trace_processing._reconstruct_traces_by_index`
    (used by the processing chain the detector consumes, and left unchanged
    for that reason) requires a record depth and orders by it. A depth exists
    only once a velocity has been applied -- for SEG-Y usually the 0.1 m/ns
    default -- so a picker on the temporal waveform depended on an assumed
    velocity, and returned UNAVAILABLE for MALA/GSSI/IDS lines ingested
    without one.

    ORDER: `sample_index` (every converter records it) when every sample of
    the trace carries one, else the raw `two_way_time_ns`. Either way the
    order must be strictly increasing in raw time with no duplicate index or
    time; anything else is refused rather than silently re-sorted, because a
    trace whose samples cannot be ordered has no onset to pick.
    """
    if not records:
        return None, "no records"
    if any(len(r.signal) != 1 for r in records):
        return None, ("these records are not in the per-sample GPR shape (already "
                      "multi-sample-per-record) -- there is nothing to reconstruct whole "
                      "traces from")
    if any(r.metadata.get("trace_index") is None or r.metadata.get("two_way_time_ns") is None
           for r in records):
        return None, ("these records are not in the per-sample GPR shape (missing trace_index "
                      "or raw two_way_time_ns) -- there is nothing to reconstruct whole "
                      "traces from")

    by_trace: dict = {}
    for r in records:
        by_trace.setdefault((r.metadata.get("source_file", ""), r.metadata["trace_index"]),
                            []).append(r)
    for key, recs in by_trace.items():
        indices = [r.metadata.get("sample_index") for r in recs]
        if all(isinstance(i, int) for i in indices):
            if len(set(indices)) != len(indices):
                return None, f"trace {key}: duplicate sample_index, so sample order is unknown"
            recs.sort(key=lambda r: r.metadata["sample_index"])
        else:
            recs.sort(key=lambda r: r.metadata["two_way_time_ns"])
        times = [r.metadata["two_way_time_ns"] for r in recs]
        if any(b <= a for a, b in zip(times, times[1:])):
            return None, (f"trace {key}: raw two_way_time_ns is not strictly increasing in "
                          f"sample order (duplicate or out-of-order times), so the sample "
                          f"order cannot be established without guessing")
    return by_trace, None


def resolve_time_zero_for_frame(
    frame, records: list[SubterraRecord], sample_interval_ns: Optional[float] = None,
) -> TimeZeroResult:
    """
    The method hierarchy for ONE frame's own records, in priority order:
    Method A (`metadata_instrument_time_zero`) -> an existing operator
    `DeclarationKind.TIME_ZERO` declaration -> Method C
    (`direct_wave_consensus_time_zero`). The first resolved result wins;
    a stronger method is never overridden by a weaker one that happens to
    also succeed.

    SCOPED PER FRAME, DELIBERATELY, NOT PER DATASET. A real cross-file 4TU
    experiment (three independent SEG-Y lines, each DERIVED via Method C)
    found genuinely different values -- 0.776 / 0.873 / 1.764 ns -- so
    averaging them into one dataset-wide constant would misrepresent every
    one of the three. `records` must be this frame's own records only: a
    caller that mixes frames together would corrupt Method C's cross-trace
    consensus, which assumes every trace shares one acquisition clock.
    """
    result = metadata_instrument_time_zero(frame)
    if result.resolved:
        return result

    # A KNOWN-GEOMETRY CALIBRATION outranks a bare declaration and Method C: its
    # time zero was fitted together with the frame's active velocity, and
    # re-running the hierarchy must not split that pair.
    calibrated = _active_calibration_time_zero(frame)
    if calibrated is not None:
        return calibrated

    declared = frame.assumption(DECLARED_TIME_ZERO_KEY)
    if declared is not None:
        try:
            correction = float(declared.value)
        except (TypeError, ValueError):
            correction = None
        if correction is not None and math.isfinite(correction):
            from schemas.depth_model import declaration_id_of

            return TimeZeroResult(
                status=TimeZeroStatus.DECLARED, method=TimeZeroMethod.OPERATOR_DECLARED,
                correction_ns=correction, basis=declared.basis,
                source="DeclarationKind.TIME_ZERO", generated_utc=_now(),
                declaration_id=declaration_id_of(frame, "time_zero"),
            )

    by_trace, problem = reconstruct_traces_by_time(records)
    if by_trace is None:
        return TimeZeroResult(
            status=TimeZeroStatus.UNAVAILABLE, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
            basis=problem,
        )

    whole_traces: list[SubterraRecord] = []
    intervals: list[float] = []
    starts: list[float] = []
    for recs in by_trace.values():
        if recs[0].metadata.get("two_way_time_ns") is not None:
            starts.append(recs[0].metadata["two_way_time_ns"])
        whole_traces.append(recs[0].model_copy(update={"signal": [r.signal[0] for r in recs]}))
        times = [r.metadata.get("two_way_time_ns") for r in recs[:2]]
        if len(times) == 2 and all(t is not None for t in times):
            intervals.append(times[1] - times[0])

    if sample_interval_ns is None:
        sample_interval_ns = statistics.median(intervals) if intervals else None
    if not sample_interval_ns or sample_interval_ns <= 0:
        return TimeZeroResult(
            status=TimeZeroStatus.UNAVAILABLE, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
            basis="no usable sample interval could be established from these records' own "
                 "two_way_time_ns spacing",
        )

    start = statistics.median(starts) if starts else 0.0

    # VENDOR MARKER SAMPLES ARE NOT WAVEFORM. A converter that knows its
    # format's leading samples may carry markers says so on the frame (GSSI:
    # `leading_samples_may_be_markers` = 2). Left in, they sit in the quiet
    # window and inflate its noise estimate by orders of magnitude, so a real
    # arrival is picked deep in the main lobe or not at all. They are dropped
    # from every trace and the start advances by the same number of samples,
    # so the pick stays on the raw axis. Frames without the assumption: no-op.
    markers = _declared_marker_samples(frame)
    if markers:
        whole_traces = [t.model_copy(update={"signal": t.signal[markers:]}) for t in whole_traces]
        start += markers * sample_interval_ns
    return direct_wave_consensus_time_zero(whole_traces, sample_interval_ns, start_time_ns=start)


def _active_calibration_time_zero(frame) -> Optional[TimeZeroResult]:
    """The applied CALIBRATED result, while its paired velocity is still active."""
    from schemas.time_zero import APPLIED_TIME_ZERO_KEY

    a = frame.assumption(APPLIED_TIME_ZERO_KEY) if hasattr(frame, "assumption") else None
    if a is None or not isinstance(a.value, dict):
        return None
    try:
        result = TimeZeroResult.model_validate(a.value)
    except ValueError:
        return None
    if result.status is not TimeZeroStatus.CALIBRATED:
        return None
    conv = getattr(getattr(frame, "vertical_axis", None), "conversion", None) or {}
    if conv.get("velocity_basis") != "calibrated_from_known_geometry":
        return None
    return result.model_copy(update={"applied": False})


#: The converter-recorded count of leading samples that may be vendor markers.
MARKER_SAMPLES_KEY = "leading_samples_may_be_markers"


def _declared_marker_samples(frame) -> int:
    a = frame.assumption(MARKER_SAMPLES_KEY) if hasattr(frame, "assumption") else None
    if a is None:
        return 0
    try:
        n = int(a.value)
    except (TypeError, ValueError):
        return 0
    return n if 0 < n < 64 else 0


def revert_time_zero(records: list[SubterraRecord]) -> None:
    """
    Removes an applied correction from records: no `corrected_time_ns`, nothing
    excluded, no `time_zero*` processing stamp. Raw time is untouched. Used
    when the time zero that produced the correction is no longer the active
    one (a new TIME_ZERO declaration), so no record keeps a correction nobody
    currently asserts.
    """
    for r in records:
        if "corrected_time_ns" in r.metadata:
            r.metadata["corrected_time_ns"] = None
            r.metadata["time_zero_excluded"] = False
        applied = r.metadata.get("processing_applied")
        if applied:
            r.metadata["processing_applied"] = {
                k: v for k, v in applied.items()
                if k != "time_zero" and not k.startswith("time_zero_")}
        _invalidate_topographic_time(r)


def _invalidate_topographic_time(record: SubterraRecord) -> None:
    """
    `topographic_corrected_time_ns` is built on `corrected_time_ns`
    (`preprocessing.topographic_correction`); when the time-zero correction
    changes it describes a superseded axis. Cleared, with its stamp, until
    the topographic correction is run again -- never recomputed silently.
    """
    if record.metadata.get("topographic_corrected_time_ns") is None:
        return
    record.metadata["topographic_corrected_time_ns"] = None
    applied = record.metadata.get("processing_applied")
    if applied:
        record.metadata["processing_applied"] = {
            k: v for k, v in applied.items()
            if k != "topographic_correction" and not k.startswith("topographic_correction_")}


def _persist_on_frame(frame, result: TimeZeroResult) -> None:
    """
    Records the result on the FRAME (`APPLIED_TIME_ZERO_KEY`), replacing any
    earlier one, so the frame -- not only its records -- says which time zero
    its depth rests on. A declaration that fed it stays under its own key.
    """
    from schemas.spatial import Assumption
    from schemas.time_zero import APPLIED_TIME_ZERO_KEY

    note = Assumption(
        key=APPLIED_TIME_ZERO_KEY, value=result.model_dump(mode="json"),
        basis=(f"time zero {result.status.value} by {result.method.value}"
               + (f": correction {result.correction_ns:g} ns applied to the records' "
                  f"corrected_time_ns (raw two_way_time_ns kept)"
                  if result.applied and result.correction_ns is not None
                  else ": nothing applied") + f". {result.basis}"),
        verified=False)
    frame.assumptions = [a for a in (frame.assumptions or [])
                         if a.key != APPLIED_TIME_ZERO_KEY] + [note]


def apply_time_zero_for_dataset(
    records: list[SubterraRecord], frames: list,
) -> tuple[list[SubterraRecord], dict[str, TimeZeroResult]]:
    """
    Runs `resolve_time_zero_for_frame` and applies the winning result, PER
    FRAME, mutating `records` in place (they are the same objects grouped
    by `frame_id`, not copies) and returning them alongside one
    `TimeZeroResult` per frame_id actually resolved.

    Records with no `frame_id` (pre-frame datasets, or a non-GPR modality)
    are left completely untouched -- there is no frame to resolve
    `metadata_instrument_time_zero` or a declaration against, and this is
    not the place to invent one.

    THREE STEPS, EACH NAMED IN THE PROVENANCE:
      1. select the time zero (declaration -> Method C) and record it on the
         frame (`APPLIED_TIME_ZERO_KEY`, with its declaration id if any);
      2. derive corrected travel time (`corrected_time_ns`; raw kept);
      3. derive depth with `schemas.depth_model.rederive_depth`, from the
         frame's ONE active velocity (`active_velocity`) -- never a velocity
         of its own. With no velocity, time zero is still applied and depth
         stays absent.

    An unresolved result leaves no correction active: records return to the
    raw axis and depth is rederived from it, so no earlier correction can
    survive in a stored number.
    """
    from schemas.depth_model import rederive_depth

    frames_by_frame_id = {f.frame_id: f for f in frames}
    by_frame: dict[Optional[str], list[SubterraRecord]] = {}
    for r in records:
        by_frame.setdefault(r.frame_id, []).append(r)

    results: dict[str, TimeZeroResult] = {}
    for frame_id, frame_records in by_frame.items():
        frame = frames_by_frame_id.get(frame_id)
        if frame is None:
            continue

        result = resolve_time_zero_for_frame(frame, frame_records)
        if result.resolved:
            result = result.model_copy(update={"applied": True})
        apply_time_zero_correction(frame_records, result)
        _persist_on_frame(frame, result)
        rederive_depth(frame, frame_records)
        results[frame_id] = result

    return records, results
