"""
Converts GeoTIFF rasters (satellite imagery, DEMs) into Universal Subterra
Records. Rasters are sampled on a grid (`stride`) rather than pixel-by-pixel
to keep record counts tractable for large scenes.

Requires the optional `rasterio` dependency.
"""
from pathlib import Path

import numpy as np

from converters.base import BaseConverter, MissingDependencyError
from schemas.subterra_record import SubterraRecord, SensorType
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
    ) -> list[SubterraRecord]:
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

            if ds.crs and ds.crs.to_epsg() != 4326:
                lons, lats = rio_transform(ds.crs, "EPSG:4326", xs, ys)
            else:
                lons, lats = xs, ys

            values = band1[rows.ravel(), cols.ravel()]

            for lat, lon, val in zip(lats, lons, values):
                if ds.nodata is not None and val == ds.nodata:
                    continue
                records.append(
                    SubterraRecord(
                        dataset_id=dataset_id,
                        sensor_type=sensor_type,
                        latitude=float(lat),
                        longitude=float(lon),
                        signal=[float(val)],
                        metadata={"band": 1, "stride": stride, "source_crs": str(ds.crs)},
                    )
                )

        logger.info(f"GeoTIFFConverter: sampled {len(records)} points from {path.name} (stride={stride})")
        return records
