"""
Types for the Learned Detector V1 investigation: a per-pixel/per-sample
anomaly-SEGMENTATION training example, and the label-provenance vocabulary
that keeps a real measurement, a transcribed publication value, an
operator's review and a synthetic fabrication from ever being collapsed
into one undifferentiated "label".

WHY THIS IS A SEPARATE MODULE FROM `schemas.provenance`. `ProvenanceClass`
already answers "how much does the data vouch for this VALUE" for a
quantity Subterra reports. A segmentation label answers a narrower,
different question: "how precisely is this mask SPATIALLY located, and by
what mechanism". The two axes are not the same and are not collapsed here
-- `LabelSource` below is deliberately a smaller, purpose-built vocabulary
(the four kinds the milestone brief itself names: independently measured,
author-provided, operator-reviewed, synthetic), and a `GPRTrainingExample`
is free to also carry a real `ProvenanceClass` inside its `basis` text
where that helps a reader, without the two enums pretending to be one.

THE AUDIT THIS MODULE'S OWN DOCSTRING RECORDS (see
`training/segmentation.py` for the full account): as of this milestone,
real trace-associated GPR anomaly evidence exists in exactly ONE place in
the held corpus -- BAM specimen Pk266, 4 targets, all Level B (a real,
code-verified X-axis trace footprint) with a DERIVED (not published) time-
axis pick available only where `bam_hyperbola_velocity_audit`'s own
confidence gate is cleared. Every other held dataset (4TU, TU1208, TestUM,
Grimsel) is Level D or unheld. `LabelLevel` exists so that fact is a typed,
checkable property of every example this module can produce, not a claim
buried in a docstring that could quietly go stale.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class LabelLevel(str, Enum):
    """
    How precisely a label is spatially associated with the signal, per the
    Learned Detector V1 brief's own rubric. Never promoted upward by this
    module or any of its callers -- a caller that wants to know whether an
    example is trustworthy enough to train on reads this field, not the
    example's mere presence in the dataset.
    """
    #: Pixel/sample-level mask, or a sufficiently precise physical/radar
    #: association that can deterministically produce one.
    A_MASK = "pixel_or_sample_mask"
    #: Bounding box / trace span / precise event region, no finer mask.
    B_REGION = "bounding_box_or_trace_span"
    #: Target depth or approximate position only, no trace association.
    C_POSITION = "depth_or_position_only"
    #: Existence only -- no trace association of any kind.
    D_EXISTENCE = "existence_only_no_association"


#: States that MAY be used to train a segmentation model at all. C and D
#: cannot produce a mask by construction (see `LabelLevel`'s own docstring)
#: -- kept here as the one place that boundary is enforced in code, not
#: re-derived ad hoc by every caller.
TRAINABLE_LABEL_LEVELS = (LabelLevel.A_MASK, LabelLevel.B_REGION)


class LabelSource(str, Enum):
    """
    The FOUR KINDS the milestone brief names, never collapsed into one.
    Distinct from `LabelLevel` (precision) and from
    `schemas.provenance.ProvenanceClass` (general value provenance) -- see
    this module's own docstring for why all three stay separate.
    """
    #: A real measurement Subterra itself derived from real signal data
    #: (e.g. a confidence-gated arrival-time pick against a real trace).
    #: NOT the same as an author's published number -- see PUBLISHED_TRUTH.
    MEASURED_ASSOCIATION = "measured_association"
    #: A number transcribed from a publication or data repository by a
    #: human, attributed to its source, never Subterra's own measurement.
    PUBLISHED_TRUTH = "published_truth"
    #: A person reviewed and confirmed or edited a candidate region.
    OPERATOR_REVIEWED = "operator_reviewed"
    #: Fabricated/simulated. Never real. See `training/synthetic_gpr.py`'s
    #: own disclaimer, which this value exists to make impossible to drop.
    SYNTHETIC = "synthetic"


class MaskRegion(BaseModel):
    """
    A segmentation target's positive region, in the SAME (trace, sample)
    index space `preprocessing.spatial_grid.build_trace_depth_grid_for_records`
    already uses for a real B-scan grid -- no separate coordinate system is
    invented.

    `trace_indices`/`sample_indices` are PARALLEL arrays: cell i is
    `(trace_indices[i], sample_indices[i])`. This is deliberately a sparse
    point list, not a dense boolean array -- seehow `training/segmentation.py`
    builds one from `bam_hyperbola_velocity_audit`'s real arrival picks: ONE
    sample per traced arrival, never an invented width around it (see that
    module's own docstring for why a wider mask is not built without
    evidence to size it).
    """
    trace_indices: list[int]
    sample_indices: list[int]
    #: What produced this exact region -- e.g. "real X-axis footprint
    #: (benchmark.bam_truth.build_footprint) intersected with a real
    #: per-trace arrival-time pick (bam_hyperbola_velocity_audit.associate_
    #: target), one sample per traced arrival, no invented width".
    rule: str = Field(..., min_length=1)

    @property
    def n_cells(self) -> int:
        return len(self.trace_indices)


class GPRTrainingExample(BaseModel):
    """
    One training/evaluation example: a real GPR window and (if any) its
    label, with full provenance. Mirrors the milestone brief's own
    `GPRTrainingExample` sketch; every field below is either populated from
    something Subterra actually holds or explicitly left `None` -- nothing
    here is a placeholder invented to fill the shape.
    """
    dataset_id: str
    site_id: str
    survey_id: str
    source_file: str
    #: (first, last) trace index, inclusive, that this example's window covers.
    trace_range: tuple[int, int]
    #: (first, last) sample index, inclusive.
    sample_range: tuple[int, int]

    #: Real amplitude values, shape (n_samples, n_traces) -- see
    #: `training/segmentation.py`'s own docstring for which processing
    #: stage feeds this and why.
    signal: list[list[float]]

    #: None means genuinely unlabelled (e.g. a real BAM window outside any
    #: target's footprint, or any window from a Level-C/D dataset) --
    #: distinct from an empty `MaskRegion`, which would claim "labelled,
    #: and the label is empty".
    mask: Optional[MaskRegion] = None
    label_level: LabelLevel
    label_source: Optional[LabelSource] = None
    #: Free text: exactly which real fact(s) this label rests on, and their
    #: own source. Required whenever a mask is present -- mirrors
    #: `QuantityProvenance.basis`'s own non-empty requirement.
    label_basis: Optional[str] = None

    sensor_vendor: Optional[str] = None
    antenna_frequency_mhz: Optional[float] = None
    sample_interval_ns: Optional[float] = None
    preprocessing_version: str
    #: Assigned by `training.segmentation.split_by_site`, never by hand --
    #: see that function for why a trace-level random split is refused.
    split: Optional[str] = None

    extra: dict[str, Any] = Field(default_factory=dict)


class ModelArtifactProvenance(BaseModel):
    """
    What must be recorded before a trained model file is allowed to become
    evidence, per the milestone brief's own list. Constructed once, never
    partially -- a caller that cannot supply every field has not finished
    training a claimable artifact.
    """
    #: `model_checksum_sha256` below is a real field name, not an internal
    #: one -- silences pydantic's "model_" protected-namespace warning.
    model_config = ConfigDict(protected_namespaces=())

    architecture: str
    parameter_count: int
    training_commit: str
    training_dataset_ids: list[str]
    validation_dataset_ids: list[str]
    test_dataset_ids: list[str]
    preprocessing_version: str
    training_config: dict[str, Any]
    seed: int
    metrics: dict[str, float]
    model_checksum_sha256: str
    trained_utc: str
    label_provenance_summary: str = Field(..., min_length=1)
    #: Never omitted: what this artifact is NOT validated for, stated as
    #: plainly as what it is. Mirrors every synthetic-classifier disclaimer
    #: already in `api/routes/training.py`, generalised to this one field
    #: rather than left to whichever caller remembers to write one.
    validity_caveat: str = Field(..., min_length=1)
