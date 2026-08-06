"""
Converts LAS/LAZ LiDAR point clouds into Universal Subterra Records.
Points are optionally downsampled (`max_points`) since raw point clouds
can run into the hundreds of millions of points.

Requires the optional `laspy` dependency.
"""
from pathlib import Path

import numpy as np

from converters.base import BaseConverter, MissingDependencyError
from schemas.subterra_record import SubterraRecord, SensorType
from utils.logger import get_logger

logger = get_logger(__name__)


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

        records: list[SubterraRecord] = []
        for i, pi in enumerate(idx):
            records.append(
                SubterraRecord(
                    dataset_id=dataset_id,
                    sensor_type=sensor_type,
                    latitude=float(ys[i]),
                    longitude=float(xs[i]),
                    elevation=float(zs[i]),
                    signal=[float(intensity[i])] if intensity is not None else [],
                    metadata={
                        "point_index": int(pi),
                        "downsampled": n > max_points,
                        "source_point_count": n,
                    },
                )
            )

        logger.info(
            f"LASConverter: parsed {len(records)}/{n} points from {path.name} "
            f"(downsampled={n > max_points})"
        )
        return records
