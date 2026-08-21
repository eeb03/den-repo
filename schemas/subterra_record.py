"""
The Universal Subterra Record: every dataset, regardless of original
format (SEG-Y, LAS, CSV, GeoTIFF, MiniSEED, XYZ, ...), converts into
this one structure before it ever touches a model.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from schemas.spatial import GeographicPosition, NoPosition, Position, PositionKind


class SensorType(str, Enum):
    GPR = "gpr"
    SEISMIC = "seismic"
    MAGNETOMETER = "magnetometer"
    ERT = "ert"                 # electrical resistivity tomography
    GRAVITY = "gravity"
    LIDAR = "lidar"
    DEM = "dem"
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


#: Reason attached to positions derived from the legacy (0.0, 0.0)
#: placeholder that converters wrote before `position` existed.
LEGACY_PLACEHOLDER_REASON = (
    "legacy placeholder coordinates (0.0, 0.0) written before an explicit "
    "position was representable; not an actual position"
)

#: Used when a caller supplies neither coordinates nor a position. Absence is
#: recorded as a declaration rather than left as an unset field.
NO_COORDINATES_SUPPLIED = "no coordinates or position were supplied for this sample"


class SubterraRecord(BaseModel):
    """One sensor observation in the unified format.

    POSITION (see schemas/spatial.py): `position` is REQUIRED and is the
    authoritative statement of where -- or whether -- this sample is
    located. Its legal values include `NoPosition`, so "we have no
    horizontal position" is something a converter declares deliberately
    rather than something that happens by omission.

    `latitude`/`longitude` are now a DERIVED VIEW of `position`, not an
    independent field, and they are optional. They are populated only when
    the sample genuinely has a geographic position; a projected, odometry,
    or unpositioned sample leaves them None rather than carrying the (0.0,
    0.0) placeholder converters used to invent to satisfy a required field.

    That placeholder was not harmless. It made "at 0N 0E" and "position
    unknown" the same value, produced a fabricated 0.0 m lateral extent in
    the evidence tier, and clustered every unpositioned dataset together off
    the coast of Africa during fusion. Two separate bugs in one session
    traced back to code trying to tell the two apart after the fact.

    Compatibility runs BOTH ways, so existing code keeps working:
    constructing a record with latitude/longitude derives the matching
    GeographicPosition, and constructing one with a GeographicPosition fills
    latitude/longitude in. Only non-geographic samples see None -- which is
    the point.
    """

    dataset_id: str = Field(..., description="Parent dataset identifier")
    sensor_type: SensorType
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    position: Position = Field(
        ...,
        description="Explicit spatial position; auto-derived from latitude/longitude when not supplied",
    )
    registered_position: Optional[Position] = Field(
        None,
        description=(
            "Where a GeoTie REGISTERS this sample, when one has been supplied. Additive: "
            "`position` keeps the acquisition's own coordinate untouched, so registration "
            "can be re-done, corrected, or discarded without data loss."
        ),
    )
    frame_id: Optional[str] = Field(
        None, description="SurveyFrame this sample belongs to (schemas/survey_frame.py)"
    )
    elevation: Optional[float] = Field(None, description="meters above sea level")
    timestamp: Optional[datetime] = None
    depth: Optional[float] = Field(None, description="meters below surface, positive down")
    signal: list[float] = Field(default_factory=list, description="raw or processed trace/measurement")
    metadata: dict[str, Any] = Field(default_factory=dict)
    ground_truth: GroundTruthLabel = GroundTruthLabel.NONE
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)

    @model_validator(mode="before")
    @classmethod
    def _derive_position_from_legacy_coords(cls, data: Any) -> Any:
        """
        Fills in `position` from latitude/longitude when a caller doesn't
        supply one, so that adding a required field breaks no existing
        converter, test, or stored JSONL file.

        The exact-(0.0, 0.0) case maps to `NoPosition` rather than to a
        geographic position at null island. That is a narrow, deliberate
        heuristic covering the placeholder SEGYConverter wrote for every
        un-georeferenced trace: without it, ~5.17M already-stored INGV
        records would load as if they claimed a real position in the Gulf
        of Guinea. The cost is that a survey genuinely at 0N 0E would be
        mislabelled; that is open ocean, and any converter that knows
        better sets `position` explicitly and bypasses this entirely.
        """
        if not isinstance(data, dict):
            return data
        position = data.get("position")

        if position is not None:
            # position -> latitude/longitude, so consumers that still read the
            # legacy fields keep working for geographic data.
            if data.get("latitude") is None and data.get("longitude") is None:
                kind = (position.get("kind") if isinstance(position, dict)
                        else getattr(position, "kind", None))
                if kind == PositionKind.GEOGRAPHIC:
                    lat = (position.get("lat") if isinstance(position, dict)
                           else position.lat)
                    lon = (position.get("lon") if isinstance(position, dict)
                           else position.lon)
                    data = dict(data)
                    data["latitude"], data["longitude"] = lat, lon
            return data

        # latitude/longitude -> position, for callers that supply only the
        # legacy fields.
        lat, lon = data.get("latitude"), data.get("longitude")
        if lat is None or lon is None:
            data = dict(data)
            data["position"] = NoPosition(reason=NO_COORDINATES_SUPPLIED)
            return data
        try:
            lat_f, lon_f = float(lat), float(lon)
        except (TypeError, ValueError):
            return data  # let the normal type error surface
        data = dict(data)
        if lat_f == 0.0 and lon_f == 0.0:
            data["position"] = NoPosition(reason=LEGACY_PLACEHOLDER_REASON)
        else:
            data["position"] = GeographicPosition(lat=lat_f, lon=lon_f)
        return data

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
