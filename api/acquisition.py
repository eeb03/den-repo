"""
The acquisition boundary: what arrived, what it is, and what it will and will
not support — decided before ingestion, not after.

WHY THIS IS NOT A NEW PIPELINE. `ImportJob` already recorded the original
filename, the sanitised stored name, the size, the detected format, the
resulting dataset id and a failure stage; `jobs/storage.py` already streamed
uploads into a per-job directory with a size cap and a traversal-proof
filename; `converters/registry.py` already classified files. A separate
`Acquisition` table would have been a second upload path with its own
ownership rules, its own failure vocabulary and its own drift. So the
acquisition record IS the import job, plus the four things it was missing: a
checksum, the claimed content type, an identification result, and a place to
STOP before ingesting.

ACQUISITION IS NOT THE DATASET, and the distinction is the point of the stage.
The acquisition describes what somebody handed to Subterra -- bytes, a name, a
time of arrival. The dataset describes what Subterra made of it. One
acquisition may produce no dataset at all (unsupported, malformed, withdrawn),
and the record of its arrival survives either way.

THE HOLD POINT IS THE NEW BEHAVIOUR. Before this, an upload was queued the
moment it landed and the first thing a user learned about a spatially
unusable file was a finished dataset that could not be placed. With
`review=true` the acquisition stops at IDENTIFIED or NEEDS_INPUT and states
what it found, so the decision to ingest is made by somebody who knows what
they are ingesting.

WHAT IDENTIFICATION MAY NOT DO. It reads the registry and the file's own
extension and size. It does not parse the payload, does not sniff for a
modality the extension cannot support, and does not guess a CRS, a datum, a
time window or a velocity. A `.csv` may be GPR traces, a point cloud or a DEM,
and Subterra does not know which -- so the modality stays the one the user
declared, and the ambiguity is reported rather than resolved.
"""
from __future__ import annotations

from typing import Any, Optional

from converters.registry import classify_file, supported_extensions
from database.models import Dataset, ImportJob
from utils.logger import get_logger

logger = get_logger(__name__)

# --- acquisition states ----------------------------------------------------
#
# ONE STATE MACHINE, EXTENDED -- not a second one beside `ImportJob.state`.
# Everything from QUEUED onward is the existing ingestion job, untouched; the
# states below it are the acquisition boundary that now precedes it. A second
# `acquisition_state` column would have meant two fields that could disagree
# about whether the same file was finished.
#
#     RECEIVED ──▶ IDENTIFIED ──▶ QUEUED ──▶ RUNNING ──▶ SUCCEEDED
#         │            │                                     │
#         │            └──▶ NEEDS_INPUT ──▶ QUEUED           FAILED
#         └──▶ REJECTED
#
RECEIVED = "RECEIVED"
IDENTIFIED = "IDENTIFIED"
NEEDS_INPUT = "NEEDS_INPUT"
REJECTED = "REJECTED"

#: States in which an acquisition is waiting for a person, and from which
#: `accept` may move it into the existing pipeline.
HELD_STATES = (IDENTIFIED, NEEDS_INPUT)

#: Terminal without a dataset. Distinct from FAILED, which means ingestion was
#: attempted and did not finish -- a difference the user needs, because one is
#: "we cannot read this" and the other is "something went wrong".
TERMINAL_WITHOUT_DATASET = (REJECTED,)


# --- failure categories ----------------------------------------------------
#
# Recorded in `error_stage` so "upload failed" never has to stand for six
# different things. Each is answerable by a different action.
STAGE_UPLOAD = "upload"                  # the bytes never arrived intact
STAGE_FORMAT = "format-check"            # arrived, cannot be identified
STAGE_IDENTIFICATION = "identification"  # identified, but not usably
STAGE_VALIDATION = "validation"          # readable, but malformed
STAGE_INGESTION = "ingestion"            # accepted, pipeline failed


def duplicates_of(db, checksum: Optional[str], *, owner_id: Optional[str],
                  exclude_job_id: Optional[str] = None) -> dict[str, Any]:
    """
    Whether these exact bytes have been seen before.

    REPORTED, NEVER ACTED ON. Stage 7 established this for datasets and the
    reasoning is unchanged: the four INGV datasets share one checksum and are
    four different ingestion events under different converter behaviour.
    Identical bytes arriving twice is a fact about the bytes, not a mistake to
    be corrected, and the user decides what it means.

    Scoped to what the caller may already see -- their own acquisitions and the
    datasets visible to them -- so this cannot become a way to discover that
    somebody else holds a particular file.
    """
    if not checksum:
        return {"checked": False, "reason": "no checksum was computed"}

    datasets = [
        {"dataset_id": d.id, "name": d.name}
        for d in db.query(Dataset).filter(Dataset.checksum == checksum).all()
        if d.owner_id in (owner_id, None)
    ]
    query = db.query(ImportJob).filter(ImportJob.checksum == checksum,
                                       ImportJob.owner_id == owner_id)
    if exclude_job_id:
        query = query.filter(ImportJob.id != exclude_job_id)
    acquisitions = [
        {"acquisition_id": j.id, "original_filename": j.original_filename,
         "state": j.state, "dataset_id": j.dataset_id}
        for j in query.all()
    ]

    return {
        "checked": True,
        "is_duplicate": bool(datasets or acquisitions),
        "datasets": datasets,
        "acquisitions": acquisitions,
        "note": ("byte-identical to something already held. Separate arrivals are kept "
                 "separate: identical bytes can still be different ingestion events, "
                 "under different converter behaviour."),
    }


#: What each supported format can carry SPATIALLY, from the converter's own
#: documented behaviour rather than from inspecting the payload. This is an
#: EXPECTATION, not a measurement: it says what the format is capable of
#: declaring, and the dataset report says what this particular file actually
#: declared once it has been read.
_FORMAT_SPATIAL_EXPECTATION: dict[str, dict[str, Any]] = {
    "segy": {
        "horizontal": "trace headers may carry easting/northing; the projection is "
                      "usually not declared in the file",
        "vertical": "a two-way time axis; no vertical datum",
        "missing": ["the EPSG code of the header coordinates", "a vertical datum"],
    },
    "ids_dt": {
        "horizontal": "none: the format carries along-track distance from the wheel "
                      "encoder, not a position on Earth",
        "vertical": "a two-way time window, read from the file's own H record",
        "missing": ["a GeoTie, which is the only route from along-track distance to "
                    "a geographic position", "a vertical datum"],
    },
    "mala": {
        "horizontal": "an optional companion coordinate file",
        "vertical": "a two-way time axis; no vertical datum",
        "missing": ["a vertical datum"],
    },
    "csv": {
        "horizontal": "whatever columns the file happens to contain",
        "vertical": "whatever columns the file happens to contain",
        "missing": ["a declared CRS, unless the file states one",
                    "a vertical datum"],
    },
    "geotiff": {
        "horizontal": "a declared CRS, usually present",
        "vertical": "elevation values, but GeoTIFF routinely omits the vertical datum",
        "missing": ["a vertical datum"],
    },
    "las": {
        "horizontal": "a declared CRS in the header",
        "vertical": "elevation values; the datum is often undeclared",
        "missing": ["a vertical datum"],
    },
}

#: Formats whose contents cannot be inferred from the extension. A `.csv` may
#: be GPR traces, a point cloud or a DEM, and guessing is how a depth slice
#: gets processed as a radargram.
_AMBIGUOUS_FORMATS = {"csv"}


def identify(job: ImportJob, db) -> dict[str, Any]:
    """
    Establish what arrived, without reading the payload.

    Returns the identification block stored on the acquisition. It reports what
    it knows AND what it does not: a format that could hold several kinds of
    data says so rather than picking one.
    """
    classification, detail = classify_file(job.stored_filename or job.original_filename or "")
    expectation = _FORMAT_SPATIAL_EXPECTATION.get(detail, {})
    ambiguous = detail in _AMBIGUOUS_FORMATS

    identification: dict[str, Any] = {
        "original_filename": job.original_filename,
        "stored_filename": job.stored_filename,
        "size_bytes": job.size_bytes,
        "checksum": job.checksum,
        "content_type_claimed": job.content_type,
        "classification": classification,
        "detected_format": detail,
        "parser_available": classification == "supported",
        # The modality is the one the USER declared. No converter can establish
        # it from the bytes, and inferring it from an extension is how a depth
        # slice gets processed as a radargram.
        "declared_modality": job.sensor_type,
        "modality_source": "declared_by_uploader",
        "ambiguous_format": ambiguous,
        "ambiguity_note": (
            f"a {detail} file can hold several kinds of measurement, and Subterra "
            f"cannot tell which from the file alone. It will be read as "
            f"{job.sensor_type!r} because that is what you declared."
        ) if ambiguous else None,
        "spatial_expectation": expectation or {
            "horizontal": "unknown for this format",
            "vertical": "unknown for this format",
            "missing": [],
        },
        "duplicates": duplicates_of(db, job.checksum, owner_id=job.owner_id,
                                    exclude_job_id=job.id),
        # Ingestion readiness and spatial readiness are SEPARATE, and this is
        # where that separation starts. A file with no usable spatial reference
        # is still worth parsing, processing and assessing.
        "ingestion_ready": classification == "supported",
        "spatial_expectation_note": (
            "what this FORMAT can carry, not what this file declares. The dataset "
            "report answers the second question, once the file has been read."
        ),
    }

    if classification != "supported":
        identification["rejection_reason"] = (
            f"'{detail}' is a recognised format but no adapter can read it yet."
            if classification == "recognized_unsupported"
            else f"Unrecognised file type '{detail}'."
        )
        identification["supported_formats"] = sorted(supported_extensions())

    return identification


def state_after_identification(identification: dict[str, Any]) -> str:
    """
    Where the acquisition rests once identified.

    REJECTED when nothing can read it. NEEDS_INPUT when it can be read but a
    decision belongs to the user -- an ambiguous format, or bytes already held.
    IDENTIFIED otherwise, which still waits for `accept`: the hold is the point
    of the review flow, not a penalty for being unusual.
    """
    if not identification.get("parser_available"):
        return REJECTED
    if identification.get("ambiguous_format"):
        return NEEDS_INPUT
    if (identification.get("duplicates") or {}).get("is_duplicate"):
        return NEEDS_INPUT
    return IDENTIFIED


def open_session_or_refuse(db, user, session_id: str):
    """
    The acquisition session this upload belongs to, if it may still have one.

    Refuses in three distinguishable ways rather than one: a session that does
    not exist (or is not the caller's) is a 404 so an id cannot be probed; a
    session that has ended is a 409, because attaching to a completed
    acquisition event would rewrite history rather than record it.
    """
    from fastapi import HTTPException

    from database.models import AcquisitionSession
    from schemas.devices import ACCEPTS_ACQUISITIONS, SessionState

    session = (
        db.query(AcquisitionSession)
        .filter(AcquisitionSession.id == session_id)
        .first()
    )
    if session is None or session.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    if SessionState(session.state) not in ACCEPTS_ACQUISITIONS:
        raise HTTPException(
            status_code=409,
            detail=(f"this session is {session.state} and cannot receive an "
                    f"acquisition; only "
                    f"{' or '.join(s.value for s in ACCEPTS_ACQUISITIONS)} can"))
    return session


#: Which formats can accept which ingest declarations. Kept explicit so an
#: option that would be silently ignored is refused instead of recorded as
#: though it had done something.
INGEST_OPTIONS_BY_FORMAT: dict[str, tuple[str, ...]] = {
    "geotiff": ("band_is_elevation",),
    # How to decode coordinates/elevation already present in a SEG-Y file's
    # trace header fields (converters.segy_converter.COORDINATE_ENCODINGS) --
    # a declaration about DECODING, never a source of coordinates that are
    # actually absent. See that module's own docstring.
    "segy": ("coordinate_encoding",),
}


def validated_ingest_options(job, body) -> dict[str, Any]:
    """
    The declarations a user made at review, checked against what this file's
    converter can actually use.

    A raster band carries numbers and no statement of what they measure, so
    whether band 1 is elevation is a CLAIM somebody makes -- and it changes what
    the converter produces. Recording one for a format that cannot use it would
    be provenance for an effect that never happened.
    """
    from fastapi import HTTPException

    if body is None:
        return {}

    declared = {k: v for k, v in body.model_dump().items() if v is not None}
    if not declared:
        return {}

    fmt = (job.identification or {}).get("detected_format")
    accepted = INGEST_OPTIONS_BY_FORMAT.get(fmt, ())
    unusable = sorted(set(declared) - set(accepted))
    if unusable:
        raise HTTPException(
            status_code=422,
            detail=(f"{', '.join(unusable)} cannot be applied to a {fmt} file; "
                    f"this format accepts {', '.join(accepted) or 'no ingest options'}"))
    return declared
