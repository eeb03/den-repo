"""
VolumeProduct: a reconstructed scalar field on a regular 3D grid, with every
claim about it stated.

WHAT A VOLUME IS. "What scalar field has been reconstructed, from which
measurements, by which explicit process, and how well is each voxel
supported?" -- a different question from the reconstructed SCENE
(`schemas.scene`), which asks "what individually placeable evidence do we
have?" and deliberately never fills space between measurements. The two are
separate products and neither is built from the other.

WHAT A VOLUME IS NOT. Not a detection, not an interpretation, not a material
property. The V1 GPR field is a (migrated) radar response in the
instrument's arbitrary amplitude units. It is never called density,
material, probability or composition: those need a model this platform does
not have, and a future field carrying one must name its method and evidence
(`PropertyField`).

COORDINATES. A LOCAL volume needs no Earth reference: x and y are survey
metres in the acquisition's own frame, z is depth below a declared /
calibrated surface (or two-way time). A GEOREFERENCED volume additionally
carries a registration to the Earth -- only when the frame's existing
registration gates allow it -- and never invents one.

MULTIMODAL BY CONSTRUCTION. Nothing here is GPR-specific except the values a
GPR reconstruction puts in it: `PropertyField` carries property name, unit,
uncertainty, method and evidence sources, so resistivity (ERT), velocity
(seismic) or an assay-constrained composition field can occupy the same
grid later -- each traceable to the sensor that actually measured it.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum, IntEnum
from typing import Any, Optional

from pydantic import BaseModel, Field

VALIDATION_STATUS = (
    "A reconstructed image, not a validated detection or interpretation. Each voxel "
    "states how it is supported; nothing in this volume identifies an object or a "
    "material.")

WHAT_IT_IS_NOT = (
    "Not density, material, moisture, probability or mineral content. The V1 GPR field "
    "is radar response in arbitrary instrument amplitude units, optionally migrated "
    "(focused) with a stated velocity.")


class ZDomain(str, Enum):
    #: Metres below the declared/calibrated surface. Requires a scientifically
    #: sufficient depth model.
    DEPTH = "depth"
    #: Two-way travel time in ns. Never relabelled as depth.
    TWO_WAY_TIME = "two_way_time"


class CoordinateFrameKind(str, Enum):
    LOCAL = "local_volume"
    GEOREFERENCED = "georeferenced_volume"


class SupportClass(IntEnum):
    """How a voxel's value came to exist. Stored as uint8 per voxel."""
    #: No measurement close enough: the value is NaN, never filled.
    UNSUPPORTED = 0
    #: Interpolated between measured lines within the stated maximum distance.
    INTERPOLATED = 1
    #: At a measured (x, y) position, but computed from many traces (migration).
    RECONSTRUCTED = 2
    #: At a measured (x, y) position and a measured sample (a sub-sample
    #: time-zero shift by linear interpolation is the only operation).
    MEASURED = 3


SUPPORT_CLASS_MEANING = {
    SupportClass.UNSUPPORTED: "no measurement within the stated distance; value is empty, not filled",
    SupportClass.INTERPOLATED: "interpolated between measured lines within the stated maximum distance",
    SupportClass.RECONSTRUCTED: "at a measured trace position; value computed from many traces by migration",
    SupportClass.MEASURED: "at a measured trace position and sample (sub-sample time-zero shift only)",
}


class VolumeAxis(BaseModel):
    name: str
    n: int
    origin: float
    step: float
    unit: str
    description: str

    def values(self):
        import numpy as np
        return self.origin + np.arange(self.n) * self.step

    def index_of(self, value: float) -> int:
        return int(round((value - self.origin) / self.step))


class HorizontalRegistration(BaseModel):
    """lat = a*x + b*y + e ; lon = c*x + d*y + f, with x, y the VOLUME's metres."""
    method: str
    a: float
    b: float
    e: float
    c: float
    d: float
    f: float
    source: str
    verified: bool = False
    rms_residual_m: Optional[float] = None


class VolumeCoordinateFrame(BaseModel):
    kind: CoordinateFrameKind
    description: str
    x_meaning: str
    y_meaning: str
    z_meaning: str
    #: What z = 0 is, in words, with its authority.
    z_origin: str
    horizontal_registration: Optional[HorizontalRegistration] = None
    #: Absolute elevation is a separate claim from horizontal placement.
    absolute_elevation: bool = False
    #: Why the frame is local / why elevation is not absolute.
    notes: list[str] = Field(default_factory=list)


class PropertyField(BaseModel):
    """One scalar field on the volume grid. Future modalities add fields, not schemas."""
    property_name: str
    unit: str
    value_kind: str                       # "measured" | "derived" | "reconstructed" | "estimated"
    description: str
    method: str
    uncertainty: Optional[str] = None
    evidence_sources: list[str] = Field(default_factory=list)
    support_field: str = "support_class"
    file: str
    dtype: str = "float32"
    #: Robust statistics of finite values, for display defaults only.
    stats: dict[str, float] = Field(default_factory=dict)


class ProcessingStep(BaseModel):
    name: str
    applied: bool
    parameters: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


class MigrationSpec(BaseModel):
    method: str                          # "none" | "stolt_fk_3d"
    velocity_m_per_ns: Optional[float] = None
    velocity_source: Optional[str] = None
    time_zero_ns: Optional[float] = None
    time_zero_source: Optional[str] = None
    assumptions: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class InterpolationSpec(BaseModel):
    mode: str                            # "nearest_no_fill" | "linear_bounded"
    output_line_spacing_m: float
    max_gap_m: float
    max_gap_rule: str


class VolumeConfig(BaseModel):
    """What the user asks for. Every field has a stated, conservative default."""
    frame_id: Optional[str] = None
    #: "auto": depth when the depth model is scientifically sufficient, else refuse
    #: depth and offer time. "depth" / "time" are explicit requests.
    z_domain: str = "auto"
    migration: str = "none"              # "none" | "stolt_fk_3d"
    interpolation: str = "nearest_no_fill"
    #: Output line spacing in metres; None = the measured line spacing.
    output_line_spacing_m: Optional[float] = None
    #: Interpolate across a line gap only when it is at most this many measured
    #: line spacings wide (1.0 = adjacent measured lines only).
    max_gap_line_spacings: float = 2.0
    dewow: bool = True
    background_removal: str = "none"     # "none" | "line_mean"
    #: Stolt zero padding, traces each side in x and y.
    migration_padding: int = 32


class VolumeStatus(str, Enum):
    CURRENT = "current"
    STALE = "stale"


class VolumeProduct(BaseModel):
    id: str
    dataset_id: str
    source_dataset_ids: list[str]
    frame_ids: list[str]
    modality: str = "gpr"
    coordinate_frame: VolumeCoordinateFrame
    x_axis: VolumeAxis
    y_axis: VolumeAxis
    z_axis: VolumeAxis
    z_domain: ZDomain
    shape: tuple[int, int, int]
    voxel_spacing: tuple[float, float, float]
    fields: list[PropertyField]
    primary_field: str
    #: uint8 SupportClass per voxel, plus per-(x, y)-column companions.
    support_file: str
    distance_file: str                   # nearest measured trace distance (m), per column
    count_file: str                      # measured traces within one native spacing, per column
    support_summary: dict[str, int] = Field(default_factory=dict)
    reconstruction_method: str
    processing: list[ProcessingStep]
    migration: MigrationSpec
    interpolation: InterpolationSpec
    calibration_provenance: dict[str, Any] = Field(default_factory=dict)
    config: VolumeConfig
    created_at: datetime
    created_by: Optional[str] = None
    source_fingerprint: str
    #: The components of the fingerprint, so staleness can say WHICH input changed.
    input_components: dict[str, str] = Field(default_factory=dict)
    status: VolumeStatus = VolumeStatus.CURRENT
    validation_status: str = VALIDATION_STATUS
    what_it_is_not: str = WHAT_IT_IS_NOT
    performance: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
