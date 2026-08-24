"""
Time-zero: where a GPR trace's own recorded time axis actually starts,
relative to the physical event depth is supposed to be measured from.

WHY THIS IS ITS OWN MODULE. `depth = velocity * (two_way_time - t0) / 2` has
two unknowns, and this platform already has a whole vocabulary
(`schemas.provenance`) for being honest about the SECOND one (velocity). It
has had nothing for the first. Collapsing "time-zero" into "just another
Assumption" would work for STORING one value, but it would not let two
converters' UNRELATED reasons for not having a t0 (GSSI's `rhf_position`
being of unestablished meaning; SEG-Y having no header field at all) be told
apart from a genuine algorithmic failure, or from an operator's declaration.
Those are different facts and this module keeps them different.

FOUR DISTINCT THINGS, NEVER COLLAPSED INTO ONE NUMBER (see the milestone
brief this module implements):

    instrument time-zero    the acquisition system's own zero/reference
                             sample -- a property of the recording hardware,
                             not of the ground.
    signal onset /          the observed arrival of a real physical
    direct-wave arrival     propagation path (direct/coupling wave), which
                             is not necessarily at instrument time-zero.
    air-gap correction      the delay between instrument zero and the
                             ground/surface interaction, from antenna
                             geometry -- a SPATIAL fact in metres
                             (`schemas.spatial.DepthOriginOffset`,
                             `DeclarationKind.ANTENNA_OFFSET`), not this
                             module's concern once converted; this module
                             produces the TIME correction that would need to
                             exist before that geometry is even meaningful.
    operator-declared       a correction asserted by a person from evidence
    correction               Subterra did not compute.

`TimeZeroResult` carries which of these a given correction actually is
(`method`), whether it was obtained at all (`status`), and -- critically --
NEVER reports a number without both.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TimeZeroMethod(str, Enum):
    """How a correction (or the absence of one) was arrived at. Never inferred from `status` alone."""
    #: Nothing was attempted for this dataset/frame.
    NONE = "none"
    #: A standard, well-documented acquisition-metadata field the converter
    #: already parses (e.g. SEG-Y `DelayRecordingTime`). NEVER a vendor
    #: field whose meaning is not independently established (GSSI
    #: `rhf_position`, MALA `SIGNAL POSITION` -- see `metadata_instrument_time_zero`).
    METADATA_INSTRUMENT = "metadata_instrument"
    #: A human asserted a correction from evidence external to this pipeline.
    OPERATOR_DECLARED = "operator_declared"
    #: A robust, cross-trace consensus pick of the direct/coupling-wave
    #: onset, algorithmic, from the trace amplitudes themselves.
    DIRECT_WAVE_CONSENSUS = "direct_wave_consensus"


class TimeZeroStatus(str, Enum):
    """
    The outcome of one attempt, independent of which method was tried.

    Mirrors the classification vocabulary this repository's own research
    audits already use (VALIDATED/ESTIMATED/INCONCLUSIVE/FAILED in
    `scripts/bam_hyperbola_velocity_audit.py` and siblings) rather than
    inventing a new one -- narrowed to what a time-zero ATTEMPT can
    honestly report. `NOT_RUN` and `UNAVAILABLE` are deliberately distinct
    from each other for the same reason `dataset_report.py`'s
    `Readiness`/`ProcessingStage` never conflate "not run yet" (a
    scheduling fact) with "cannot be run" (a property of the evidence):
    a caller that never asked is not the same fact as a caller who asked
    and found nothing to work with.
    """
    NOT_RUN = "not_run"
    UNAVAILABLE = "unavailable"
    DECLARED = "declared"
    DERIVED = "derived"
    MEASURED = "measured"
    INCONCLUSIVE = "inconclusive"
    FAILED = "failed"


#: The statuses that mean a numeric correction actually exists and may be applied.
RESOLVED_TIME_ZERO_STATUSES: tuple[TimeZeroStatus, ...] = (
    TimeZeroStatus.DECLARED, TimeZeroStatus.DERIVED, TimeZeroStatus.MEASURED,
)


class TimeZeroResult(BaseModel):
    """
    One attempt's complete, honest answer -- carried as a value, the same
    way `schemas.provenance.QuantityProvenance` is, so a caller need not
    re-derive "was this actually applied" from a scattering of booleans.

    `correction_ns` is None whenever `status` is not in
    `RESOLVED_TIME_ZERO_STATUSES` -- there is no such thing as a
    provisional or best-guess correction here.
    """
    status: TimeZeroStatus
    method: TimeZeroMethod
    correction_ns: Optional[float] = None
    #: Free text: what evidence this rests on, required whenever `status`
    #: is resolved. Mirrors `QuantityProvenance.basis`'s own requirement.
    basis: str = Field(..., min_length=1)
    #: A human-attributable source for OPERATOR_DECLARED; the field/header
    #: name for METADATA_INSTRUMENT; the algorithm name for
    #: DIRECT_WAVE_CONSENSUS. Optional because NOT_RUN/UNAVAILABLE have none.
    source: Optional[str] = None
    applied: bool = False
    generated_utc: Optional[datetime] = None

    # --- diagnostics DIRECT_WAVE_CONSENSUS actually computes; None elsewhere ---
    traces_evaluated: Optional[int] = None
    successful_picks: Optional[int] = None
    outliers_rejected: Optional[int] = None
    #: Robust spread (max absolute deviation from the median, ns) across the
    #: successful per-trace picks that WERE kept, after outlier rejection --
    #: never fabricated for a method that does not compute one.
    spread_ns: Optional[float] = None

    @property
    def resolved(self) -> bool:
        return self.status in RESOLVED_TIME_ZERO_STATUSES

    def as_processing_applied(self) -> dict:
        """
        The `time_zero_*`-prefixed keys `schemas.dataset_report._time_zero_step`
        already reads generically from a record's `processing_applied` dict
        (see that function's docstring: "(1) `processing_applied`'s own
        time-zero keys, if a future step of `process_gpr_traces` ever stamps
        them -- none does today"). This is that future step's own contract,
        so the existing report machinery needs no change to display it.
        """
        out = {
            "time_zero": self.applied,
            "time_zero_status": self.status.value,
            "time_zero_method": self.method.value,
            "time_zero_basis": self.basis,
        }
        if self.correction_ns is not None:
            out["time_zero_correction_ns"] = self.correction_ns
        if self.source is not None:
            out["time_zero_source"] = self.source
        if self.traces_evaluated is not None:
            out["time_zero_traces_evaluated"] = self.traces_evaluated
        if self.successful_picks is not None:
            out["time_zero_successful_picks"] = self.successful_picks
        if self.outliers_rejected is not None:
            out["time_zero_outliers_rejected"] = self.outliers_rejected
        if self.spread_ns is not None:
            out["time_zero_spread_ns"] = self.spread_ns
        return out
