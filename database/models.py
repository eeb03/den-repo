import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, DateTime, JSON, Boolean, ForeignKey, Text
)
from sqlalchemy.orm import relationship

from database.session import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Dataset(Base):
    """Metadata registry entry — one row per ingested dataset."""
    __tablename__ = "datasets"

    id = Column(String, primary_key=True, default=gen_uuid)
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
