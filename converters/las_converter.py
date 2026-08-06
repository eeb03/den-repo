"""
Converts LAS/LAZ LiDAR point clouds into Universal Subterra Records plus one
SurveyFrame per file. Points are optionally downsampled (`max_points`) since
raw point clouds can run into the hundreds of millions of points.

COORDINATES. LAS point clouds are usually delivered in a PROJECTED CRS
(UTM, a state plane), not in lat/lon. This converter previously wrote
`latitude=y, longitude=x` straight from the file, which meant any real
projected cloud failed ingest outright: a UTM northing of 4,544,705 does
not satisfy `latitude <= 90`, so pydantic raised two validation errors and
the whole dataset was rejected. The path had no test coverage, so the
failure was never visible.

Now the file's own CRS decides:
  - projected CRS  -> `position` holds native easting/northing as a
                      ProjectedPosition, and latitude/longitude are filled
                      by reprojecting to EPSG:4326 (rasterio, the same
                      mechanism GeoTIFFConverter already uses)
  - geographic CRS -> used directly
  - no CRS declared -> coordinates are trusted as lat/lon only if they are
                      actually in WGS84 range; otherwise the file is
                      rejected with an explicit message rather than a bare
                      range error. Such a file cannot be represented until
                      latitude/longitude become optional, which is a later
                      milestone.

The CRS is read from the LAS WKT VLR directly rather than via
`laspy.LasHeader.parse_crs()`, which requires pyproj (not a dependency
here); rasterio parses the WKT and performs the transform.

Requires the optional `laspy` dependency; `rasterio` additionally when a
projected CRS has to be reprojected.
"""
from pathlib import Path

import numpy as np

from converters.base import BaseConverter, ConversionResult, MissingDependencyError
from schemas.spatial import (
    Assumption, AxisKind, CRSKind, GeographicPosition, ProjectedPosition,
    SpatialRef, VerticalAxis, crs_kind_for_positions,
)
from schemas.subterra_record import SubterraRecord, SensorType
from schemas.survey_frame import SurveyFrame, make_frame_id
from utils.logger import get_logger

logger = get_logger(__name__)


def _read_wkt(las) -> str | None:
    """Pulls the coordinate-system WKT out of the LAS VLRs, or None if absent."""
    try:
        from laspy.vlrs.known import WktCoordinateSystemVlr
    except ImportError:  # pragma: no cover - laspy import already guarded upstream
        return None
    for vlr in las.header.vlrs:
        if isinstance(vlr, WktCoordinateSystemVlr) and vlr.string:
            return vlr.string
    return None


def _parse_crs(wkt: str):
    """Parses WKT via rasterio (pyproj is not a dependency of this project)."""
    try:
        from rasterio.crs import CRS
    except ImportError as e:
        raise MissingDependencyError(
            "rasterio is required to interpret the coordinate system of a LAS file. "
            "Install with: pip install rasterio"
        ) from e
    return CRS.from_wkt(wkt)


class LASConverter(BaseConverter):
    format_name = "las"
    supported_extensions = (".las", ".laz")

    def convert(
        self,
        path: str | Path,
        dataset_id: str,
        sensor_type: SensorType,
        max_points: int = 200_000,
    ) -> list[SubterraRecord]:
        """Records only. See `load()` for records plus the file's SurveyFrame."""
        return self.load(
            path, dataset_id=dataset_id, sensor_type=sensor_type, max_points=max_points
        ).records

    def load(
        self,
        path: str | Path,
        dataset_id: str,
        sensor_type: SensorType,
        max_points: int = 200_000,
        **kwargs,
    ) -> ConversionResult:
        try:
            import laspy
        except ImportError as e:
            raise MissingDependencyError(
                "laspy is required to convert LAS/LAZ files. Install with: pip install laspy"
            ) from e

        path = Path(path)
        las = laspy.read(str(path))

        n = len(las.points)
        if n > max_points:
            idx = np.random.default_rng(42).choice(n, size=max_points, replace=False)
            idx.sort()
        else:
            idx = np.arange(n)

        xs = np.asarray(las.x)[idx]
        ys = np.asarray(las.y)[idx]
        zs = np.asarray(las.z)[idx]
        intensity = np.asarray(las.intensity)[idx] if "intensity" in las.point_format.dimension_names else None

        wkt = _read_wkt(las)
        crs = _parse_crs(wkt) if wkt else None
        lats, lons, positions, assumptions = self._resolve_coordinates(path, crs, wkt, xs, ys)

        records: list[SubterraRecord] = []
        for i, pi in enumerate(idx):
            records.append(
                SubterraRecord(
                    dataset_id=dataset_id,
                    sensor_type=sensor_type,
                    latitude=float(lats[i]),
                    longitude=float(lons[i]),
                    position=positions[i],
                    frame_id=make_frame_id(dataset_id, path.name),
                    elevation=float(zs[i]),
                    signal=[float(intensity[i])] if intensity is not None else [],
                    metadata={
                        "point_index": int(pi),
                        "downsampled": n > max_points,
                        "source_point_count": n,
                    },
                )
            )

        frame = SurveyFrame(
            frame_id=make_frame_id(dataset_id, path.name),
            dataset_id=dataset_id,
            modality=sensor_type,
            modality_source="user_supplied",
            source_format=self.format_name,
            source_file=path.name,
            spatial_ref=self._spatial_ref(crs, wkt, positions),
            vertical_axis=VerticalAxis(
                kind=AxisKind.ELEVATION_M,
                units="m",
                origin=(
                    f"vertical component of {crs.to_string()}" if crs is not None
                    else "unrecorded (LAS file declares no coordinate system)"
                ),
                positive_down=False,
                n_samples=1,
            ),
            n_positions=len(records),
            position_index_name="point_index",
            assumptions=assumptions,
            source_metadata={
                "las_version": str(las.header.version),
                "point_format": int(las.header.point_format.id),
                "source_point_count": n,
                "downsampled": n > max_points,
                "max_points": max_points,
                "crs_wkt": wkt,
            },
        )

        logger.info(
            f"LASConverter: parsed {len(records)}/{n} points from {path.name} "
            f"(downsampled={n > max_points}, crs={crs.to_string() if crs is not None else 'undeclared'})"
        )
        return ConversionResult(records=records, frames=[frame])

    def _resolve_coordinates(self, path, crs, wkt, xs, ys):
        """
        Returns (lats, lons, positions, assumptions).

        `positions` is the authoritative statement of where each point is;
        `lats`/`lons` are the legacy WGS84 view, reprojected when needed.
        """
        assumptions: list[Assumption] = []

        if crs is not None and crs.is_geographic:
            assumptions.append(Assumption(
                key="crs", value=crs.to_string(),
                basis="declared by the LAS WKT VLR", verified=True))
            positions = [GeographicPosition(lat=float(y), lon=float(x)) for x, y in zip(xs, ys)]
            return ys, xs, positions, assumptions

        if crs is not None:
            try:
                from rasterio.warp import transform as rio_transform
            except ImportError as e:
                raise MissingDependencyError(
                    "rasterio is required to reproject a projected LAS file to WGS84. "
                    "Install with: pip install rasterio"
                ) from e
            lons, lats = rio_transform(crs, "EPSG:4326", list(xs), list(ys))
            assumptions.append(Assumption(
                key="crs", value=crs.to_string(),
                basis="declared by the LAS WKT VLR", verified=True))
            assumptions.append(Assumption(
                key="reprojection", value=f"{crs.to_string()} -> EPSG:4326",
                basis="rasterio.warp.transform; latitude/longitude are derived, position is native",
                verified=True))
            positions = [ProjectedPosition(easting=float(x), northing=float(y)) for x, y in zip(xs, ys)]
            return np.asarray(lats), np.asarray(lons), positions, assumptions

        # No CRS declared. Trust the coordinates as lat/lon only if they
        # could actually BE lat/lon; never assume it for projected-looking values.
        in_range = bool(
            np.all(np.abs(np.asarray(ys)) <= 90.0) and np.all(np.abs(np.asarray(xs)) <= 180.0)
        )
        if in_range:
            assumptions.append(Assumption(
                key="crs", value="EPSG:4326",
                basis="ASSUMED: the LAS file declares no coordinate system, but its "
                      "coordinates fall within WGS84 lon/lat range",
                verified=False))
            positions = [GeographicPosition(lat=float(y), lon=float(x)) for x, y in zip(xs, ys)]
            return ys, xs, positions, assumptions

        raise ValueError(
            f"{path.name}: coordinates are outside WGS84 lon/lat range "
            f"(x {float(np.min(xs)):.1f}..{float(np.max(xs)):.1f}, "
            f"y {float(np.min(ys)):.1f}..{float(np.max(ys)):.1f}), which means they are "
            "projected -- but the file declares no coordinate system, so they cannot be "
            "reprojected to the latitude/longitude this schema still requires. Add a CRS "
            "to the file, or wait for latitude/longitude to become optional."
        )

    def _spatial_ref(self, crs, wkt, positions) -> SpatialRef:
        kind = crs_kind_for_positions(p.kind for p in positions)
        if crs is not None:
            epsg = crs.to_epsg()
            return SpatialRef(
                kind=kind,
                code=f"EPSG:{epsg}" if epsg else None,
                name=crs.to_string(),
                horizontal_units="deg" if crs.is_geographic else "m",
            )
        return SpatialRef(
            kind=kind,
            code="EPSG:4326" if kind == CRSKind.GEOGRAPHIC else None,
            name="LAS file declares no coordinate system; coordinates were in WGS84 range",
            horizontal_units="deg" if kind == CRSKind.GEOGRAPHIC else "m",
        )
