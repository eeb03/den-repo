"""
Types for Self-Supervised GPR Encoder V1: a real-GPR masked-reconstruction
pretraining window, its corpus-membership bookkeeping, and the artifact
provenance a trained encoder must carry.

WHY THIS IS A SEPARATE MODULE FROM `schemas.segmentation`. `GPRTrainingExample`
is a LABELLED-example schema: `label_level` is a required field, and the whole
type exists to carry a mask and its evidence chain. An SSL window has, by
design, no label at all -- forcing it through that schema would mean inventing
a `label_level` value for "not applicable to this milestone", which is not
what that enum means (see `schemas.segmentation.LabelLevel`'s own docstring:
it grades how PRECISELY a label is associated, not whether one exists). The
conventions ARE reused deliberately: the same `dataset_id`/`site_id`/
`survey_id`/`source_file`/`trace_range`/`sample_range` naming, the same
`license`/`commercial_use_permitted` fields, the same `preprocessing_version`
discipline, and the same "split assigned by a function, never by hand" rule
(`training.ssl_corpus.assign_split`, mirroring `training.segmentation.split_by_site`).

WHY THE WINDOW REF DOES NOT CARRY THE SIGNAL ARRAY. `SSLWindowRef` is an
INDEX entry -- where a window comes from, not the window itself -- mirroring
`training.segmentation.annotation_record`'s own choice to exclude the (large)
signal array from a portable listing. A corpus of thousands of windows must
stay cheap to build, validate and list; the actual amplitude array is
materialised on demand by `training.ssl_corpus.read_window`, from the real
file, every time -- never cached as a second copy of the data inside this
schema.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class LicensePool(str, Enum):
    """
    Which pool a real source file's licence places it in. Two pools are kept
    SEPARATE and never silently combined (the milestone brief's own Section
    2 rule) -- a caller building the primary, commercially-deployable V1
    corpus filters to `COMMERCIAL_COMPATIBLE` explicitly; one building the
    research-only corpus makes that choice explicitly too.
    """
    #: The source licence permits commercial model training without asking
    #: (e.g. CC0-1.0, CC-BY-4.0). Eligible for the primary V1 encoder.
    COMMERCIAL_COMPATIBLE = "commercial_compatible"
    #: The source licence restricts commercial use (e.g. "In Copyright --
    #: Non-Commercial Use Permitted"), or has not been read/verified at all.
    #: Never silently promoted -- an unverified licence is RESEARCH_ONLY,
    #: not "probably fine".
    RESEARCH_ONLY = "research_only"


class SiteSplit(str, Enum):
    """
    Section 3's three-way corpus role, assigned by `training.ssl_corpus`'s
    own deterministic site table -- never by hand, never inferred from a
    file's position in a directory listing.
    """
    #: Used for SSL gradient updates.
    TRAIN = "train"
    #: Held out of SSL gradient updates, used only to monitor masked
    #: reconstruction loss during pretraining. Section 3's own distinction:
    #: for a site NOT ALSO in `RESERVED`, this is "unseen acquisition,
    #: possibly the same site as training" when the site also contributes
    #: training windows from other files, or genuine unseen-site validation
    #: when the whole site is held to this role -- `SSLSiteEntry.exposure`
    #: states which, per site, rather than leaving it implicit.
    VALIDATION = "validation"
    #: NEVER touched by SSL training or validation of any kind. Reserved
    #: for a future Detector V1 "completely unseen site" claim -- exposing
    #: this data to SSL pretraining at all (even unlabelled) would already
    #: weaken that specific claim, per the brief's own Section 3 warning.
    RESERVED = "reserved"


class SiteExposure(str, Enum):
    """
    Section 3's required distinction, stated per site rather than left to
    prose: what a future evaluation on this site's data may honestly claim.
    """
    #: The site contributed no data to SSL training or validation at all.
    UNSEEN_SITE = "unseen_site"
    #: The site's SIGNAL was seen during SSL (train or validation), but no
    #: TARGET LABEL was ever used (SSL never uses labels for anything) --
    #: a future supervised evaluation on held-out labels at this site is
    #: "unseen labels", not "unseen site".
    UNSEEN_LABELS_SEEN_ACQUISITION = "unseen_labels_seen_acquisition"


class SSLSourceFile(BaseModel):
    """
    One real, on-disk GPR file (or, for BAM, one real 3-D scan volume) that
    Self-Supervised GPR Encoder V1 may window. Built by
    `training.ssl_corpus.discover_source_files` from the files actually
    present on disk -- never hand-typed, so this list cannot silently drift
    from what is really held.
    """
    dataset_id: str
    site_id: str
    survey_id: str
    source_file: str
    #: Which low-level reader `training.ssl_corpus.read_window` dispatches
    #: to for this file -- not a general format name, a dispatch key.
    reader: str
    sensor_vendor: Optional[str] = None
    antenna_frequency_mhz: Optional[float] = None
    sample_interval_ns: Optional[float] = None
    trace_spacing_m: Optional[float] = None
    n_traces: int
    n_samples: int
    #: For a real 3-D volume windowed by 2-D slice (BAM: (X, Y, samples),
    #: sliced along Y into X-by-samples "lines" -- see
    #: `training.ssl_corpus.discover_bam_source_files`), which slice index
    #: along the un-windowed axis this entry is. `None` for a file that is
    #: already 2-D (every other reader).
    line_index: Optional[int] = None
    license: Optional[str] = None
    commercial_use_permitted: Optional[bool] = None
    license_pool: LicensePool
    split: Optional[SiteSplit] = None
    exposure: Optional[SiteExposure] = None


class SSLWindowRef(BaseModel):
    """
    One SSL training/validation window: WHERE it comes from, not the window
    itself. `training.ssl_corpus.read_window` materialises the real
    amplitude array from `source_file` at (`trace_start`:`trace_end`,
    `sample_start`:`sample_end`) at read time.
    """
    dataset_id: str
    site_id: str
    survey_id: str
    source_file: str
    reader: str
    #: (first, last) trace index, inclusive.
    trace_start: int
    trace_end: int
    #: (first, last) sample index, inclusive.
    sample_start: int
    sample_end: int
    #: See `SSLSourceFile.line_index`'s own docstring.
    line_index: Optional[int] = None
    sensor_vendor: Optional[str] = None
    antenna_frequency_mhz: Optional[float] = None
    sample_interval_ns: Optional[float] = None
    preprocessing_version: str
    license: Optional[str] = None
    commercial_use_permitted: Optional[bool] = None
    license_pool: LicensePool
    split: SiteSplit
    exposure: SiteExposure


class SSLArtifactProvenance(BaseModel):
    """
    What must be recorded before a trained SSL encoder artifact is allowed
    to become evidence, per the milestone brief's Section 15 list. Mirrors
    `schemas.segmentation.ModelArtifactProvenance`'s own discipline
    ("constructed once, never partially") for a different training
    objective -- kept as a separate type because an SSL artifact's
    provenance is about MASKING/RECONSTRUCTION configuration that a
    supervised-detector artifact has no equivalent field for, and forcing
    the two into one schema would mean optional fields on both sides.
    """
    model_config = ConfigDict(protected_namespaces=())

    architecture: str
    parameter_count: int
    training_commit: str
    training_sites: list[str]
    validation_sites: list[str]
    reserved_sites: list[str]
    #: dataset_id -> licence string, for every source file this encoder saw.
    licenses: dict[str, str]
    commercial_use_status: LicensePool
    preprocessing_version: str
    normalization: str
    masking_strategy: str
    mask_ratio: float
    seed: int
    optimizer: str
    learning_rate: float
    epochs: int
    batch_size: int
    hardware: str
    metrics: dict[str, float]
    model_checksum_sha256: str
    trained_utc: str
    #: Never omitted: what this encoder is NOT validated for, stated as
    #: plainly as what it is -- mirrors `ModelArtifactProvenance.validity_caveat`.
    limitations: str = Field(..., min_length=1)
    extra: dict[str, Any] = Field(default_factory=dict)
