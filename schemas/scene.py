"""
The reconstructed-scene payload: what a 3D renderer needs to draw an
elevation-anchored underground scene, assembled from what the platform
already knows about one dataset -- never inventing a position or an
elevation it has no evidence for.

THE DISTINCTION THIS MODULE EXISTS TO PROTECT. Three different claims, and
collapsing them is exactly how a fabricated Z coordinate is born:

    DECLARED    an operator supplied a value (a vertical datum, an
                axis-origin offset) through the existing spatial-declaration
                workflow
    DERIVED     Subterra computed a value FROM declared/measured inputs --
                `compute_absolute_elevation` below is the only place that
                happens, and it is pure arithmetic on values this module
                did not choose
    VALIDATED   independent external evidence (a survey, an excavation)
                confirms a physical position -- 4TU/TU1208/Grimsel remain
                the external tracks for this, and nothing here touches them

A resolved scene may use DECLARED and DERIVED values. It must never present
either as VALIDATED. `VALIDATION_STATUS` says so in every payload this
module produces, resolved or not, so a consumer never has to infer it or
read source code to find it.

WHAT THIS MODULE DOES NOT DO. It does not decide whether a scene CAN be
shown -- `schemas.views._scene_3d` and `fusion.vertical_reference.assess`
already decide that, and this module reads their answer rather than
re-deriving it. It does not generate candidates -- `interpretation.
anomaly_candidates` and `api.candidates` already do, and this module reads
the stored set. It does not add a velocity, a datum, or an offset that
nobody declared.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from interpretation.candidate_intelligence import DepthCertainty, LocalisationCertainty
from schemas.spatial import DepthOriginOffset, VerticalRelationshipKind

#: Carried on every payload, resolved or not, so a client never has to infer
#: the epistemic status of what it is about to render.
VALIDATION_STATUS = (
    "Positions and elevations in this scene are declared or derived from "
    "declared inputs. None of them is independently validated against "
    "physical ground truth."
)

#: A surface frame can hold hundreds of thousands of points; a renderer
#: needs a scene, not a dataset dump. This bounds what one payload carries.
#: Raw, full-resolution data remains available through the existing
#: diagnostic views (the embedded point-cloud/heatmap viewer, the report).
MAX_SURFACE_POINTS = 2000

#: Same reasoning as MAX_SURFACE_POINTS, for the same reason: a dataset can
#: carry far more above-threshold measurements than a scene should embed in
#: one response. Downsampling is an even stride over the already-qualifying
#: set (same technique `_surface_points` already uses) -- it never changes
#: which measurements qualify as evidence.
MAX_EVIDENCE_SAMPLES = 2000


class ScenePosition(BaseModel):
    """
    Where a scene object sits horizontally, or exactly why it does not.

    Reuses `LocalisationCertainty` (`interpretation.candidate_intelligence`)
    rather than inventing a second position-quality vocabulary -- a
    candidate's horizontal position is either spatially registered,
    frame-relative, trace-relative or unknown regardless of which surface
    consumes it.
    """
    available: bool
    lat: Optional[float] = None
    lon: Optional[float] = None
    basis: LocalisationCertainty
    reason: str


class SceneElevation(BaseModel):
    """
    An object's vertical position in the scene, or exactly why it does not
    have one.

    `elevation_m` is populated only when `available` is True, and is always
    DERIVED: computed by `compute_absolute_elevation` from a surface
    elevation this payload also carries, a depth this payload also carries,
    and (when declared) an axis-origin offset. It is never a second,
    unaccountable number.
    """
    available: bool
    elevation_m: Optional[float] = None
    depth_m: Optional[float] = None
    depth_certainty: DepthCertainty
    provenance: str
    reason: str


class SceneSurfacePoint(BaseModel):
    lat: float
    lon: float
    elevation_m: float


class SceneSurface(BaseModel):
    """The declared surface (DEM/LiDAR) a scene draws the ground from."""
    frame_id: str
    dataset_id: str
    modality: str
    vertical_datum_code: Optional[str] = None
    vertical_datum_provenance: Optional[str] = None
    points: list[SceneSurfacePoint] = Field(default_factory=list)
    point_count_total: int = 0
    downsampled: bool = False


class SceneCandidate(BaseModel):
    """
    One anomaly candidate placed in the scene, or explicitly not placed.

    Carries the same `id` and evidence pointers as the existing candidate
    API (`AnomalyCandidate`/`InspectableCandidate`) rather than minting a
    parallel identity -- a client can always follow `evidence_reference`
    back to the same radargram/report view already shipped.
    """
    id: str
    position: ScenePosition
    elevation: SceneElevation
    score: float
    score_meaning: str
    anomaly_class: str
    note: str
    source_file: str
    trace_range: tuple[int, int]
    depth_range: tuple[float, float]
    evidence_reference: str


class SceneEvidenceSample(BaseModel):
    """
    One individual measurement whose processed signal exceeded the same
    anomaly-evidence threshold candidate generation uses -- placed
    individually, never grouped, never connected to a neighbour. This is
    NOT a candidate and NOT a structure: it carries no shape, no class, no
    claim beyond "this one measurement's value was this strong, here".

    `position`/`elevation` reuse the exact same types `SceneCandidate`
    already uses, for the same reason a candidate does: an evidence sample
    that lacks a real position is never placed here (the caller building
    this list excludes it and counts it in
    `SceneEvidenceField.excluded_unpositioned_count` instead of guessing).
    """
    source_file: str
    trace_index: int
    depth_m: float
    evidence_value: float
    reliable: bool
    position: ScenePosition
    elevation: SceneElevation
    evidence_reference: str


class SceneEvidenceField(BaseModel):
    """
    Every spatially-registered evidence sample above threshold for this
    scene, or the reason there are none.

    Deliberately sparse where the underlying measurements are sparse: no
    interpolation, no fabricated coverage between samples, no mesh. A short
    `samples` list is a correct, successful result -- not a partial one.
    """
    samples: list[SceneEvidenceSample] = Field(default_factory=list)
    threshold: float
    point_count_total: int = 0
    downsampled: bool = False
    #: Measurements that exceeded the threshold but had no usable geographic
    #: position -- reported as a count (not individually: this can run into
    #: the thousands) rather than silently dropped.
    excluded_unpositioned_count: int = 0
    #: Populated only when `samples` is empty, explaining why: preprocessing
    #: never ran, nothing exceeded threshold, or nothing above threshold has
    #: a usable position. A user should never have to guess which.
    reason: Optional[str] = None


class SceneVerticalRelationship(BaseModel):
    """The same `VerticalRelationship` `fusion.vertical_reference.assess` already computes, carried verbatim."""
    kind: VerticalRelationshipKind
    subsurface_frame_id: Optional[str]
    surface_frame_id: Optional[str]
    reasons: list[str]
    missing: list[str]


class ScenePayload(BaseModel):
    """
    Everything a "Reconstructed scene" renderer needs for one dataset, or
    the reason it cannot be shown yet.

    `resolved` is `schemas.views._scene_3d`'s own answer -- this module adds
    no second opinion about whether a scene may be drawn.
    """
    dataset_id: str
    resolved: bool
    resolution_reason: Optional[str] = None
    missing: list[str] = Field(default_factory=list)
    vertical_relationship: Optional[SceneVerticalRelationship] = None
    surface: Optional[SceneSurface] = None
    candidates: list[SceneCandidate] = Field(default_factory=list)
    #: Stage A: individual measured/derived evidence samples, distinct from
    #: `candidates` (which are grouped, classified regions). `None` for an
    #: unresolved scene -- same gate as `surface`/`candidates`, no second
    #: opinion about whether a scene may be shown.
    evidence: Optional[SceneEvidenceField] = None
    validation_status: str = VALIDATION_STATUS
    #: Pointers to the existing diagnostic surfaces, so a client that shows
    #: this scene can still offer "inspect the raw data" without
    #: constructing those URLs itself.
    diagnostic_views: dict[str, str] = Field(default_factory=dict)


def compute_absolute_elevation(
    surface_elevation_m: float,
    depth_m: float,
    offset: Optional[DepthOriginOffset],
) -> float:
    """
    The one piece of arithmetic this whole module exists to perform
    correctly and nowhere else: `docs/depth-origin.md` names it directly
    ("Nothing performs that arithmetic yet") and pins the sign convention
    this function applies unmodified (`schemas.spatial.OFFSET_POSITIVE_MEANS`):
    positive offset means the reference point sits ABOVE the ground, so on a
    positive-down depth axis the ground itself sits at `+offset_m`, and a
    sample at depth `d` is `(d - offset_m)` below ground.

    `offset` is used only when it `relates_the_depth_axis` -- a phase-centre
    or housing offset answers a different question and is silently ignored
    here exactly as `fusion.vertical_reference.assess` already treats it
    (that function reports such an offset as insufficient, so this one
    never receives it as a `relates_the_depth_axis` offset for a dataset
    that hasn't cleared `assess` first).
    """
    offset_m = offset.offset_m if (offset is not None and offset.relates_the_depth_axis) else 0.0
    depth_below_ground = depth_m - offset_m
    return surface_elevation_m - depth_below_ground
