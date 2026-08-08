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
    A platform account. THE TABLE EXISTS; AUTHENTICATION DOES NOT.

    This is deliberately schema-only. Nothing creates a row, nothing reads one,
    and no request is associated with a user, because the platform has no login
    and inventing an identity to fill a column would be worse than leaving it
    empty -- it would make every dataset look owned by someone who does not
    exist, and later make it impossible to tell real ownership from the
    placeholder.

    It is created now so that ownership can be added to `datasets` while the
    table is empty and the change is free. Adding a foreign key to a populated
    table, after users exist, means deciding retroactively who owns data that
    was uploaded by nobody -- a question with no correct answer.

    No password column is present, and that is intentional too: the credential
    model (password hash, OIDC subject, API token) is a decision for the
    authentication task, and guessing at it here would bake in a choice that
    task should make.
    """
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    #: Login identifier. Unique so the constraint exists before any row does.
    email = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    datasets = relationship("Dataset", back_populates="owner")


class Dataset(Base):
    """Metadata registry entry — one row per ingested dataset."""
    __tablename__ = "datasets"

    id = Column(String, primary_key=True, default=gen_uuid)
    #: Who uploaded this. NULL means "uploaded before ownership existed, or by
    #: an unauthenticated caller" -- which is every row today. It is nullable
    #: on purpose: the platform is still single-user, and a NOT NULL column
    #: would force a fabricated owner onto historical data. Nothing reads this
    #: yet and no request sets it; see docs/ownership-schema.md.
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

    OWNERSHIP. `owner_id` is nullable and unenforced. It exists so that the
    import path is not the thing that has to be retrofitted when authentication
    lands. `Dataset` now carries the matching column, added to existing
    databases by database/migrations.py -- `create_all` cannot alter a table
    that already exists. See docs/ownership-schema.md.
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
