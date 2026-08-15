"""
The dataset lifecycle: naming, status, duplicate awareness, and deletion.

WHY DELETION NEEDED A POLICY RATHER THAN A CASCADE. `DELETE /api/datasets/{id}`
removed one row and nothing else. Everything a dataset actually consists of --
its normalised records, its survey frames, its labels, its resolved objects --
lives in JSONL beside the database, and none of it was touched. The corpus on
this machine carries 15 orphaned artifact sets totalling 167 MB for datasets
that no longer exist, which is what that looks like after a few months.

Adding `cascade="all, delete-orphan"` would not have fixed it: the files are not
rows, and the rows that DO reference a dataset should not all be treated the
same way. So the policy is explicit, and it follows one line:

    DERIVED DATA IS REMOVED. SOURCE DATA AND EVENT LOGS ARE RETAINED.

  removed   the dataset row and its versions; records, frames, labels,
            associations and objects; fusion samples that included it; the
            spatial declarations made about it
  retained  the raw source file, and the import job that created it

THE RAW FILE IS NEVER DELETED, and this is the most important decision here. It
is the bottom of the evidence chain -- the original measurement every later
claim reduces to -- and it cannot be regenerated. It is also demonstrably
SHARED: the four INGV datasets in this corpus have identical source checksums
and point into the same download, so deleting "one dataset's" raw file would
destroy three other datasets' provenance. A user who wants the bytes gone can
remove them; the platform will not do it on their behalf as a side effect of
tidying a list.

THE IMPORT JOB IS NEVER DELETED either. An import happened; that a dataset was
later removed does not un-happen it. The job is an append-only record of an
event, and `dataset_id` on it means "the dataset this import produced", which
may since have been deleted. Deleting jobs would make the import history lie by
omission.

FUSION SAMPLES ARE REMOVED, because they are derived: a fusion sample is the
output of a computation over datasets, recomputable from whatever remains, and a
sample that silently references a dataset nobody can open is worse than no
sample.

SPATIAL DECLARATIONS ARE REMOVED for a different reason: they are claims ABOUT
this dataset ("its vertical datum is NAP") and describe nothing once it is gone,
unlike an import job, which records an event that really happened. They also
carry a foreign key to `datasets.id`, so retaining them is not merely
undesirable -- it makes the delete fail.

ROW FIRST, FILES SECOND. The two failure modes are not symmetric. If the files
go and the row survives, the dataset is still listed and still openable while
everything it consists of has silently vanished -- which is what happened during
Stage 8 browser verification when the new declaration table's foreign key made
the row delete fail after the artifacts were already unlinked. If the row goes
and a file survives, the result is an orphan: recoverable, reportable by
`scripts/find_orphaned_artifacts.py`, and visible. So the database commits
first, and the files are removed after.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from configs.settings import settings
from database.models import (
    Dataset, DatasetVersion, FusionSample, ImportJob, SpatialDeclaration)
from utils.logger import get_logger

logger = get_logger(__name__)

#: Job states that mean work is in flight. Taken from `ImportJob.state`, not
#: redefined -- a second status vocabulary is how two parts of a product start
#: disagreeing about whether something is finished.
ACTIVE_JOB_STATES = ("QUEUED", "RUNNING")

#: Every per-dataset artifact this platform writes, by suffix. Kept in one place
#: because the failure mode is a store being added later and quietly not being
#: cleaned up -- exactly how the existing orphans accumulated. A test asserts
#: this list covers every `_path_for` in `database/`.
ARTIFACT_SUFFIXES = (
    ".jsonl",                 # normalised records      (records_store)
    ".frames.json",           # survey frames           (frames_store)
    ".labels.json",           # semantic labels         (labels_store)
    ".associations.json",     # candidate associations  (objects_store)
    ".objects.json",          # resolved objects        (objects_store)
    ".candidates.json",       # stored candidate set    (candidates_store)
)


# ---------------------------------------------------------------------------
# naming
# ---------------------------------------------------------------------------

#: Long enough for a descriptive survey name, short enough that it cannot be
#: used to smuggle a document into a column.
MAX_NAME_LENGTH = 200


class InvalidDatasetName(ValueError):
    """The proposed name cannot be stored."""


def clean_dataset_name(raw: Optional[str]) -> str:
    """
    Validate and normalise a human-facing dataset name.

    THE NAME IS NOT AN IDENTIFIER. The dataset id is immutable and is what every
    record, frame, label and artifact is keyed on; renaming touches one column
    and nothing else. Two datasets may legitimately share a name -- the corpus
    already has two called "INGV-UNISA Site 1 GPR v3" -- so uniqueness is not
    enforced. Making the display name unique would either reject a reasonable
    request or silently mangle it.
    """
    name = (raw or "").strip()
    if not name:
        raise InvalidDatasetName("a dataset name cannot be empty")
    if len(name) > MAX_NAME_LENGTH:
        raise InvalidDatasetName(
            f"a dataset name cannot be longer than {MAX_NAME_LENGTH} characters")
    # Control characters would corrupt a log line or a terminal, and no real
    # survey name contains one.
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise InvalidDatasetName("a dataset name cannot contain control characters")
    return name


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@dataclass
class DatasetStatus:
    """
    Where a dataset is in its own lifecycle.

    DERIVED, NOT STORED. There is no status column, deliberately: a stored
    status is a second copy of the truth that drifts the moment a process dies
    between writing the data and writing the status. This is computed from the
    two things that are actually true -- whether an import job is in flight, and
    whether records exist -- so it cannot disagree with them.

    THE VOCABULARY IS THE JOB'S, EXTENDED. `state` carries `ImportJob.state`
    verbatim when a job is involved, so nothing is hidden or renamed.
    """
    #: importing | ready | empty | failed
    value: str
    reason: str
    #: The originating job's own state, when there is one. Never reinterpreted.
    job_state: Optional[str] = None
    job_id: Optional[str] = None

    @property
    def is_busy(self) -> bool:
        return self.value == "importing"


def status_for(dataset: Dataset, latest_job: Optional[ImportJob]) -> DatasetStatus:
    """
    One dataset's status, given its most recent import job (or None).

    Order matters: an in-flight job wins over record counts, because a dataset
    that is being written to is not "ready" merely because an earlier import
    left rows behind.
    """
    if latest_job is not None and latest_job.state in ACTIVE_JOB_STATES:
        return DatasetStatus(
            value="importing",
            reason=f"an import job is {latest_job.state.lower()}",
            job_state=latest_job.state, job_id=latest_job.id)

    records = int(getattr(dataset, "record_count", 0) or 0)
    if records > 0:
        return DatasetStatus(
            value="ready",
            reason=f"{records:,} record(s) are stored and readable",
            job_state=getattr(latest_job, "state", None),
            job_id=getattr(latest_job, "id", None))

    if latest_job is not None and latest_job.state == "FAILED":
        return DatasetStatus(
            value="failed",
            reason=(latest_job.error_message or "the import failed")[:200],
            job_state=latest_job.state, job_id=latest_job.id)

    return DatasetStatus(
        value="empty",
        reason="the dataset holds no records",
        job_state=getattr(latest_job, "state", None),
        job_id=getattr(latest_job, "id", None))


def latest_jobs_by_dataset(db, dataset_ids: Iterable[str]) -> dict[str, ImportJob]:
    """
    The most recent import job per dataset, in one query.

    Batched deliberately: the dataset list would otherwise issue a query per
    row, and a list endpoint that gets slower the more datasets a user has is a
    list endpoint that will eventually be paginated to hide the problem.
    """
    ids = [i for i in dataset_ids if i]
    if not ids:
        return {}
    rows = (
        db.query(ImportJob)
        .filter(ImportJob.dataset_id.in_(ids))
        .order_by(ImportJob.created_at.asc())
        .all()
    )
    # Last write wins, and the query is ordered ascending, so this leaves the
    # most recent job per dataset.
    return {job.dataset_id: job for job in rows}


# ---------------------------------------------------------------------------
# duplicate awareness
# ---------------------------------------------------------------------------

def duplicate_groups(datasets: Iterable[Dataset]) -> dict[str, list[str]]:
    """
    Datasets that were ingested from the same source bytes, grouped by checksum.

    DETECTION ONLY. Nothing here merges, hides or deletes anything, and that is
    a deliberate scientific decision rather than caution. The four INGV rows in
    this corpus share one checksum and one record count, and are still four
    different things: one read 100 files from the archive and three read 50
    (the archive ships three copies of the same 50 lines), and two were scored
    0.3 while two were scored 0.8 because the record schema changed between
    ingests. Identical bytes in, four different ingestion events, four different
    processing contexts.

    Collapsing them would destroy the only record of how converter behaviour
    changed over time -- which is provenance, not clutter. So the platform says
    "these four came from the same source" and lets the person decide.
    """
    by_checksum: dict[str, list[str]] = {}
    for dataset in datasets:
        checksum = getattr(dataset, "checksum", None)
        if not checksum:
            continue
        by_checksum.setdefault(checksum, []).append(dataset.id)
    return {c: ids for c, ids in by_checksum.items() if len(ids) > 1}


# ---------------------------------------------------------------------------
# deletion
# ---------------------------------------------------------------------------

@dataclass
class DeletionPlan:
    """
    Exactly what deleting a dataset will do, enumerated before it happens.

    Returned to the caller after the fact as well, because "deleted: true" is
    not an adequate answer for an irreversible operation over scientific data.
    A person should be able to read what went and what stayed.
    """
    dataset_id: str
    artifacts: list[str] = field(default_factory=list)
    fusion_sample_ids: list[str] = field(default_factory=list)
    spatial_declaration_ids: list[str] = field(default_factory=list)
    version_count: int = 0
    retained_raw_path: Optional[str] = None
    retained_job_ids: list[str] = field(default_factory=list)


def artifact_paths(dataset_id: str) -> list[Path]:
    """Every per-dataset artifact file that currently exists on disk."""
    processed = settings.processed_dir
    return [
        path for path in (processed / f"{dataset_id}{suffix}" for suffix in ARTIFACT_SUFFIXES)
        if path.exists()
    ]


def plan_deletion(db, dataset: Dataset) -> DeletionPlan:
    """What `delete_dataset` would remove and retain. Reads nothing destructive."""
    dataset_id = dataset.id
    samples = [
        s for s in db.query(FusionSample).all()
        if dataset_id in (s.dataset_ids or [])
    ]
    jobs = db.query(ImportJob).filter(ImportJob.dataset_id == dataset_id).all()
    declarations = db.query(SpatialDeclaration).filter(
        SpatialDeclaration.dataset_id == dataset_id).all()
    versions = db.query(DatasetVersion).filter(
        DatasetVersion.dataset_id == dataset_id).count()

    return DeletionPlan(
        dataset_id=dataset_id,
        artifacts=[p.name for p in artifact_paths(dataset_id)],
        fusion_sample_ids=[s.id for s in samples],
        spatial_declaration_ids=[d.id for d in declarations],
        version_count=versions,
        retained_raw_path=getattr(dataset, "raw_path", None),
        retained_job_ids=[j.id for j in jobs],
    )


def delete_dataset_completely(db, dataset: Dataset) -> DeletionPlan:
    """
    Apply the policy. Returns what was actually done.

    ORDER: the database first, the files second -- see the module docstring. A
    half-deleted dataset that is still listed is invisible; an orphaned file is
    not.
    """
    plan = plan_deletion(db, dataset)
    dataset_id = dataset.id

    if plan.fusion_sample_ids:
        db.query(FusionSample).filter(
            FusionSample.id.in_(plan.fusion_sample_ids)).delete(synchronize_session=False)

    # Claims about a dataset that no longer exists describe nothing, and their
    # foreign key would block the delete regardless.
    db.query(SpatialDeclaration).filter(
        SpatialDeclaration.dataset_id == dataset_id).delete(synchronize_session=False)

    # `Dataset.versions` cascades, so the versions go with the row.
    db.delete(dataset)
    db.commit()

    for path in artifact_paths(dataset_id):
        try:
            path.unlink()
        except OSError as exc:  # noqa: PERF203 -- one message per file is the point
            logger.error("could not remove artifact %s: %s", path.name, exc)

    # The parse cache is keyed on the file's identity; the file is gone, but a
    # dataset re-created under the same id must not read the old records back.
    from database.records_store import clear_records_cache

    clear_records_cache()

    logger.info(
        "deleted dataset %s: %d artifact(s), %d fusion sample(s), %d declaration(s), "
        "%d version(s); retained raw source and %d import job record(s)",
        dataset_id, len(plan.artifacts), len(plan.fusion_sample_ids),
        len(plan.spatial_declaration_ids), plan.version_count, len(plan.retained_job_ids),
    )
    return plan


def active_job_for(db, dataset_id: str) -> Optional[ImportJob]:
    """A queued or running import for this dataset, if there is one."""
    return (
        db.query(ImportJob)
        .filter(ImportJob.dataset_id == dataset_id,
                ImportJob.state.in_(ACTIVE_JOB_STATES))
        .first()
    )
