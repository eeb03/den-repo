"""
Devices and acquisition sessions.

WHAT THIS IS NOT. There is no hardware integration behind any of these routes.
Nothing here opens a port, speaks a protocol, or asks an instrument anything.
Registering a device records what somebody says they used; a session records
that an acquisition event happened. That is provenance, and it is all Stage 10
claims to be.

WHERE THE CONVERGENCE HAPPENS. A session does not have its own upload endpoint.
It produces an acquisition through `POST /api/imports` -- the same route
FileDrop uses -- with a `session_id`. Everything after that point is identical:
the same identification, the same review hold, the same validation, the same
ingestion, the same dataset. There is deliberately no hardware path and no file
path, because a second pipeline is how the two would drift.

AUTHORISATION IS THE EXISTING MECHANISM. Devices and sessions follow the rule
datasets already follow: a NULL owner is system/reference data, readable by
everyone and writable by nobody; another user's device is a 404 rather than a
403, so an id cannot be probed for existence.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from database.models import AcquisitionSession, Device, ImportJob, User, gen_uuid
from database.session import get_db
from schemas.devices import (
    ACCEPTS_ACQUISITIONS,
    FAILURE_STAGES,
    DeviceAdapter,
    DeviceCapabilities,
    DeviceKind,
    IdentitySource,
    InvalidTransition,
    SessionEvidence,
    SessionState,
    transition,
)
from schemas.subterra_record import SensorType
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class RegisterDeviceRequest(BaseModel):
    device_type: SensorType
    manufacturer: Optional[str] = Field(default=None, max_length=200)
    model: Optional[str] = Field(default=None, max_length=200)
    serial_number: Optional[str] = Field(default=None, max_length=200)
    firmware_version: Optional[str] = Field(default=None, max_length=200)
    label: Optional[str] = Field(default=None, max_length=200)
    capabilities: DeviceCapabilities = Field(default_factory=DeviceCapabilities)
    #: HOW this device's evidence is meant to arrive. Absent by default: a
    #: device with no declared adapter is valid and must not default to
    #: file_drop. See schemas/devices.py::DeviceAdapter.
    adapter: Optional[DeviceAdapter] = None
    #: Whether this record stands for real hardware or a stand-in. A simulated
    #: device is marked for ever after, in every dataset its sessions produce.
    kind: DeviceKind = DeviceKind.PHYSICAL


class CreateSessionRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)
    #: Who ran it, in their own words. Provenance, not an account.
    operator: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)


class SessionEvidenceRequest(BaseModel):
    evidence: SessionEvidence = Field(default_factory=SessionEvidence)


class FailSessionRequest(BaseModel):
    stage: str
    message: str = Field(..., min_length=1, max_length=2000)


def _device_or_404(db: Session, user: User, device_id: str) -> Device:
    """
    Visible devices: the caller's own, plus system devices owned by nobody.

    404 rather than 403 for somebody else's, so a device id cannot be tested for
    existence -- the rule datasets already follow.
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None or device.owner_id not in (user.id, None):
        raise HTTPException(status_code=404, detail="Device not found")
    return device


def _owned_device(db: Session, user: User, device_id: str) -> Device:
    device = _device_or_404(db, user, device_id)
    if device.owner_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="this is a system reference device and cannot be modified")
    return device


def _session_or_404(db: Session, user: User, session_id: str) -> AcquisitionSession:
    row = db.query(AcquisitionSession).filter(
        AcquisitionSession.id == session_id).first()
    if row is None or row.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return row


# ---------------------------------------------------------------------------
# devices
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
@router.post("/", status_code=201)
def register_device(body: RegisterDeviceRequest, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """
    Record an instrument.

    EVERYTHING HERE IS USER-DECLARED, and the record says so permanently.
    `identity_source` is fixed at `user_declared` and is not a request field: a
    client that could set it could assert that an instrument reported its own
    serial number, which would be a forgery. A future adapter that genuinely
    reads a serial off hardware will write `device_reported`, and the two will
    stay distinguishable in everything downstream.
    """
    device = Device(
        id=gen_uuid(),
        owner_id=user.id,
        manufacturer=body.manufacturer,
        model=body.model,
        device_type=body.device_type.value,
        serial_number=body.serial_number,
        firmware_version=body.firmware_version,
        label=body.label,
        capabilities=body.capabilities.model_dump(mode="json"),
        adapter=body.adapter.model_dump(mode="json") if body.adapter else None,
        identity_source=IdentitySource.USER_DECLARED.value,
        kind=body.kind.value,
        created_at=datetime.utcnow(),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    logger.info("registered %s device %s", device.kind, device.id)
    return {"device": device.to_dict()}


@router.get("")
@router.get("/")
def list_devices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    devices = (
        db.query(Device)
        .filter((Device.owner_id == user.id) | (Device.owner_id.is_(None)))
        .order_by(Device.created_at.desc())
        .all()
    )
    return [d.to_dict() for d in devices]


@router.get("/{device_id}")
def get_device(device_id: str, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    return {"device": _device_or_404(db, user, device_id).to_dict()}


@router.post("/{device_id}/sessions", status_code=201)
def create_session(device_id: str, body: CreateSessionRequest,
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """
    Begin a record of one acquisition event.

    A session starts CREATED and carries no evidence: nothing has been acquired
    yet, and a session that claimed otherwise at creation would be describing an
    event that has not happened.
    """
    device = _device_or_404(db, user, device_id)
    session = AcquisitionSession(
        id=gen_uuid(), device_id=device.id, owner_id=user.id,
        state=SessionState.CREATED.value, label=body.label,
        operator=body.operator, notes=body.notes,
        evidence=SessionEvidence().model_dump(mode="json"),
        created_at=datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session": session.to_dict(), "device": device.to_dict()}


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

sessions_router = APIRouter()


def _session_payload(db: Session, session: AcquisitionSession) -> dict[str, Any]:
    device = db.query(Device).filter(Device.id == session.device_id).first()
    capabilities = DeviceCapabilities.model_validate(
        (device.capabilities or {}) if device else {})
    evidence = SessionEvidence.model_validate(session.evidence or {})
    acquisitions = (
        db.query(ImportJob).filter(ImportJob.session_id == session.id)
        .order_by(ImportJob.created_at.asc()).all()
    )
    return {
        "session": session.to_dict(),
        "device": device.to_dict() if device else None,
        # THE GAP, STATED. What the device can do and what this session actually
        # provided are two different lists, and the difference is the point.
        "capability_gap": evidence.missing(capabilities),
        "acquisitions": [
            {"acquisition_id": j.id, "state": j.state,
             "original_filename": j.original_filename, "dataset_id": j.dataset_id}
            for j in acquisitions
        ],
        "datasets": [j.dataset_id for j in acquisitions if j.dataset_id],
    }


@sessions_router.get("/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    return _session_payload(db, _session_or_404(db, user, session_id))


@sessions_router.post("/{session_id}/state")
def move_session(session_id: str, to: SessionState, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """
    Move a session along its lifecycle.

    ONE ENDPOINT, NOT FIVE. The legal transitions live in
    `schemas/devices.py::ALLOWED_TRANSITIONS`; separate `start`, `complete` and
    `cancel` routes would each have to re-check the same table, and would drift.
    A terminal session never reopens: a second acquisition event is a second
    session, and reopening one would make its start and end times describe two
    different things.
    """
    session = _session_or_404(db, user, session_id)
    try:
        new_state = transition(SessionState(session.state), to)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    session.state = new_state.value
    if new_state == SessionState.ACQUIRING and session.started_at is None:
        session.started_at = datetime.utcnow()
    if new_state in (SessionState.COMPLETED, SessionState.CANCELLED, SessionState.FAILED):
        session.ended_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return _session_payload(db, session)


@sessions_router.post("/{session_id}/evidence")
def record_evidence(session_id: str, body: SessionEvidenceRequest,
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """
    Record what this session actually provided.

    NOT WHAT THE DEVICE CAN PROVIDE -- that is on the device and does not change.
    A session whose GNSS never got a fix records `position_provided=False` even
    though its device reports positions, and the report says so. Nothing here
    stores a coordinate, an orientation or a time: it records WHETHER a kind of
    information arrived, so the spatial workflow can say what is missing. The
    values themselves live on records, on frames, and in spatial declarations,
    where they already have provenance.
    """
    session = _session_or_404(db, user, session_id)
    if SessionState(session.state) not in ACCEPTS_ACQUISITIONS + (SessionState.CREATED,):
        raise HTTPException(
            status_code=409,
            detail=f"this session is {session.state} and no longer records evidence")
    session.evidence = body.evidence.model_dump(mode="json")
    db.commit()
    db.refresh(session)
    return _session_payload(db, session)


@sessions_router.post("/{session_id}/fail")
def fail_session(session_id: str, body: FailSessionRequest,
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """
    Record that the acquisition event failed, and how.

    The stage matters: a device that was never reachable, a session that could
    not start, a measurement that failed midway and a payload that arrived
    invalid have different answers, and "device error" for all of them tells
    nobody anything. Ingestion failure is deliberately NOT one of these -- that
    belongs to the import job, which has its own stages. A session does not fail
    because a parser did.
    """
    if body.stage not in FAILURE_STAGES:
        raise HTTPException(
            status_code=422,
            detail=f"stage must be one of {', '.join(FAILURE_STAGES)}")
    session = _session_or_404(db, user, session_id)
    try:
        session.state = transition(SessionState(session.state), SessionState.FAILED).value
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    session.failure_stage = body.stage
    session.failure_message = body.message
    session.ended_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return _session_payload(db, session)
