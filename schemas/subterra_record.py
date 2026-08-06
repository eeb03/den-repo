"""
The Universal Subterra Record: every dataset, regardless of original
format (SEG-Y, LAS, CSV, GeoTIFF, MiniSEED, XYZ, ...), converts into
this one structure before it ever touches a model.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class SensorType(str, Enum):
    GPR = "gpr"
    SEISMIC = "seismic"
    MAGNETOMETER = "magnetometer"
    ERT = "ert"                 # electrical resistivity tomography
    GRAVITY = "gravity"
    LIDAR = "lidar"
    SATELLITE = "satellite"
    GPS = "gps"
    IMU = "imu"


class GroundTruthLabel(str, Enum):
    PIPE = "pipe"
    CABLE = "cable"
    TUNNEL = "tunnel"
    CAVITY = "cavity"
    VOID = "void"
    ROCK = "rock"
    MINERAL = "mineral"
    ORE = "ore"
    GROUNDWATER = "groundwater"
    ARCHAEOLOGICAL_OBJECT = "archaeological_object"
    CONCRETE = "concrete"
    REBAR = "rebar"
    UTILITY_LINE = "utility_line"
    MINE = "mine"
    UNEXPLODED_ORDNANCE = "unexploded_ordnance"
    UNKNOWN_ANOMALY = "unknown_anomaly"
    NONE = "none"


class SubterraRecord(BaseModel):
    """One georeferenced sensor observation in the unified format."""

    dataset_id: str = Field(..., description="Parent dataset identifier")
    sensor_type: SensorType
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    elevation: Optional[float] = Field(None, description="meters above sea level")
    timestamp: Optional[datetime] = None
    depth: Optional[float] = Field(None, description="meters below surface, positive down")
    signal: list[float] = Field(default_factory=list, description="raw or processed trace/measurement")
    metadata: dict[str, Any] = Field(default_factory=dict)
    ground_truth: GroundTruthLabel = GroundTruthLabel.NONE
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)

    @field_validator("signal")
    @classmethod
    def signal_must_be_finite(cls, v: list[float]) -> list[float]:
        import math

        for x in v:
            if x is not None and (math.isnan(x) or math.isinf(x)):
                raise ValueError("signal contains NaN/Inf values; run preprocessing before ingest")
        return v

    def to_flat_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        d["sensor_type"] = self.sensor_type.value
        d["ground_truth"] = self.ground_truth.value
        d["timestamp"] = self.timestamp.isoformat() if self.timestamp else None
        return d


class DatasetQualityReport(BaseModel):
    dataset_id: str
    checksum: str
    record_count: int
    missing_coordinates: int = 0
    missing_timestamps: int = 0
    missing_depth: int = 0
    invalid_signal_count: int = 0
    coordinate_bounds_valid: bool = True
    quality_score: float = Field(0.0, ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)
