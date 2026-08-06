"""
Converts CSV / XYZ tabular sensor data (magnetometer, gravity, ERT, GPS/IMU)
into Universal Subterra Records.

Expected/auto-detected columns (case-insensitive, flexible aliases):
  latitude/lat/y, longitude/lon/lng/x, elevation/elev/z, depth,
  timestamp/time/date, signal/value/reading/measurement, and any
  remaining columns are folded into `metadata`.

COORDINATES. A CSV carries no CRS declaration, so its latitude/longitude
columns are ASSUMED to be WGS84 -- recorded as an unverified assumption on
the frame rather than left implicit. Note the `x`/`y` aliases: a table whose
x/y are actually projected coordinates would be misread as lon/lat, and
(like the LAS case) would fail the schema's range check. Column-detection
behaviour is UNCHANGED in this milestone; see the frame's `crs` assumption.
"""
from pathlib import Path

import pandas as pd

from converters.base import BaseConverter, ConversionResult
from schemas.spatial import (
    Assumption, AxisKind, CRSKind, SpatialRef, VerticalAxis, crs_kind_for_positions,
)
from schemas.subterra_record import SubterraRecord, SensorType
from schemas.survey_frame import SurveyFrame, make_frame_id
from utils.logger import get_logger

logger = get_logger(__name__)

_COLUMN_ALIASES = {
    "latitude": ["latitude", "lat", "y"],
    "longitude": ["longitude", "lon", "lng", "long", "x"],
    "elevation": ["elevation", "elev", "z", "altitude"],
    "depth": ["depth", "z_depth"],
    "timestamp": ["timestamp", "time", "date", "datetime"],
    "signal": ["signal", "value", "reading", "measurement", "amplitude", "anomaly"],
}


def _find_column(columns: list[str], aliases: list[str]) -> str | None:
    lower_map = {c.lower(): c for c in columns}
    for alias in aliases:
        if alias in lower_map:
            return lower_map[alias]
    return None


class CSVConverter(BaseConverter):
    format_name = "csv"
    supported_extensions = (".csv", ".xyz", ".tsv")

    def convert(
        self, path: str | Path, dataset_id: str, sensor_type: SensorType, **kwargs
    ) -> list[SubterraRecord]:
        """Records only. See `load()` for records plus the file's SurveyFrame."""
        return self.load(path, dataset_id=dataset_id, sensor_type=sensor_type, **kwargs).records

    def load(
        self, path: str | Path, dataset_id: str, sensor_type: SensorType, **kwargs
    ) -> ConversionResult:
        path = Path(path)
        sep = "\t" if path.suffix.lower() == ".tsv" else None
        # XYZ files are typically whitespace-delimited with no header
        if path.suffix.lower() == ".xyz":
            df = pd.read_csv(path, delim_whitespace=True, header=None)
            df.columns = ["longitude", "latitude", "signal"][: len(df.columns)]
        else:
            df = pd.read_csv(path, sep=sep, engine="python")

        columns = list(df.columns)
        col_lat = _find_column(columns, _COLUMN_ALIASES["latitude"])
        col_lon = _find_column(columns, _COLUMN_ALIASES["longitude"])
        col_elev = _find_column(columns, _COLUMN_ALIASES["elevation"])
        col_depth = _find_column(columns, _COLUMN_ALIASES["depth"])
        col_time = _find_column(columns, _COLUMN_ALIASES["timestamp"])
        col_signal = _find_column(columns, _COLUMN_ALIASES["signal"])

        if col_lat is None or col_lon is None:
            raise ValueError(
                f"{path.name}: could not detect latitude/longitude columns "
                f"(found columns: {columns})"
            )

        used_cols = {c for c in [col_lat, col_lon, col_elev, col_depth, col_time, col_signal] if c}
        meta_cols = [c for c in columns if c not in used_cols]

        records: list[SubterraRecord] = []
        for _, row in df.iterrows():
            try:
                lat = float(row[col_lat])
                lon = float(row[col_lon])
            except (ValueError, TypeError):
                continue  # skip malformed rows rather than fail the whole dataset

            timestamp = None
            if col_time:
                try:
                    timestamp = pd.to_datetime(row[col_time], errors="coerce")
                    if pd.isna(timestamp):
                        timestamp = None
                except Exception:
                    timestamp = None

            signal = []
            if col_signal is not None:
                try:
                    signal = [float(row[col_signal])]
                except (ValueError, TypeError):
                    signal = []

            metadata = {c: row[c] for c in meta_cols if pd.notna(row[c])}

            records.append(
                SubterraRecord(
                    dataset_id=dataset_id,
                    sensor_type=sensor_type,
                    latitude=lat,
                    longitude=lon,
                    frame_id=make_frame_id(dataset_id, path.name),
                    elevation=float(row[col_elev]) if col_elev and pd.notna(row[col_elev]) else None,
                    depth=float(row[col_depth]) if col_depth and pd.notna(row[col_depth]) else None,
                    timestamp=timestamp,
                    signal=signal,
                    metadata=metadata,
                )
            )

        has_depth = col_depth is not None and any(r.depth is not None for r in records)
        kind = crs_kind_for_positions(r.position.kind for r in records)
        frame = SurveyFrame(
            frame_id=make_frame_id(dataset_id, path.name),
            dataset_id=dataset_id,
            modality=sensor_type,
            modality_source="user_supplied",
            source_format=self.format_name,
            source_file=path.name,
            spatial_ref=SpatialRef(
                kind=kind,
                code="EPSG:4326" if kind == CRSKind.GEOGRAPHIC else None,
                name="latitude/longitude columns; a CSV declares no coordinate system",
                horizontal_units="deg" if kind == CRSKind.GEOGRAPHIC else "m",
            ),
            vertical_axis=VerticalAxis(
                kind=AxisKind.DEPTH_M if has_depth else AxisKind.NONE,
                units="m" if has_depth else "",
                origin="unrecorded (a CSV declares no vertical datum)",
                positive_down=True,
                n_samples=1,
            ),
            n_positions=len(records),
            position_index_name="row",
            assumptions=[
                Assumption(
                    key="crs", value="EPSG:4326" if kind == CRSKind.GEOGRAPHIC else None,
                    basis="ASSUMED: the file's latitude/longitude columns carry no CRS declaration",
                    verified=False,
                )
            ],
            source_metadata={
                "columns": columns,
                "detected_columns": {
                    "latitude": col_lat, "longitude": col_lon, "elevation": col_elev,
                    "depth": col_depth, "timestamp": col_time, "signal": col_signal,
                },
                "row_count": int(len(df)),
            },
        )

        logger.info(f"CSVConverter: parsed {len(records)}/{len(df)} rows from {path.name}")
        return ConversionResult(records=records, frames=[frame])
