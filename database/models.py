import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, DateTime, JSON, Boolean, ForeignKey, Text
)
from sqlalchemy.orm import relationship

from database.session import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    """
    A platform account.

    The table was created empty one commit before authentication existed, so
    that ownership could be added to `datasets` while doing so was free.
    Retrofitting a foreign key onto a populated table means deciding
    retroactively who owns data that was uploaded by nobody -- a question with
    no correct answer.

    The credential is a PBKDF2 hash in `password_hash`; see auth/passwords.py
    for why PBKDF2 and not bcrypt. No profile fields beyond an email and a
    display name: an account exists to own datasets, and anything else would be
    personal data collected for no stated purpose.
    """
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    #: Login identifier. Unique so the constraint exists before any row does.
    email = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=True)
    #: PBKDF2-HMAC-SHA256, encoded by auth/passwords.py. Nullable so the column
    #: could be added to the already-created users table; a user without one
    #: cannot log in, because verify_password refuses an absent hash.
    password_hash = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    datasets = relationship("Dataset", back_populates="owner")
    sessions = relationship("UserSession", back_populates="user",
                            cascade="all, delete-orphan")


class UserSession(Base):
    """
    One signed-in browser.

    ONLY THE HASH OF THE TOKEN IS STORED. The cookie carries 256 bits of
    `secrets` output; the database keeps SHA-256 of it, so a database dump
    cannot be replayed as a set of live sessions.

    Revocation is a column rather than a delete so that logging out leaves a
    trace: `revoked_at` says a session ended deliberately, which a missing row
    could not distinguish from one that expired or never existed.
    """
    __tablename__ = "user_sessions"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    #: SHA-256 of the cookie value. Unique: two sessions cannot share a token.
    token_hash = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    #: Coarse provenance for the session, for a future "your sessions" screen.
    user_agent = Column(String, nullable=True)

    user = relationship("User", back_populates="sessions")


class PasswordResetToken(Base):
    """
    A one-time credential for choosing a new password.

    ITS OWN TABLE, not columns on `users`. Reset state is transient, plural (a
    user may request twice), and needs its own expiry and consumption
    semantics; hanging it off the account row would mean a half-dozen nullable
    columns whose meaning depends on each other, and would put a live
    credential in the same row as the account it protects.

    ONLY THE HASH IS STORED, exactly as with session tokens. The raw token
    exists in the emailed link and nowhere else -- not in this table, not in a
    log line, not in an API response. A database dump therefore yields nothing
    that can reset anybody's password.

    `used_at` rather than a delete: a consumed token must be distinguishable
    from one that never existed, so a second use can be refused by the same
    atomic UPDATE that consumed it the first time. Rows are inert once used or
    expired.
    """
    __tablename__ = "password_reset_tokens"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    #: SHA-256 of the token in the link. Unique: two tokens cannot collide, and
    #: the index is what makes consumption a single indexed UPDATE.
    token_hash = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LoginAttempt(Base):
    """
    Failed-login counters, in the database rather than in the process.

    WHY NOT AN IN-MEMORY DICT. A dict resets on restart -- so an attacker gets a
    fresh budget for free by waiting for a deploy -- and it is per-process, so
    N workers would silently multiply the limit by N. Neither is a limiter.

    WHY NOT REDIS. There is none: the deployment is `db` and `api`, and the only
    mention of Redis in this repository is the comment explaining why the job
    runner does not use it. PostgreSQL is already the application's shared,
    durable state, and adding a second store for one counter would be a new
    operational dependency to buy something the existing one already does.

    COUNTING IS ATOMIC IN SQL, never read-modify-write in Python: a single
    `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` both increments and reports
    the new value, so simultaneous attempts cannot lose an update and slip past
    the threshold. See auth/rate_limit.py.

    `bucket` is the composite key -- "ip:1.2.3.4" or "email:a@b.test" -- so one
    table serves both dimensions without a second schema.
    """
    __tablename__ = "login_attempts"

    bucket = Column(String, primary_key=True)
    #: Epoch seconds. A float rather than a DateTime deliberately: comparison
    #: and arithmetic then behave identically on SQLite and PostgreSQL, with no
    #: timezone semantics to differ between them.
    window_started_at = Column(Float, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)


class Dataset(Base):
    """Metadata registry entry — one row per ingested dataset."""
    __tablename__ = "datasets"

    id = Column(String, primary_key=True, default=gen_uuid)
    #: Who uploaded this, taken from the authenticated session at import and
    #: never from the request body. NULL means SYSTEM/PUBLIC: the published
    #: reference corpora that predate accounts, readable by any signed-in user
    #: and writable by none. Still nullable on purpose -- a NOT NULL column
    #: would force a fabricated owner onto that data. See
    #: docs/ownership-schema.md and auth/dependencies.py for the visibility rule.
    owner_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String, nullable=False, index=True)
    source = Column(String, nullable=True)          # e.g. "Zenodo", "USGS"
    source_url = Column(String, nullable=True)
    license = Column(String, nullable=True)
    sensor_type = Column(String, nullable=False, index=True)
    original_format = Column(String, nullable=False)  # segy, las, csv, geotiff, ...
    coordinate_system = Column(String, default="EPSG:4326")
    collection_date = Column(DateTime, nullable=True)
    location_description = Column(String, nullable=True)
    resolution = Column(String, nullable=True)
    depth_range_min = Column(Float, nullable=True)
    depth_range_max = Column(Float, nullable=True)
    frequency = Column(String, nullable=True)
    has_ground_truth = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    checksum = Column(String, nullable=True)
    quality_score = Column(Float, nullable=True)
    record_count = Column(Integer, default=0)
    raw_path = Column(String, nullable=True)
    processed_path = Column(String, nullable=True)
    center_lat = Column(Float, nullable=True)
    center_lon = Column(Float, nullable=True)
    extra_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    versions = relationship("DatasetVersion", back_populates="dataset", cascade="all, delete-orphan")
    owner = relationship("User", back_populates="datasets")


class ImportJob(Base):
    """
    One user-initiated dataset import, and everything the API can honestly say
    about it while it runs.

    WHY A TABLE AND NOT AN IN-MEMORY DICT. A job must not be able to vanish
    without the API being able to represent that it failed. An in-memory
    registry loses every running job on restart and reports the survivors as
    still RUNNING forever, which is a lie the interface would then repeat. The
    row survives the process; `mark_orphaned_jobs_failed()` reconciles anything
    that was RUNNING when the process died.

    STAGE, NOT PERCENTAGE. `stage` carries the name of the pipeline step the
    job is actually in -- converting, validating, persisting, registering. The
    underlying pipeline cannot report fractional completion, and inventing a
    percentage from a step count would be a fabricated measurement in a product
    whose entire argument is that it does not fabricate measurements.

    OWNERSHIP. `owner_id` is set from the authenticated session when the job is
    created, and the dataset the job produces inherits it from the job -- never
    from anything the client sent. A job with a NULL owner predates
    authentication and is nobody's to read; unlike datasets there is no
    system-owned case for jobs. See auth/dependencies.py::job_or_404.
    """
    __tablename__ = "import_jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    #: Only "dataset_import" today. Present so a second job type does not need
    #: a schema change.
    job_type = Column(String, nullable=False, default="dataset_import", index=True)
    #: QUEUED | RUNNING | SUCCEEDED | FAILED
    state = Column(String, nullable=False, default="QUEUED", index=True)
    #: The pipeline step this job is in. Never a percentage.
    stage = Column(String, nullable=True)

    #: As the client sent it -- kept verbatim for display and diagnostics.
    original_filename = Column(String, nullable=True)
    #: What we actually wrote to disk, after sanitisation.
    stored_filename = Column(String, nullable=True)
    stored_path = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)

    sensor_type = Column(String, nullable=True)
    detected_format = Column(String, nullable=True)
    #: "supported" | "recognized_unsupported" | "unknown", from the converter
    #: registry -- never a second hand-maintained list.
    format_status = Column(String, nullable=True)

    dataset_id = Column(String, nullable=True, index=True)
    #: Which stage raised, and what it said. The real backend error, never a
    #: generic apology.
    error_stage = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)

    #: Who started this import. Nullable and unset for the same reason as
    #: Dataset.owner_id: there is no authentication, so there is no identity to
    #: record. It became a real foreign key once the users table existed.
    owner_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "job_type": self.job_type,
            "state": self.state,
            "stage": self.stage,
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "size_bytes": self.size_bytes,
            "sensor_type": self.sensor_type,
            "detected_format": self.detected_format,
            "format_status": self.format_status,
            "dataset_id": self.dataset_id,
            "error_stage": self.error_stage,
            "error_message": self.error_message,
            "owner_id": self.owner_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class DatasetVersion(Base):
    """Version history for a dataset (PRD: 'Data Versioning' requirement)."""
    __tablename__ = "dataset_versions"

    id = Column(String, primary_key=True, default=gen_uuid)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False)
    version = Column(Integer, nullable=False)
    checksum = Column(String, nullable=True)
    change_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    dataset = relationship("Dataset", back_populates="versions")


class SpatialDeclaration(Base):
    """
    One asserted spatial relationship between a dataset and the physical world.

    WHY THIS IS A TABLE AND NOT A FIELD ON THE FRAME. A CRS, a vertical datum, a
    velocity or a tie is not simply a value -- it is a CLAIM somebody made, on
    some authority, at some time, which a later claim may supersede. Writing the
    value onto the frame and nothing else would lose who said it and what it
    replaced, and those are exactly the questions asked when a reconstruction
    turns out to be in the wrong place. The frame still carries the value, so
    every existing consumer keeps working; this carries the claim.

    APPEND-ONLY. A declaration is never edited or deleted: a correction is a new
    row that supersedes the old one. `superseded_at`/`superseded_by` make the
    history readable, and the audit trail survives the correction -- which is
    the whole reason a scientific platform records provenance rather than state.

    WHAT IT IS NOT. It is not a second provenance system: `value` carries the
    existing vocabulary (`CRSProvenance`, `Assumption`, `GeoTie`), and
    `schemas/provenance.py` remains the single projection consumers read. It is
    not a second versioning system either -- it records what changed and when,
    so downstream products computed before a change can be identified as stale.
    """
    __tablename__ = "spatial_declarations"

    id = Column(String, primary_key=True, default=gen_uuid)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False, index=True)
    #: NULL means "every frame in the dataset". A survey line's CRS is usually a
    #: property of the whole acquisition, but a tie is emphatically not.
    frame_id = Column(String, nullable=True, index=True)

    #: crs | vertical_datum | antenna_offset | depth_conversion | geo_tie |
    #: surface_reference. See schemas/spatial_reference.py::DeclarationKind.
    kind = Column(String, nullable=False, index=True)
    #: The declaration's payload, in the kind's own shape.
    value = Column(JSON, nullable=False, default=dict)

    #: WHO ASSERTED THIS, in their own words -- "site survey 2019-03-20",
    #: "PDOK documentation for AHN". Required: a spatial claim with no
    #: attribution is indistinguishable from a guess, which is the failure this
    #: whole table exists to prevent.
    supplied_by = Column(String, nullable=False)
    note = Column(Text, nullable=True)

    #: The account that made the declaration, from the session -- never from the
    #: request body. Distinct from `supplied_by`, which names the AUTHORITY: the
    #: person typing may be relaying a surveyor's measurement.
    declared_by_user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    superseded_at = Column(DateTime, nullable=True)
    superseded_by = Column(String, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dataset_id": self.dataset_id,
            "frame_id": self.frame_id,
            "kind": self.kind,
            "value": self.value,
            "supplied_by": self.supplied_by,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "superseded_at": self.superseded_at.isoformat() if self.superseded_at else None,
            "superseded_by": self.superseded_by,
            "active": self.superseded_at is None,
        }


class FusionSample(Base):
    """
    A multimodal fusion sample: multiple datasets matched to one location.

    The centre is stored in whatever frame the sample was clustered in.
    center_lat/center_lon were NOT NULL, which meant a sample from any
    non-geographic frame either could not be persisted at all or had to be
    given placeholder coordinates -- the exact failure the Position
    abstraction exists to prevent, reintroduced at the storage layer. They
    are now nullable, and `spatial_ref_kind` says which pair is meaningful.
    """
    __tablename__ = "fusion_samples"

    id = Column(String, primary_key=True, default=gen_uuid)
    #: Which frame this sample's centre lives in: "geographic", "projected",
    #: "local_cartesian", "odometry". Determines which centre columns apply.
    spatial_ref_kind = Column(String, nullable=False, default="geographic")
    #: Populated for geographic samples only.
    center_lat = Column(Float, nullable=True)
    center_lon = Column(Float, nullable=True)
    #: Populated for samples clustered in native units (metres) instead.
    center_x = Column(Float, nullable=True)
    center_y = Column(Float, nullable=True)
    radius_m = Column(Float, nullable=False)
    #: How many member records reached this centre through a CRS transform
    #: rather than carrying a geographic coordinate of their own. Non-zero
    #: means the centre is only as trustworthy as the CRS that was declared.
    n_reprojected = Column(Integer, nullable=False, default=0)
    dataset_ids = Column(JSON, default=list)   # list of Dataset.id included in this sample
    sensor_types = Column(JSON, default=list)  # sensors represented
    has_ground_truth = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class BenchmarkRun(Base):
    """Results of running a model against a dataset/fusion sample set (Phase 2 hookup point)."""
    __tablename__ = "benchmark_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    model_name = Column(String, nullable=False)
    dataset_id = Column(String, nullable=True)
    metrics = Column(JSON, default=dict)  # precision, recall, f1, depth_error, inference_ms, ...
    created_at = Column(DateTime, default=datetime.utcnow)
