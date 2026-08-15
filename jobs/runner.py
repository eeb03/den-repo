"""
Running an import off the request thread, honestly.

WHAT THIS IS. A single background worker thread that pulls import jobs and runs
THE EXISTING INGEST PIPELINE unchanged. Nothing about conversion, validation,
preprocessing, record persistence or dataset registration is reimplemented
here; this module only decides when that pipeline runs and records what
happened while it did.

WHY NOT CELERY/REDIS. The deployment is a single uvicorn process against a
local database. A broker would add an operational dependency without buying
anything the product can currently use, and the honest cost of not having one
is written down in LIMITATIONS below rather than papered over.

WHY ONE WORKER, NOT FastAPI BackgroundTasks. Two reasons, both about telling
the truth. A dedicated single-thread executor makes QUEUED a real state -- a
second import genuinely waits -- whereas BackgroundTasks would start everything
at once and "queued" would be decorative. And a multi-minute CPU-bound ingest
running in FastAPI's request threadpool would compete with ordinary API calls;
here it cannot.

LIMITATIONS, stated rather than discovered later:

  1. SINGLE PROCESS. Jobs run in the API process. Two uvicorn workers would
     each get their own executor and each pick up work, so this design does NOT
     survive a multi-worker deployment as-is.
  2. RESTART. A job RUNNING when the process dies does not resume. It is not
     left lying either: `mark_orphaned_jobs_failed` runs at startup and moves
     any such row to FAILED with a stated reason, so the API can always
     represent what happened.
  3. NO RETRY. A failed job stays failed; the user re-imports.
  4. IN-MEMORY QUEUE. Work waiting in the executor is lost on restart, but the
     row is QUEUED in the database, so the same reconciliation catches it.

  The migration path when this stops being enough is to replace `submit()` with
  an enqueue to a real broker and run `_execute` in a separate worker process.
  The job table, the states and the API do not change.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from database.models import ImportJob
from database.session import get_session
from utils.logger import get_logger

logger = get_logger(__name__)

# --- states ---------------------------------------------------------------
QUEUED = "QUEUED"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
TERMINAL_STATES = (SUCCEEDED, FAILED)

# --- stages ---------------------------------------------------------------
# The steps the pipeline actually has. No percentage is derived from these:
# the pipeline cannot report fractional completion, and a number invented from
# a step index would be a fabricated measurement.
STAGE_QUEUED = "queued"
STAGE_CONVERTING = "converting"
STAGE_VALIDATING = "validating"
STAGE_PREPROCESSING = "preprocessing"
STAGE_PERSISTING = "persisting"
STAGE_REGISTERING = "registering"
STAGE_COMPLETE = "complete"

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="subterra-import")
_lock = threading.Lock()


def _set(job_id: str, **fields) -> None:
    """Write job fields in their own short transaction."""
    with get_session() as session:
        job = session.query(ImportJob).filter(ImportJob.id == job_id).first()
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)


def mark_orphaned_jobs_failed() -> int:
    """
    Reconcile jobs the process was running when it died.

    Called at startup. Without this a killed process leaves rows RUNNING for
    ever, and the API would keep reporting work that is not happening -- the
    one failure mode a job system must never have.
    """
    with get_session() as session:
        orphans = (
            session.query(ImportJob)
            .filter(ImportJob.state.in_([QUEUED, RUNNING]))
            .all()
        )
        for job in orphans:
            job.state = FAILED
            job.error_stage = job.stage or STAGE_QUEUED
            job.error_message = (
                "the server restarted while this import was in progress; "
                "the job did not resume. Re-import the file to try again."
            )
            job.completed_at = datetime.utcnow()
        count = len(orphans)
    if count:
        logger.info("Marked %d interrupted import job(s) as FAILED", count)
    return count


def submit(job_id: str) -> None:
    """Hand a persisted job to the worker."""
    _executor.submit(_execute, job_id)


def _execute(job_id: str) -> None:
    """
    Run one import. Every exception becomes a FAILED row with the stage that
    raised and the backend's own message -- never a generic apology, because a
    scientific tool that says "something went wrong" has told the user nothing
    they can act on.
    """
    # Imported here so the module graph stays acyclic: the route module imports
    # this one.
    from api.routes.datasets import _run_ingest_pipeline
    from schemas.subterra_record import SensorType

    with get_session() as session:
        job = session.query(ImportJob).filter(ImportJob.id == job_id).first()
        if job is None:
            logger.warning("import job %s vanished before it ran", job_id)
            return
        if job.state != QUEUED:
            return
        path = job.stored_path
        sensor_type = job.sensor_type
        name = job.original_filename or job.stored_filename
        # The trusted owner: written when the job was created, from the
        # authenticated session. The worker never sees the request.
        owner_id = job.owner_id
        ingest_options = job.ingest_options
        job.state = RUNNING
        job.stage = STAGE_CONVERTING
        job.started_at = datetime.utcnow()

    stage_holder = {"stage": STAGE_CONVERTING}

    def on_stage(stage: str) -> None:
        stage_holder["stage"] = stage
        _set(job_id, stage=stage)

    try:
        from pathlib import Path

        with get_session() as session:
            result = _run_ingest_pipeline(
                Path(path),
                SensorType(sensor_type),
                name,
                session,
                source="upload",
                on_stage=on_stage,
                owner_id=owner_id,
                # WHAT THE USER DECLARED AT REVIEW, handed to the converter
                # unchanged. The pipeline itself is untouched: this is the same
                # `converter_kwargs` seam the scripted ingest paths already use.
                converter_kwargs=ingest_options or None,
            )
        _set(
            job_id,
            state=SUCCEEDED,
            stage=STAGE_COMPLETE,
            dataset_id=result["dataset_id"],
            completed_at=datetime.utcnow(),
        )
        logger.info("import job %s succeeded -> dataset %s", job_id, result["dataset_id"])
    except Exception as exc:  # noqa: BLE001 - the message is the product feature
        detail = getattr(exc, "detail", None)
        _set(
            job_id,
            state=FAILED,
            error_stage=stage_holder["stage"],
            error_message=str(detail if detail is not None else exc)[:2000],
            completed_at=datetime.utcnow(),
        )
        logger.warning("import job %s failed at %s: %s", job_id, stage_holder["stage"], exc)
