"""
What a radargram's axes mean, and where a candidate sits on it.

WHY THIS IS A MODULE AND NOT A FEW LINES IN A COMPONENT. Two decisions in the
viewer are scientific claims wearing the clothes of formatting:

  1. What the vertical axis is called. `two_way_time_ns` converted with an
     UNCALIBRATED DEFAULT velocity is not the same quantity as a depth derived
     from a velocity somebody declared for this site, and neither is a measured
     depth. A label is the whole difference between reporting a measurement and
     inventing one, so the decision is made here, tested, and handed to the UI
     already made.

  2. What the grid's numbers ARE. `preprocess_trace_local_anomaly` OVERWRITES
     `record.signal` with the local-anomaly z-score and keeps the amplitude in
     `metadata["pre_anomaly_signal"]`. A viewer that reads `field="signal"` and
     labels the result "amplitude" would present statistical evidence as a
     physical measurement -- precisely the error
     `_require_anomaly_processed` refuses in the other direction.

THE MAPPING IS EXACT OR IT IS REFUSED. `AnomalyEvidence.trace_range` holds real
SEG-Y trace_index VALUES and `depth_range` holds real depth VALUES; the grid
carries `trace_indices` and `depths` for its columns and rows. So a candidate's
footprint is a lookup, not an estimate. When a value is not present in the grid
-- a stale candidate from a line that has since been reprocessed, say -- the
footprint is returned unplaceable WITH A REASON rather than clamped to the
nearest column. An approximately-placed candidate is worse than an absent one:
it invites a reviewer to check the wrong traces and report back that the
detector was wrong about a region it never proposed.
"""
from __future__ import annotations

from bisect import bisect_left
from enum import Enum
from typing import Optional, Sequence

from pydantic import BaseModel, Field


class VerticalAxisKind(str, Enum):
    """
    What the rows of the grid actually are.

    `DERIVED_DEPTH_DEFAULT` exists because the alternative is to call it depth.
    The SEG-Y converter applies `DEFAULT_GPR_VELOCITY_M_PER_NS = 0.1` so that a
    depth axis exists at all, and that number is a placeholder nobody measured
    on this ground. Collapsing it into `DERIVED_DEPTH_DECLARED` would turn a
    default into an assertion.
    """
    SAMPLE_INDEX = "sample_index"
    TWO_WAY_TIME_NS = "two_way_time_ns"
    DERIVED_DEPTH_DEFAULT = "derived_depth_default_velocity"
    DERIVED_DEPTH_DECLARED = "derived_depth_declared_velocity"
    MEASURED_DEPTH_M = "measured_depth_m"
    UNKNOWN = "unknown"


class VelocitySource(str, Enum):
    NONE = "none"
    #: The converter's placeholder, applied so an axis exists. Not a measurement.
    CONVERTER_DEFAULT = "converter_default"
    #: Somebody asserted it for this dataset, with an attribution.
    DECLARED = "declared"


class VerticalAxis(BaseModel):
    """The vertical axis, described so a renderer cannot mislabel it."""
    kind: VerticalAxisKind
    #: Exactly what to print beside the axis. Never "Depth (m)" for a derived axis.
    label: str
    units: Optional[str]
    #: Why the label says what it says.
    basis: str
    is_derived: bool
    velocity_source: VelocitySource
    velocity_m_per_ns: Optional[float] = None
    #: Present whenever the axis is derived. The UI must show it.
    caveat: Optional[str] = None


class HorizontalAxis(BaseModel):
    """
    The horizontal axis.

    Geographic positioning is offered ONLY when the traces genuinely carry it.
    Stage 13 established that a candidate locatable by trace is trace-relative,
    which is a real location and not a coordinate; the same holds for the axis
    it sits on.
    """
    kind: str            # trace_index | along_track_m | geographic
    label: str
    units: Optional[str]
    basis: str
    geographic_available: bool


DERIVED_DEFAULT_CAVEAT = (
    "Derived from two-way travel time using the converter's default velocity of "
    "{v} m/ns. Nobody measured or declared this for this site -- it is a "
    "placeholder that lets a depth axis exist, and true depth could differ "
    "substantially. Declare a velocity to replace it."
)

DERIVED_DECLARED_CAVEAT = (
    "Derived from two-way travel time using a declared velocity of {v} m/ns. A "
    "velocity is an assumption about this ground, so this depth is derived and "
    "not measured."
)


def describe_vertical_axis(survey_frame: Optional[dict],
                           velocity_m_per_ns: Optional[float],
                           velocity_is_declared: bool = False) -> VerticalAxis:
    """
    Decide what the vertical axis is, from the frame and the velocity's origin.

    `velocity_is_declared` is supplied by the caller because only the caller can
    see the spatial declaration log. Defaulting it to False is deliberate: an
    undeclared velocity must never be presented as a declared one, and the safe
    direction for an unknown is the weaker claim.
    """
    axis = (survey_frame or {}).get("vertical_axis") or {}
    kind = axis.get("kind")
    conversion = axis.get("conversion")

    if velocity_m_per_ns is not None and conversion:
        if velocity_is_declared:
            return VerticalAxis(
                kind=VerticalAxisKind.DERIVED_DEPTH_DECLARED,
                label="Derived depth", units="m",
                basis=(f"{kind} converted with a declared velocity "
                       f"({conversion.get('method', 'constant_velocity')})"),
                is_derived=True, velocity_source=VelocitySource.DECLARED,
                velocity_m_per_ns=velocity_m_per_ns,
                caveat=DERIVED_DECLARED_CAVEAT.format(v=velocity_m_per_ns))
        return VerticalAxis(
            kind=VerticalAxisKind.DERIVED_DEPTH_DEFAULT,
            label="Derived depth (default velocity)", units="m",
            basis=f"{kind} converted with the converter's default velocity",
            is_derived=True, velocity_source=VelocitySource.CONVERTER_DEFAULT,
            velocity_m_per_ns=velocity_m_per_ns,
            caveat=DERIVED_DEFAULT_CAVEAT.format(v=velocity_m_per_ns))

    if kind == "two_way_time_ns":
        return VerticalAxis(
            kind=VerticalAxisKind.TWO_WAY_TIME_NS,
            label="Two-way time", units="ns",
            basis="the instrument's own time axis; no velocity has been supplied",
            is_derived=False, velocity_source=VelocitySource.NONE)

    if kind == "depth_m":
        return VerticalAxis(
            kind=VerticalAxisKind.MEASURED_DEPTH_M,
            label="Depth", units="m",
            basis="the acquisition declares a depth axis directly",
            is_derived=False, velocity_source=VelocitySource.NONE)

    return VerticalAxis(
        kind=VerticalAxisKind.SAMPLE_INDEX,
        label="Sample", units=None,
        basis=("no frame states what the vertical axis measures, so rows are "
               "shown as sample positions and nothing more"),
        is_derived=False, velocity_source=VelocitySource.NONE)


def describe_horizontal_axis(trace_geographic: Optional[Sequence[bool]],
                             along_track: Optional[Sequence[Optional[float]]],
                             ) -> HorizontalAxis:
    """
    Trace index unless the data genuinely supports something stronger.

    The grid's columns are evenly spaced in TRACE INDEX, not in metres. Where
    along-track distance is measured it is offered as a reading for the columns,
    never as a respacing of them -- redrawing the image on a distance axis would
    resample measured data.
    """
    geographic = bool(trace_geographic) and any(bool(v) for v in trace_geographic)
    measured_along_track = bool(along_track) and any(v is not None for v in along_track)

    if measured_along_track:
        return HorizontalAxis(
            kind="along_track_m", label="Along-track distance", units="m",
            basis=("columns are evenly spaced by trace index; the distance "
                   "reading comes from the acquisition's own odometry"),
            geographic_available=geographic)
    return HorizontalAxis(
        kind="trace_index", label="Trace", units=None,
        basis=("the acquisition supplies no along-track distance, so a column "
               "is identified by its trace index"),
        geographic_available=geographic)


# ---------------------------------------------------------------------------
# what the grid's values are
# ---------------------------------------------------------------------------

class FieldSemantics(BaseModel):
    """
    What the numbers in the grid mean.

    Without this a viewer reads `field="signal"` and guesses. On a dataset that
    has been through trace-local anomaly preprocessing the guess is wrong: the
    values are z-scores, and the amplitude they were computed from is somewhere
    else entirely.
    """
    field: str
    label: str
    units: Optional[str]
    description: str
    #: True when the values are a statistic over the signal rather than signal.
    is_statistic: bool


def describe_field(field: str, anomaly_processed: bool) -> FieldSemantics:
    if field == "signal" and anomaly_processed:
        return FieldSemantics(
            field=field, label="Local-anomaly z-score", units="σ",
            description=(
                "each cell is how far that sample sits from the background "
                "estimated in a ring around it, in standard deviations. This is "
                "a statistic computed FROM the amplitude, not the amplitude: the "
                "recorded signal is preserved separately as pre_anomaly_signal."),
            is_statistic=True)
    if field == "signal":
        return FieldSemantics(
            field=field, label="Recorded amplitude", units=None,
            description=("the converter's recorded sample values, in whatever "
                         "units the acquisition used; no anomaly preprocessing "
                         "has been applied to this dataset"),
            is_statistic=False)
    if field in ("elevation", "absolute_elevation_m"):
        return FieldSemantics(
            field=field, label=field.replace("_", " ").capitalize(), units="m",
            description="per-record elevation as stored", is_statistic=False)
    return FieldSemantics(
        field=field, label=field, units=None,
        description="as stored on the record", is_statistic=False)


# ---------------------------------------------------------------------------
# candidate -> grid
# ---------------------------------------------------------------------------

#: Depth values in a candidate and in the grid come from the SAME record field,
#: so they should match exactly. A JSON round trip can still perturb the last
#: bits of a float, so lookup allows a hair of slack -- far below one sample
#: spacing, which on the corpus held is ~0.005 m.
DEPTH_TOLERANCE_M = 1e-6


class CandidateFootprint(BaseModel):
    """
    Where a candidate sits in grid coordinates, or why it cannot be placed.

    `placeable=False` is a real answer and the viewer must render it as one --
    listing the candidate, saying it cannot be located on this grid, and giving
    the reason. Silently dropping it would hide a staleness problem; guessing a
    position would manufacture one.
    """
    candidate_id: str
    placeable: bool
    reason: str = ""
    first_column: Optional[int] = None
    last_column: Optional[int] = None
    first_row: Optional[int] = None
    last_row: Optional[int] = None
    peak_column: Optional[int] = None
    peak_row: Optional[int] = None

    @property
    def n_columns(self) -> int:
        if self.first_column is None or self.last_column is None:
            return 0
        return self.last_column - self.first_column + 1

    @property
    def n_rows(self) -> int:
        if self.first_row is None or self.last_row is None:
            return 0
        return self.last_row - self.first_row + 1


def _row_for_depth(depths: Sequence[float], value: float) -> Optional[int]:
    """Exact index of `value` in a sorted depth list, within tolerance."""
    if not depths:
        return None
    i = bisect_left(depths, value - DEPTH_TOLERANCE_M)
    if i < len(depths) and abs(depths[i] - value) <= DEPTH_TOLERANCE_M:
        return i
    if i > 0 and abs(depths[i - 1] - value) <= DEPTH_TOLERANCE_M:
        return i - 1
    return None


def map_candidate(candidate: dict,
                  trace_indices: Sequence[int],
                  depths: Sequence[float]) -> CandidateFootprint:
    """
    Place one candidate on one grid, exactly or not at all.

    `candidate` is the serialised `AnomalyCandidate` -- taken as a dict so this
    stays usable from the route layer without importing the detector, and so a
    stored candidate that predates a model change fails as unplaceable rather
    than raising.
    """
    evidence = (candidate or {}).get("evidence") or {}
    candidate_id = (candidate or {}).get("id") or ""

    trace_range = evidence.get("trace_range")
    depth_range = evidence.get("depth_range")
    if not trace_range or not depth_range or len(trace_range) < 2 or len(depth_range) < 2:
        return CandidateFootprint(
            candidate_id=candidate_id, placeable=False,
            reason="the candidate carries no trace or depth range to place it by")

    by_trace = {int(t): i for i, t in enumerate(trace_indices)}
    first_col = by_trace.get(int(trace_range[0]))
    last_col = by_trace.get(int(trace_range[1]))
    if first_col is None or last_col is None:
        return CandidateFootprint(
            candidate_id=candidate_id, placeable=False,
            reason=(f"traces {trace_range[0]}-{trace_range[1]} are not in this "
                    f"grid, which holds {trace_indices[0] if trace_indices else 'none'}"
                    f"-{trace_indices[-1] if trace_indices else 'none'}; the "
                    f"candidate was generated from different records"))

    sorted_depths = list(depths)
    first_row = _row_for_depth(sorted_depths, float(depth_range[0]))
    last_row = _row_for_depth(sorted_depths, float(depth_range[1]))
    if first_row is None or last_row is None:
        return CandidateFootprint(
            candidate_id=candidate_id, placeable=False,
            reason=(f"depths {depth_range[0]}-{depth_range[1]} m do not appear "
                    f"in this grid's depth axis; the candidate was generated "
                    f"under a different depth conversion"))

    peak_col = by_trace.get(int(evidence.get("peak_trace", trace_range[0])))
    peak_row = _row_for_depth(sorted_depths, float(evidence.get("peak_depth",
                                                                depth_range[0])))

    return CandidateFootprint(
        candidate_id=candidate_id, placeable=True,
        first_column=min(first_col, last_col), last_column=max(first_col, last_col),
        first_row=min(first_row, last_row), last_row=max(first_row, last_row),
        peak_column=peak_col, peak_row=peak_row)


def map_candidates(candidates: Sequence[dict],
                   trace_indices: Sequence[int],
                   depths: Sequence[float]) -> list[CandidateFootprint]:
    return [map_candidate(c, trace_indices, depths) for c in candidates]


class RadargramSemantics(BaseModel):
    """Everything the viewer needs in order to label a grid honestly."""
    vertical: VerticalAxis
    horizontal: HorizontalAxis
    field: FieldSemantics
    #: Cells whose ring had too few neighbours for a trustworthy statistic.
    #: An unreliable cell is NOT a cell with no anomaly.
    unreliable_cells: Optional[int] = None
    total_cells: Optional[int] = None
    reliability_note: str = (
        "an unreliable cell is one whose local background could not be estimated "
        "from enough neighbours -- usually at a grid edge. It is not a cell where "
        "nothing was found, and it is not zero."
    )
    missing_note: str = (
        "a missing cell is a sample the acquisition did not record. It is drawn "
        "as a gap, never as zero signal."
    )
