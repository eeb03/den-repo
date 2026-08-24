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
    Looks for the ONE standard, documented field this module trusts: SEG-Y's
    `DelayRecordingTime`, already parsed by `converters/segy_converter.py`
    into the frame's `time_axis_origin_offset` assumption. Any other
    frame -- including one that carries `time_zero_offset_not_applied`,
    which by construction means the converter itself judged the field's
    meaning unestablished -- returns UNAVAILABLE. Nothing here reinterprets
    a vendor field; it only reads a value a converter already classified.
    """
    claim = frame.assumption(SEGY_ORIGIN_OFFSET_KEY)
    if claim is None:
        return TimeZeroResult(
            status=TimeZeroStatus.UNAVAILABLE, method=TimeZeroMethod.METADATA_INSTRUMENT,
            basis="no standard, documented time-zero field (SEG-Y DelayRecordingTime) is "
                 "recorded for this frame; this method does not reinterpret vendor fields "
                 "of unestablished meaning",
        )
    try:
        correction = float(claim.value)
    except (TypeError, ValueError):
        return TimeZeroResult(
            status=TimeZeroStatus.UNAVAILABLE, method=TimeZeroMethod.METADATA_INSTRUMENT,
            basis=f"the recorded {SEGY_ORIGIN_OFFSET_KEY!r} value {claim.value!r} is not numeric",
        )
    return TimeZeroResult(
        status=TimeZeroStatus.MEASURED, method=TimeZeroMethod.METADATA_INSTRUMENT,
        correction_ns=correction,
        basis=(f"declared by the acquisition's own SEG-Y DelayRecordingTime header field, "
              f"read by the converter as {SEGY_ORIGIN_OFFSET_KEY}: {claim.basis}"),
        source="SEG-Y DelayRecordingTime", generated_utc=_now(),
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


def _pick_onset_ns(trace: list[float], sample_interval_ns: float,
                   quiet_samples: int = QUIET_SAMPLES) -> Optional[tuple[float, float]]:
    """
    The first sustained, high-confidence deviation from the pre-signal
    noise floor, in nanoseconds -- purely from this ONE trace's own
    amplitude structure. Returns (time_ns, confidence) or None. Mirrors
    `bam_hyperbola_velocity_audit.py::_direct_arrival_extent`'s "sustained
    run" philosophy: a single sample crossing a threshold can be a
    zero-crossing artefact; three consecutive samples cannot.
    """
    n = len(trace)
    if n < quiet_samples + 10:
        return None
    quiet = trace[:quiet_samples]
    mean = statistics.mean(quiet)
    sd = statistics.pstdev(quiet) or 1e-9
    run = 0
    for i in range(quiet_samples, n - 2):
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
) -> TimeZeroResult:
    """
    Picks the direct/coupling-wave onset on every trace in `records`
    independently, then takes a robust consensus.

    `records` must be RAW multi-sample traces (one record per trace, whole
    `signal`) -- the same shape `preprocessing.trace_processing.process_gpr_traces`
    expects for its "original shape" path. Per-sample records (SEGYConverter's
    other shape) are not supported here; a caller with that shape must
    reconstruct traces first, exactly as `process_gpr_traces` itself does.
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
    for trace in traces:
        result = _pick_onset_ns(trace, sample_interval_ns)
        if result is not None:
            picks.append(result[0])
            confidences.append(result[1])

    if len(picks) < max(3, int(MIN_SUCCESS_FRACTION * n_traces)):
        return TimeZeroResult(
            status=TimeZeroStatus.INCONCLUSIVE, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
            basis=(f"only {len(picks)} of {n_traces} traces produced a pick above the "
                  f"confidence threshold ({MIN_PICK_CONFIDENCE}); too few for a defensible "
                  f"consensus"),
            traces_evaluated=n_traces, successful_picks=len(picks), generated_utc=_now(),
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
            outliers_rejected=n_outliers, generated_utc=_now(),
        )

    consensus = statistics.median(kept)
    spread = max(kept) - min(kept)

    if spread > MAX_CONSENSUS_SPREAD_NS:
        return TimeZeroResult(
            status=TimeZeroStatus.INCONCLUSIVE, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
            basis=(f"{len(kept)} traces agree within outlier rejection, but their picks span "
                  f"{spread:.3f} ns, exceeding the {MAX_CONSENSUS_SPREAD_NS} ns consistency "
                  f"bound this method requires to call the result a genuine consensus"),
            traces_evaluated=n_traces, successful_picks=len(picks),
            outliers_rejected=n_outliers, spread_ns=round(spread, 4), generated_utc=_now(),
        )

    return TimeZeroResult(
        status=TimeZeroStatus.DERIVED, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
        correction_ns=round(consensus, 4),
        basis=(f"derived from a robust median consensus of {len(kept)} independently-picked "
              f"direct/coupling-wave onsets (of {n_traces} traces evaluated, "
              f"{n_outliers} rejected as outliers), agreeing within {spread:.3f} ns"),
        source="direct_wave_consensus", applied=False,
        traces_evaluated=n_traces, successful_picks=len(picks),
        outliers_rejected=n_outliers, spread_ns=round(spread, 4), generated_utc=_now(),
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
    return records


def recompute_depth_with_time_zero(
    records: list[SubterraRecord], velocity_m_per_ns: float,
    velocity_source: str = "supplied_by_caller",
) -> list[SubterraRecord]:
    """
    `depth = corrected_time_ns * velocity / 2`, using the CORRECTED axis
    `apply_time_zero_correction` already computed -- never re-deriving it.

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
        r.depth = (corrected * velocity_m_per_ns) / 2.0
        r.metadata["velocity_m_per_ns"] = velocity_m_per_ns
        r.metadata["velocity_source"] = velocity_source
    return records
