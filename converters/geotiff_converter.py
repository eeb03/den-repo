"""
Converts GeoTIFF rasters (satellite imagery, DEMs) into Universal Subterra
Records plus one SurveyFrame per raster. Rasters are sampled on a grid
(`stride`) rather than pixel-by-pixel to keep record counts tractable for
large scenes.

COORDINATES. By default this converter reprojects sampled pixel centres to
EPSG:4326 eagerly, and that DEFAULT IS UNCHANGED: downstream raster
consumers (preprocessing/dem_alignment.py, the spatial grid builders) all
assume lat/lon today. The raster's NATIVE CRS is not discarded either -- it
lives on the frame together with an explicit record of the reprojection.

`reproject=False` keeps the raster in its OWN coordinates instead:
`ProjectedPosition` carrying the native easting/northing, and a frame whose
`SpatialRef` declares the raster's own EPSG code with
`CRSProvenance.DECLARED_BY_SOURCE`. Nothing is transformed at ingest.

Why that option exists: eager reprojection makes derived coordinates
indistinguishable from measured ones -- every record looks natively
geographic, and the frame ends up declaring EPSG:4326 as though the source
had said so. For a raster like AHN, which declares EPSG:28992 in the file,
keeping the native coordinates lets `fusion.sensor_fusion` do the transform
at fusion time through `ingestion/crs_transform.py`, where the result is
counted and reported as derived (`FusionSample.n_reprojected`). Same
transform, honest provenance.

Requires the optional `rasterio` dependency.
"""
from pathlib import Path

import numpy as np

from converters.base import BaseConverter, ConversionResult, MissingDependencyError
from schemas.spatial import (
    Assumption, AxisKind, CRSKind, CRSProvenance, GeographicPosition, ProjectedPosition,
    SpatialRef, VerticalAxis,
)
from schemas.subterra_record import SubterraRecord, SensorType
from schemas.survey_frame import SurveyFrame, make_frame_id
from utils.logger import get_logger

logger = get_logger(__name__)


class GeoTIFFConverter(BaseConverter):
    format_name = "geotiff"
    supported_extensions = (".tif", ".tiff")

    def convert(
        self,
        path: str | Path,
        dataset_id: str,
        sensor_type: SensorType,
        stride: int = 10,
        reproject: bool = True,
    ) -> list[SubterraRecord]:
        """Records only. See `load()` for records plus the raster's SurveyFrame."""
        return self.load(path, dataset_id=dataset_id, sensor_type=sensor_type,
                         stride=stride, reproject=reproject).records

    def load(
        self,
        path: str | Path,
        dataset_id: str,
        sensor_type: SensorType,
        stride: int = 10,
        reproject: bool = True,
        **kwargs,
    ) -> ConversionResult:
        """
        `reproject=True` (default, unchanged) transforms pixel centres to
        WGS84 at ingest. `reproject=False` keeps the raster's own projected
        coordinates and declares its native CRS on the frame, leaving any
        transform to the fusion layer where it is labelled derived.
        """
        try:
            import rasterio
            from rasterio.warp import transform as rio_transform
        except ImportError as e:
            raise MissingDependencyError(
                "rasterio is required to convert GeoTIFF files. Install with: pip install rasterio"
            ) from e

        path = Path(path)
        records: list[SubterraRecord] = []

        with rasterio.open(str(path)) as ds:
            band1 = ds.read(1)
            rows, cols = np.mgrid[0 : band1.shape[0] : stride, 0 : band1.shape[1] : stride]
            xs, ys = rasterio.transform.xy(ds.transform, rows.ravel(), cols.ravel())

            native = bool(ds.crs and ds.crs.to_epsg() != 4326)
            if not reproject and ds.crs is None:
                raise ValueError(
                    f"{path.name}: reproject=False keeps the raster's native coordinates and "
                    f"declares its CRS on the frame, but this raster declares no CRS. There is "
                    f"nothing to declare and nothing is inferred here, so either supply a raster "
                    f"that declares one or use the default reproject=True."
                )
            reprojected = native and reproject
            if reprojected:
                lons, lats = rio_transform(ds.crs, "EPSG:4326", xs, ys)
            else:
                lons, lats = xs, ys

            values = band1[rows.ravel(), cols.ravel()]

            for y_or_lat, x_or_lon, val in zip(lats, lons, values):
                if ds.nodata is not None and val == ds.nodata:
                    continue
                if reproject:
                    latitude, longitude = float(y_or_lat), float(x_or_lon)
                    position = GeographicPosition(lat=latitude, lon=longitude)
                else:
                    # The raster's OWN coordinates, untransformed. latitude and
                    # longitude stay unset rather than being filled with
                    # easting/northing, which would be a coordinate claiming to
                    # be something it is not.
                    latitude = longitude = None
                    position = ProjectedPosition(easting=float(x_or_lon),
                                                 northing=float(y_or_lat))
                records.append(
                    SubterraRecord(
                        dataset_id=dataset_id,
                        sensor_type=sensor_type,
                        latitude=latitude,
                        longitude=longitude,
                        position=position,
                        frame_id=make_frame_id(dataset_id, path.name),
                        signal=[float(val)],
                        metadata={"band": 1, "stride": stride, "source_crs": str(ds.crs)},
                    )
                )

            frame = self._build_frame(
                path=path, dataset_id=dataset_id, sensor_type=sensor_type, ds=ds,
                stride=stride, reprojected=reprojected, n_records=len(records),
                reproject=reproject,
            )

        logger.info(f"GeoTIFFConverter: sampled {len(records)} points from {path.name} (stride={stride})")
        return ConversionResult(records=records, frames=[frame])

    def _build_frame(self, path, dataset_id, sensor_type, ds, stride, reprojected,
                     n_records, reproject=True):
        """
        The frame's spatial_ref describes what the RECORDS hold, which after
        eager reprojection is EPSG:4326. The raster's native CRS -- the thing
        that used to be thrown away -- is preserved in source_metadata and in
        an explicit reprojection Assumption, so the transform stays traceable.
        """
        native_epsg = ds.crs.to_epsg() if ds.crs else None
        assumptions = []
        if ds.crs:
            assumptions.append(Assumption(
                key="crs", value=f"EPSG:{native_epsg}" if native_epsg else str(ds.crs),
                basis="declared by the GeoTIFF", verified=True))
        else:
            assumptions.append(Assumption(
                key="crs", value=None,
                basis="ASSUMED: the raster declares no CRS; its coordinates were used as lat/lon unchanged",
                verified=False))
        if reprojected:
            assumptions.append(Assumption(
                key="reprojection",
                value=f"{ds.crs.to_string()} -> EPSG:4326",
                basis="rasterio.warp.transform, applied eagerly at ingest; "
                      "record latitude/longitude are derived, not native",
                verified=True))
        elif not reproject:
            assumptions.append(Assumption(
                key="reprojection", value="not applied",
                basis=("records keep the raster's OWN projected coordinates and the frame "
                       "declares the CRS the file itself states. Any transform to WGS84 "
                       "happens later, in fusion, where the result is reported as derived "
                       "rather than passing for a measured coordinate."),
                verified=True))

        native_ref = SpatialRef(
            kind=CRSKind.PROJECTED,
            code=f"EPSG:{native_epsg}" if native_epsg else ds.crs.to_string(),
            crs_provenance=CRSProvenance.DECLARED_BY_SOURCE,
            name=f"raster's own coordinates, as declared by the file ({ds.crs.to_string()})",
            horizontal_units="m",
        ) if not reproject else None

        return SurveyFrame(
            frame_id=make_frame_id(dataset_id, path.name),
            dataset_id=dataset_id,
            modality=sensor_type,
            modality_source="user_supplied",
            source_format=self.format_name,
            source_file=path.name,
            spatial_ref=native_ref or SpatialRef(
                kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                crs_provenance=(CRSProvenance.DECLARED_BY_SOURCE if ds.crs
                                else CRSProvenance.INFERRED),
                name="records reprojected to WGS84 at ingest" if reprojected
                     else "raster is already in WGS84 lon/lat",
                horizontal_units="deg",
            ),
            vertical_axis=VerticalAxis(
                kind=AxisKind.ELEVATION_M if sensor_type == SensorType.LIDAR else AxisKind.NONE,
                units="m" if sensor_type == SensorType.LIDAR else "",
                origin="raster band 1 value",
                positive_down=False,
                n_samples=1,
            ),
            n_positions=n_records,
            position_index_name="pixel",
            assumptions=assumptions,
            source_metadata={
                "native_crs": str(ds.crs) if ds.crs else None,
                "native_crs_epsg": native_epsg,
                "raster_width": ds.width,
                "raster_height": ds.height,
                "band_count": ds.count,
                "nodata": ds.nodata,
                "stride": stride,
                "transform": list(ds.transform)[:6],
            },
        )
