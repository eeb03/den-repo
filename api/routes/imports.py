"""
Dataset import: upload now, process in the background, report truthfully.

The existing `POST /api/datasets/ingest` still exists and is unchanged. It runs
the whole pipeline inside the request, which is fine for a small CSV and
unusable for a 112 MB SEG-Y -- the connection is held for the duration and the
client learns nothing until it finishes or times out. This router adds the
asynchronous path the product needs without removing the synchronous one.

WHAT IS AND IS NOT REPORTED. A job carries a STATE (QUEUED / RUNNING /
SUCCEEDED / FAILED) and the name of the pipeline STAGE it is in. It carries no
percentage: the pipeline cannot measure fractional completion, and a number
derived from "step 3 of 5" would be a fabricated measurement in a platform
whose central claim is that it does not fabricate measurements.

FORMAT SUPPORT IS ASKED, NEVER ASSUMED. `GET /api/imports/formats` returns what
`converters/registry.py` actually dispatches on, plus the formats it can NAME
but not read. The interface renders that answer; it does not keep a second list
that could drift from the registry and start promising formats nobody can read.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from converters.registry import (
    KNOWN_UNSUPPORTED_FORMATS,
    classify_file,
    supported_extensions,
)
from auth.dependencies import get_current_user, job_or_404
from database.models import ImportJob, User, gen_uuid
from database.session import get_db
from api import acquisition
from jobs import runner, storage
from schemas.subterra_record import SensorType
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/formats")
def import_formats():
    """
    What the platform can actually read, straight from the converter registry.

    `recognized_unsupported` is not padding: `KNOWN_UNSUPPORTED_FORMATS` exists
    so ingestion can say "this is an IDS GeoRadar sidecar and no adapter reads
    it" instead of skipping the file in silence. Surfacing it lets the import
    screen tell a user the difference between "we know what this is and cannot
    read it" and "we have no idea what this is" -- two very different answers
    that a single "unsupported" would collapse.
    """
    return {
        "supported": sorted(supported_extensions()),
        "recognized_unsupported": [
            {"extension": ext, "description": desc}
            for ext, desc in sorted(KNOWN_UNSUPPORTED_FORMATS.items())
        ],
        "max_upload_bytes": storage.MAX_UPLOAD_BYTES,
        "note": (
            "Being listed under recognized_unsupported is a promise that the "
            "file will be reported explicitly, not a claim of support."
        ),
    }


@router.post("", status_code=202)
@router.post("/", status_code=202)
async def create_import(
    file: UploadFile = File(...),
    sensor_type: SensorType = Form(...),
    name: Optional[str] = Form(None),
    review: bool = Form(False),
    session_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Accept an upload, persist it safely, identify it, and either queue it or
    hold it for review.

    `review=false` (the default) is the original behaviour, unchanged: the file
    is queued immediately. `review=true` is FileDrop: the acquisition stops at
    IDENTIFIED, NEEDS_INPUT or REJECTED and reports what it found, and nothing
    is ingested until `POST /jobs/{id}/accept`. Defaulting to the old behaviour
    keeps every existing caller working rather than making the new flow
    mandatory for scripts that never wanted it.

    `session_id` IS WHERE STAGE 10 CONVERGES WITH STAGE 9. A device session
    produces its acquisition through THIS route rather than one of its own, so
    everything after receipt -- identification, the review hold, validation,
    spatial assessment, ingestion, the dataset -- is the same code for a file
    somebody dropped and for a file a session produced. A separate hardware
    endpoint would be a second pipeline, and the two would drift.

    202 rather than 201: the dataset does not exist yet, and saying it does
    would be the first untruth in the workflow. The response carries a job id;
    the dataset id appears on that job only once the pipeline has actually
    registered one.

    The upload is written to disk BEFORE the job is queued, so a job is never
    queued against a file that is not fully there.
    """
    job_id = gen_uuid()
    classification, detail = classify_file(file.filename or "")

    # A session must exist, belong to the caller, and still be open. Checked
    # BEFORE any bytes are written: an acquisition attributed to a session that
    # cannot accept it would be a provenance claim nobody could act on.
    session = None
    if session_id:
        session = acquisition.open_session_or_refuse(db, user, session_id)

    job = ImportJob(
        id=job_id,
        job_type="dataset_import",
        state=runner.QUEUED,
        stage=runner.STAGE_QUEUED,
        original_filename=file.filename,
        session_id=session.id if session is not None else None,
        sensor_type=sensor_type.value,
        detected_format=detail,
        format_status=classification,
        # OWNERSHIP COMES FROM THE SESSION. There is no owner_id field on this
        # request and there must never be one: a client that could name the
        # owner could give its upload away, or take someone else's.
        owner_id=user.id,
        created_at=datetime.utcnow(),
    )

    # Refuse formats we cannot read BEFORE writing anything to disk. Storing an
    # unreadable upload would leave bytes nobody can use and a job that exists
    # only to fail.
    if classification != "supported":
        job.state = runner.FAILED
        job.error_stage = "format-check"
        job.error_message = (
            f"'{detail}' is recognised but no adapter can read it yet."
            if classification == "recognized_unsupported"
            else f"Unrecognised file type '{detail}'. Supported: {sorted(supported_extensions())}"
        )
        job.completed_at = datetime.utcnow()
        db.add(job)
        db.commit()
        return {"job": job.to_dict()}

    job.content_type = file.content_type

    try:
        path, stored, size, checksum = storage.save_upload(job_id, file.filename, file.file)
    except (storage.UploadTooLarge, storage.EmptyUpload) as exc:
        storage.cleanup_job_dir(job_id)
        job.state = runner.FAILED
        job.error_stage = "upload"
        job.error_message = str(exc)
        job.completed_at = datetime.utcnow()
        db.add(job)
        db.commit()
        return {"job": job.to_dict()}

    job.stored_filename = stored
    job.stored_path = str(path)
    job.size_bytes = size
    job.checksum = checksum
    if name:
        job.original_filename = job.original_filename or name

    # Identification happens for BOTH flows: an immediate import gets the same
    # record of what arrived, it simply does not stop to show it.
    job.identification = acquisition.identify(job, db)

    if review:
        job.state = acquisition.state_after_identification(job.identification)
        job.stage = None
        db.add(job)
        db.commit()
        payload = job.to_dict()
        logger.info("acquisition %s held at %s (%s, %d bytes)",
                    job_id, payload["state"], stored, size)
        return {"job": payload}

    db.add(job)
    db.commit()

    # Snapshot BEFORE handing the job to the worker. After commit the instance
    # is expired, so reading it again would re-SELECT -- and a small file can
    # finish before that read happens, making this response report SUCCEEDED
    # for a job the caller has not yet been told the id of. The state at
    # hand-off is QUEUED; the client polls for the rest.
    payload = job.to_dict()

    runner.submit(job_id)
    logger.info("queued import job %s for %s (%d bytes)", job_id, stored, size)
    return {"job": payload}


class AcceptRequest(BaseModel):
    """
    What the user declares at the review step about how to read this file.

    Currently one thing: whether a raster band is elevation. Validated against
    what the detected format can actually accept, so an option that would be
    silently ignored is refused rather than recorded as though it had an effect.
    """
    band_is_elevation: Optional[bool] = None


@router.post("/jobs/{job_id}/accept", status_code=202)
def accept_acquisition(job_id: str, body: Optional[AcceptRequest] = None,
                       db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """
    Hand a reviewed acquisition to the existing ingestion pipeline.

    This is the whole handoff. It queues the job the pipeline already knows how
    to run -- no second normalisation, no second validator, no second dataset
    model. The acquisition keeps its id, so the dataset it produces stays
    traceable to the bytes that arrived.

    Only a HELD acquisition may be accepted. Accepting a rejected one would ask
    the pipeline to read a file nothing can read; accepting a running or
    finished one would ingest the same bytes twice under one record.
    """
    job = job_or_404(db, user, job_id)

    if job.state not in acquisition.HELD_STATES:
        raise HTTPException(
            status_code=409,
            detail=(f"this acquisition is {job.state} and cannot be accepted; "
                    f"only {' or '.join(acquisition.HELD_STATES)} can be"))

    options = acquisition.validated_ingest_options(job, body)
    if options:
        job.ingest_options = options

    job.state = runner.QUEUED
    job.stage = runner.STAGE_QUEUED
    db.commit()
    payload = job.to_dict()

    runner.submit(job_id)
    logger.info("acquisition %s accepted and queued", job_id)
    return {"job": payload}


@router.get("/jobs")
def list_jobs(
    limit: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    jobs = (
        db.query(ImportJob)
        .filter(ImportJob.owner_id == user.id)
        .order_by(ImportJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"jobs": [j.to_dict() for j in jobs]}


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 404 for someone else's job as well as for a missing one: guessing ids
    # must not reveal which of the two it was.
    return {"job": job_or_404(db, user, job_id).to_dict()}
