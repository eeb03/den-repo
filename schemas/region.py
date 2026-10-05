"""
ResponseRegion: a spatially coherent reconstructed response inside a volume
that exceeds an explicitly defined, target-independent evidence criterion.

WHAT A REGION IS NOT. Not a pipe, void, cable, utility, mineral or object.
No field here can hold a class, and nothing in Interpretation V1 sets one.
A region says "a coherent reconstructed response exists here, with these
measurements and this support"; what it IS comes later, from classification
and from evidence this platform does not yet have.

EVIDENCE IS MODALITY-NEUTRAL. `evidence` is a list of `RegionEvidence`, one
per contributing field. V1 fills exactly one (GPR response envelope); a
future ERT conductivity, magnetic anomaly, seismic response, borehole
constraint or assay-backed composition field adds an entry with its own
modality, property, unit and method rather than a new schema.

REVIEW IS OPERATOR EVIDENCE. A review asks "is this a genuine subsurface
response worth retaining?" -- never "what is it?" -- and is evidence grade C
(operator reviewed), never ground truth.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

REGION_MEANING = (
    "A spatially coherent reconstructed response exceeding a stated, target-independent "
    "evidence criterion. Not an object, not a class, not a material.")


class RegionStatus(str, Enum):
    #: Supported by measured / reconstructed voxels.
    PROPOSED = "proposed"
    #: Kept, but less than half of its voxels are measured or reconstructed:
    #: shown, penalised, and labelled as such.
    LOW_SUPPORT = "low_support"


class RegionReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    #: A genuine subsurface response worth retaining. Says nothing about identity.
    CONFIRMED_RESPONSE = "confirmed_response"
    #: Clutter, artefact or not worth retaining.
    REJECTED_RESPONSE = "rejected_response"
    UNCERTAIN = "uncertain"


class Triple(BaseModel):
    x: float
    y: float
    z: float


class Bounds(BaseModel):
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float


class RegionSupport(BaseModel):
    measured_voxel_fraction: float
    reconstructed_voxel_fraction: float
    interpolated_voxel_fraction: float
    unsupported_voxel_fraction: float
    nearest_measurement_distance_m: dict[str, float]
    peak_support_class: str


class RegionShape(BaseModel):
    #: Eigenvalues (descending) of the response-weighted coordinate
    #: covariance in physical units, and their unit vectors (x, y, z).
    pca_eigenvalues: list[float]
    pca_axes: list[list[float]]
    #: sqrt(l1 / l2): 1 = round in its main plane, large = elongated.
    elongation: float
    #: sqrt(l2 / l3).
    flatness: float
    #: voxels / bounding-box voxels.
    compactness: float
    #: Principal axis azimuth in the x-y plane (degrees from +x, 0..180) and
    #: dip below horizontal (degrees). Only meaningful when z is in metres.
    azimuth_deg: Optional[float] = None
    dip_deg: Optional[float] = None


class RegionEvidence(BaseModel):
    """One field's contribution. V1: one GPR entry."""
    modality: str                     # "gpr"
    property_name: str                # "response_envelope"
    unit: str
    method: str
    peak_value: float
    peak_robust_z: float
    peak_local_contrast: float
    integrated_response: float
    mean_response: float


class ScoreComponents(BaseModel):
    """All in [0, 1]. Strength/quality of the RECONSTRUCTED RESPONSE, not a probability of anything."""
    response_strength: float
    local_contrast: float
    persistence_3d: float
    support_quality: float
    compactness: float
    interpolation_penalty: float
    boundary_penalty: float


class ResponseRegion(BaseModel):
    id: str
    region_set_id: str
    volume_id: str
    dataset_id: str
    coordinate_frame: str             # the volume's: local_volume | georeferenced_volume
    z_domain: str                     # depth | two_way_time
    z_unit: str                       # m | ns -- a time-domain region is never described in metres
    status: RegionStatus
    voxel_count: int
    centroid: Triple                  # response-weighted
    peak_location: Triple
    peak_index: tuple[int, int, int]
    bounds: Bounds
    index_bounds: tuple[int, int, int, int, int, int]   # i0, i1, j0, j1, k0, k1 (inclusive)
    physical_extent: Triple           # length_x, length_y (m), length_z (m or ns)
    fwhm: Triple                      # through the peak, contiguous run >= half peak
    lines_spanned: int
    support: RegionSupport
    shape: RegionShape
    evidence: list[RegionEvidence]
    score_components: ScoreComponents
    evidence_score: float
    merged_from: list[int] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    #: Compact mask: bit-packed (np.packbits, C order) over `index_bounds`.
    mask_b64: str
    meaning: str = REGION_MEANING


class RegionConfig(BaseModel):
    """The proposal rule. Every number is documented in docs/volume-interpretation.md."""
    field: str = "response_envelope"
    seed_robust_z: float = 8.0
    grow_robust_z: float = 4.0
    seed_local_contrast: float = 3.0
    #: Growth also needs this much local lateral contrast: a laterally continuous
    #: layer (direct wave, back wall, flat interface) fills its own lateral window,
    #: so its contrast is ~1 and it does not become (or connect) regions.
    grow_local_contrast: float = 1.5
    use_local_contrast: bool = True
    local_window_m: float = 0.20
    connectivity: int = 6             # 6 | 18 | 26
    min_voxels: int = 40
    closing: bool = False             # optional 1-voxel binary closing (morphology)
    merge_stacked_lobes: bool = True
    merge_max_gap_m: float = 0.04     # depth volumes; time volumes use merge_max_gap_ns
    merge_max_gap_ns: float = 0.6
    merge_min_footprint_overlap: float = 0.5
    min_supported_fraction: float = 0.5
    refuse_interpolation_only: bool = True
    max_volume_unsupported_fraction: float = 0.5
    max_volume_interpolated_fraction: float = 0.5


class RegionSet(BaseModel):
    id: str
    volume_id: str
    dataset_id: str
    algorithm: str
    algorithm_version: str
    threshold_method: str
    config: RegionConfig
    source_volume_fingerprint: str
    source_volume_components: dict[str, str]
    z_domain: str
    z_unit: str
    migrated: bool
    created_at: datetime
    created_by: Optional[str] = None
    regions: list[ResponseRegion]
    rejected: dict[str, int]
    merges: list[dict[str, Any]] = Field(default_factory=list)
    background: dict[str, Any] = Field(default_factory=dict)
    performance: dict[str, Any] = Field(default_factory=dict)
    meaning: str = REGION_MEANING


class RegionReview(BaseModel):
    """One append-only review event. The current state is the latest event."""
    region_id: str
    region_set_id: str
    volume_id: str
    dataset_id: str
    status: RegionReviewStatus
    reviewer_id: str
    notes: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evidence_grade: str = "C_operator_reviewed"
    ground_truth_status: str = "not_independently_validated"
    #: Snapshot of what the reviewer saw, frozen with the judgement.
    region_snapshot: dict[str, Any] = Field(default_factory=dict)
