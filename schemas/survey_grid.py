"""
A GRIDDED ACQUISITION: a dense survey whose traces sit on a regular
(trace along line) x (line) lattice, stored as one array rather than as one
`SubterraRecord` per sample.

WHY A SEPARATE SHAPE. A BAM-style grid is 401 traces x 161 lines x 512
samples = 33 million samples. As newline-delimited `SubterraRecord`s that is
tens of gigabytes of pydantic objects, so the record store cannot hold it.
The array is the measurement; this schema is everything needed to say WHERE
each element of it was measured, and on what authority.

WHAT A GRID MUST STATE, OR IT IS NOT A GRID. A metric 3D volume needs:
  * line identities and their order            -> `line_axis`
  * the along-line trace spacing               -> `trace_axis.step`
  * the line-to-line spacing                   -> `line_axis.step`
  * the direction the lines run                -> `traversal`
  * the time axis                              -> `time_axis`
Each spacing carries its own provenance. A spacing nobody stated is never
filled in: `GridAxis.step` is required, and a caller without one must not
construct a grid (see `reconstruction.volume.preview`, which refuses).

The grid's frame is ONE `SurveyFrame` (the frame docstring already lists "a
magnetometer grid" as an acquisition unit). Declarations -- a depth
calibration, a CRS, an affine tie -- attach to that frame exactly as they
would to a single line.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class AxisProvenance(str, Enum):
    #: The values are stored in the source files themselves (e.g. X-values.npy).
    SOURCE_FILE = "source_file"
    #: Stated in the publisher's or operator's documentation, not in a file.
    DOCUMENTATION = "documentation"
    #: Declared by a user through Subterra.
    USER_DECLARED = "user_declared"


class GridAxis(BaseModel):
    """One regular axis of a grid: n positions, origin, step, unit, and why we believe them."""
    name: str
    n: int = Field(..., ge=1)
    origin: float
    step: float = Field(..., gt=0)
    unit: str
    provenance: AxisProvenance
    #: Where the numbers come from, in words. Required: an axis with no stated
    #: source is exactly the kind of number this platform does not invent.
    source: str = Field(..., min_length=1)
    #: Provenance of the UNIT, separately -- a file can store numbers without
    #: saying what they measure (BAM's .npy grids carry no unit; mm comes from
    #: the Dataverse description).
    unit_provenance: AxisProvenance = AxisProvenance.DOCUMENTATION

    def position(self, i: float) -> float:
        return self.origin + i * self.step

    def values(self):
        import numpy as np
        return self.origin + np.arange(self.n) * self.step

    def metres_per_unit(self) -> Optional[float]:
        return {"m": 1.0, "mm": 1e-3, "cm": 1e-2}.get(self.unit)


class Traversal(str, Enum):
    #: Each line is a traverse along the trace axis at a fixed line coordinate.
    LINES_ALONG_TRACE_AXIS = "lines_along_trace_axis"


class GriddedAcquisition(BaseModel):
    """The geometry and identity of one gridded acquisition's stored array."""
    dataset_id: str
    frame_id: str
    #: Along-line axis (x): trace index i -> position.
    trace_axis: GridAxis
    #: Across-line axis (y): line index j -> position. Line ORDER is this axis's
    #: order; line IDENTITY is its index.
    line_axis: GridAxis
    #: Two-way travel time (ns), sample k -> time. Raw instrument time: no
    #: time-zero correction is applied to the stored array.
    time_axis: GridAxis
    traversal: Traversal = Traversal.LINES_ALONG_TRACE_AXIS
    #: Stored array: shape (trace_axis.n, line_axis.n, time_axis.n), float32.
    array_file: str
    array_sha256: str
    dtype: str = "float32"
    #: Lines (by index) that exist in the grid but carry no measurement. A
    #: missing line is never interpolated over at storage time.
    missing_lines: list[int] = Field(default_factory=list)
    #: How the amplitudes relate to the source, verbatim (e.g. the amplitude
    #: preservation finding). Carried, never upgraded.
    amplitude_note: str = ""
    source: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _time_axis_is_time(self):
        if self.time_axis.unit != "ns":
            raise ValueError("the stored time axis must be two-way travel time in ns")
        return self

    @property
    def shape(self) -> tuple[int, int, int]:
        return (self.trace_axis.n, self.line_axis.n, self.time_axis.n)
