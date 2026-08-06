"""
Converts CSV / XYZ tabular sensor data (magnetometer, gravity, ERT, GPS/IMU)
into Universal Subterra Records.

Expected/auto-detected columns (case-insensitive, flexible aliases):
  latitude/lat/y, longitude/lon/lng/x, elevation/elev/z, depth,
  timestamp/time/date, signal/value/reading/measurement, and any
  remaining columns are folded into `metadata`.

COORDINATES. A CSV carries no CRS declaration, so what its coordinate
columns MEAN cannot be read from the file. Two cases are distinguished
rather than conflated:

- columns named latitude/lat/longitude/lon are geographic by their own
  naming, and are assumed WGS84 -- recorded as an unverified assumption.
- columns named x/y are AMBIGUOUS. They are lon/lat in one table and
  projected easting/northing in the next, and nothing in the file says
  which.

Values are range-checked to tell them apart. A table whose x/y fall outside
WGS84 range is projected, and was previously read as lon/lat anyway --
failing with an opaque "2 validation errors for SubterraRecord" from the
schema's range check, the same defect LASConverter had. Such a file now
either uses an explicitly supplied `crs` (native easting/northing preserved
as ProjectedPosition, latitude/longitude derived by reprojection) or is
rejected with a message naming the problem.

Nothing is inferred about a CRS: as with SEG-Y, `crs` is a caller
declaration and there is no default.
"""
from pathlib import Path

import pandas as pd

from converters.base import BaseConverter, ConversionResult, MissingDependencyError
from schemas.spatial import (
    Assumption, AxisKind, CRSKind, CRSProvenance, GeographicPosition, ProjectedPosition,
    SpatialRef, VerticalAxis, crs_kind_for_positions,
)
from schemas.subterra_record import SubterraRecord, SensorType
from schemas.survey_frame import SurveyFrame, make_frame_id
from utils.logger import get_logger

logger = get_logger(__name__)

#: Aliases that NAME the column geographic. Matching one of these is itself
#: evidence of intent, which x/y is not.
_GEOGRAPHIC_ALIASES = {"latitude", "lat", "longitude", "lon", "lng", "long"}

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


def _matched_alias(columns: list[str], aliases: list[str]) -> str | None:
    """Which alias actually matched -- 'lat' and 'y' mean different things."""
    lower_map = {c.lower(): c for c in columns}
    for alias in aliases:
        if alias in lower_map:
            return alias
    return None


def _parse_declared_crs(crs, name):
    """Parses a CRS the CALLER declared. Never guesses; fails loudly instead."""
    try:
        from rasterio.crs import CRS
    except ImportError as e:
        raise MissingDependencyError(
            "rasterio is required to use an explicitly supplied CRS. "
            "Install with: pip install rasterio"
        ) from e
    if not str(crs).strip():
        raise ValueError(
            f"{name}: crs was supplied but is empty. Either omit it or give an "
            f"unambiguous identifier such as 'EPSG:32633'."
        )
    try:
        return CRS.from_user_input(crs)
    except Exception as e:
        raise ValueError(
            f"{name}: could not interpret the supplied crs={crs!r}. Give an unambiguous "
            f"identifier such as 'EPSG:32633'."
        ) from e


class CSVConverter(BaseConverter):
    format_name = "csv"
    supported_extensions = (".csv", ".xyz", ".tsv")

    @staticmethod
    def _spatial_ref(kind, declared_crs, crs_input, col_lat, col_lon, named_geographic):
        if declared_crs is not None:
            epsg = declared_crs.to_epsg()
            geographic = declared_crs.is_geographic
            return SpatialRef(
                kind=CRSKind.GEOGRAPHIC if geographic else CRSKind.PROJECTED,
                code=f"EPSG:{epsg}" if epsg else declared_crs.to_string(),
                crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER,
                name=(
                    f"columns {col_lat!r}/{col_lon!r}. A CSV DECLARES NO CRS; "
                    f"{crs_input!r} was supplied externally as ingest configuration "
                    f"and applies to this dataset only."
                ),
                horizontal_units="deg" if geographic else "m",
            )
        return SpatialRef(
            kind=kind,
            code="EPSG:4326" if kind == CRSKind.GEOGRAPHIC else None,
            crs_provenance=(CRSProvenance.INFERRED if kind == CRSKind.GEOGRAPHIC
                            else CRSProvenance.NONE),
            name=(
                f"columns {col_lat!r}/{col_lon!r}; a CSV declares no coordinate system"
                + ("" if named_geographic else
                   ". These are the AMBIGUOUS x/y names, read as lon/lat only because "
                   "their values fall in WGS84 range")
            ),
            horizontal_units="deg" if kind == CRSKind.GEOGRAPHIC else "m",
        )

    @staticmethod
    def _crs_assumption(declared_crs, crs_input, named_geographic, col_lat, col_lon):
        if declared_crs is not None:
            return Assumption(
                key="crs_supplied_by_caller", value=crs_input,
                basis=(
                    "A CSV has no field for a coordinate reference system, so this was "
                    "asserted as ingest configuration for this dataset. It is NOT declared "
                    "by the file and NOT inferred from the data."
                ),
                verified=False,
            )
        return Assumption(
            key="crs", value="EPSG:4326",
            basis=(
                "ASSUMED: the file carries no CRS declaration and its coordinate values "
                "fall within WGS84 range"
                + ("" if named_geographic else
                   f", but columns {col_lat!r}/{col_lon!r} are the ambiguous x/y names, "
                   f"which are projected easting/northing in many tables. Supply crs= "
                   f"explicitly if that is the case here")
            ),
            verified=False,
        )

    @staticmethod
    def _reproject(declared_crs, pairs):
        """Derives (lat, lon) for each (northing, easting) pair."""
        from rasterio.warp import transform as rio_transform

        if not pairs:
            return []
        eastings = [b for _a, b in pairs]
        northings = [a for a, _b in pairs]
        lons, lats = rio_transform(declared_crs, "EPSG:4326", eastings, northings)
        return list(zip(lats, lons))

    def convert(
        self, path: str | Path, dataset_id: str, sensor_type: SensorType,
        crs: str | None = None, **kwargs
    ) -> list[SubterraRecord]:
        """Records only. See `load()` for records plus the file's SurveyFrame."""
        return self.load(path, dataset_id=dataset_id, sensor_type=sensor_type,
                         crs=crs, **kwargs).records

    def load(
        self, path: str | Path, dataset_id: str, sensor_type: SensorType,
        crs: str | None = None, **kwargs
    ) -> ConversionResult:
        """
        `crs` is an EXPLICIT declaration of what the coordinate columns hold.
        Required when they are projected, since a CSV declares nothing and
        nothing here infers one.
        """
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

        # Are these columns named geographic, or the ambiguous x/y?
        lat_alias = _matched_alias(columns, _COLUMN_ALIASES["latitude"])
        lon_alias = _matched_alias(columns, _COLUMN_ALIASES["longitude"])
        named_geographic = (lat_alias in _GEOGRAPHIC_ALIASES
                            and lon_alias in _GEOGRAPHIC_ALIASES)

        # Range-check the actual values before deciding what they are.
        pairs = []
        for _, row in df.iterrows():
            try:
                pairs.append((float(row[col_lat]), float(row[col_lon])))
            except (ValueError, TypeError):
                pairs.append(None)   # malformed row; skipped below
        valid = [p for p in pairs if p is not None]
        in_wgs84_range = all(
            -90.0 <= a <= 90.0 and -180.0 <= b <= 180.0 for a, b in valid
        ) if valid else True

        declared_crs = _parse_declared_crs(crs, path.name) if crs is not None else None
        projected = declared_crs is not None and not declared_crs.is_geographic
        if projected:
            reprojected = self._reproject(declared_crs, valid)
        elif not in_wgs84_range:
            raise ValueError(
                f"{path.name}: coordinate columns {col_lat!r}/{col_lon!r} contain values "
                f"outside WGS84 lon/lat range, so they are projected, not geographic. "
                f"A CSV declares no coordinate system, so supply one explicitly "
                f"(crs='EPSG:...') to have them read as easting/northing. "
                f"Reading them as latitude/longitude would place the survey somewhere it "
                f"is not."
            )
        else:
            reprojected = None

        records: list[SubterraRecord] = []
        valid_index = -1
        for row_index, (_, row) in enumerate(df.iterrows()):
            if pairs[row_index] is None:
                continue  # skip malformed rows rather than fail the whole dataset
            valid_index += 1
            raw_a, raw_b = pairs[row_index]
            if projected:
                # Native easting/northing stay authoritative; lat/lon derived.
                position = ProjectedPosition(easting=raw_b, northing=raw_a)
                lat, lon = reprojected[valid_index]
            else:
                lat, lon = raw_a, raw_b
                position = GeographicPosition(lat=lat, lon=lon)

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
                    position=position,
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
            spatial_ref=self._spatial_ref(kind, declared_crs, crs, col_lat, col_lon,
                                          named_geographic),
            vertical_axis=VerticalAxis(
                kind=AxisKind.DEPTH_M if has_depth else AxisKind.NONE,
                units="m" if has_depth else "",
                origin="unrecorded (a CSV declares no vertical datum)",
                positive_down=True,
                n_samples=1,
            ),
            n_positions=len(records),
            position_index_name="row",
            assumptions=[self._crs_assumption(declared_crs, crs, named_geographic,
                                              col_lat, col_lon)],
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
