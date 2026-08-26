"""
Topographic/air-gap correction: a PER-TRACE refinement of a frame's own
(per-line) time-zero correction, for a real air-gap that VARIES along a
line -- as opposed to a constant antenna height above ground, which a
single time-zero correction already absorbs.

WHY THIS IS SEPARATE FROM `schemas.time_zero`. Time-zero resolves ONE
constant per frame (`TimeZeroResult.correction_ns`, a scalar). This module
answers a narrower, PER-TRACE question a scalar structurally cannot: does
the antenna's height above the REAL ground (not the acquisition's own
declared elevation, which is the antenna's own height, not the ground's)
vary enough along the line to be resolvable against the acquisition's own
temporal resolution. See `scripts/four_tu_topographic_correction_audit.py`
-- a real, evidence-based research audit found real 4TU lines where it
does (height-above-ground varies 5-16 cm along a single line, converting
to a correction that exceeds that line's own sample interval in every
line checked). This module productionizes that audit's exact methodology
into a reusable, tested capability -- same computation, same "material"
threshold -- so it can eventually be applied rather than only reported.

WHY THE ABSOLUTE HEIGHT-ABOVE-GROUND VALUE IS NEVER TRUSTED, ONLY ITS
VARIATION. Both elevation sources (an antenna's own GNSS reading and a DEM)
typically carry an undeclared or differing vertical datum. A constant datum
offset between them biases the ABSOLUTE height-above-ground by an unknown
amount, but cancels exactly out of a DIFFERENTIAL correction relative to
the line's own median -- see `preprocessing.topographic_correction`'s
docstring for the arithmetic. This module's result never carries or
implies an absolute height-above-ground value, only the per-trace
deviation-derived correction.

ONE METHOD TODAY, NAMED RATHER THAN IMPLICIT -- mirrors `schemas.time_zero`'s
own "explicit methods, never guessed" discipline: a future GNSS/RTK-based
method would get its own enum member, never silently reuse this one's name
for a different computation.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TopographicCorrectionMethod(str, Enum):
    #: Nothing was attempted for this dataset/frame.
    NONE = "none"
    #: Antenna elevation (from the acquisition's own declared/measured
    #: reading) minus DEM ground elevation, differenced against the line's
    #: own median height-above-ground -- see
    #: `preprocessing.topographic_correction.dem_antenna_differential_correction`.
    DEM_ANTENNA_DIFFERENTIAL = "dem_antenna_differential"


class TopographicCorrectionStatus(str, Enum):
    """
    The outcome of one attempt, independent of which method was tried.

    `NOT_MATERIAL` is deliberately distinct from `UNAVAILABLE`: the first
    means the computation succeeded and concluded no per-trace correction
    is warranted (the real, honest answer for a terrain-following
    acquisition); the second means the computation could not be attempted
    at all (missing antenna elevation, missing DEM ground elevation, or
    too few traces carrying both). Conflating them would hide which kind
    of "no" a caller is looking at -- the same discipline
    `schemas.time_zero.TimeZeroStatus` already applies to `NOT_RUN` vs
    `UNAVAILABLE`.
    """
    NOT_RUN = "not_run"
    UNAVAILABLE = "unavailable"
    INCONCLUSIVE = "inconclusive"
    NOT_MATERIAL = "not_material"
    DERIVED = "derived"


#: The only status carrying an applicable per-trace correction. Deliberately
#: excludes NOT_MATERIAL: that status is a complete, honest, non-actionable
#: answer ("no correction is resolvable here"), not a partial DERIVED.
RESOLVED_TOPOGRAPHIC_CORRECTION_STATUSES: tuple[TopographicCorrectionStatus, ...] = (
    TopographicCorrectionStatus.DERIVED,
)


class TopographicCorrectionResult(BaseModel):
    """
    One attempt's complete, honest answer for one line/frame, carried as a
    value the same way `schemas.time_zero.TimeZeroResult` is.

    `per_trace_correction_ns` is None whenever `status` is not `DERIVED` --
    there is no such thing as a provisional or partially-applicable
    per-trace correction here.
    """
    status: TopographicCorrectionStatus
    method: TopographicCorrectionMethod
    #: trace_index -> two-way air-time correction (ns). Only set when
    #: `status == DERIVED`.
    per_trace_correction_ns: Optional[dict[int, float]] = None
    max_abs_correction_ns: Optional[float] = None
    sample_interval_ns: Optional[float] = None
    #: Free text: what evidence this rests on, required whenever a result
    #: exists at all. Mirrors `TimeZeroResult.basis`'s own requirement.
    basis: str = Field(..., min_length=1)
    n_traces_evaluated: Optional[int] = None
    n_traces_valid: Optional[int] = None
    #: Diagnostics from the underlying height-above-ground computation --
    #: never an absolute value, only spread, for the reason in the module
    #: docstring.
    height_above_ground_range_m: Optional[float] = None
    height_above_ground_std_m: Optional[float] = None
    applied: bool = False
    generated_utc: Optional[datetime] = None

    @property
    def resolved(self) -> bool:
        return self.status in RESOLVED_TOPOGRAPHIC_CORRECTION_STATUSES

    def as_processing_applied(self) -> dict:
        """
        Namespaced `topographic_*` keys, mirroring
        `TimeZeroResult.as_processing_applied`'s own contract so a future
        `schemas.dataset_report` reader can pick these up the same way it
        already reads `time_zero_*` keys generically -- no change needed
        to that module for this stamp alone to be visible.
        """
        out = {
            "topographic_correction": self.applied,
            "topographic_correction_status": self.status.value,
            "topographic_correction_method": self.method.value,
            "topographic_correction_basis": self.basis,
        }
        if self.max_abs_correction_ns is not None:
            out["topographic_correction_max_abs_ns"] = self.max_abs_correction_ns
        if self.sample_interval_ns is not None:
            out["topographic_correction_sample_interval_ns"] = self.sample_interval_ns
        if self.n_traces_evaluated is not None:
            out["topographic_correction_traces_evaluated"] = self.n_traces_evaluated
        if self.n_traces_valid is not None:
            out["topographic_correction_traces_valid"] = self.n_traces_valid
        return out
