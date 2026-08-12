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
    SpatialRef, VerticalAxis, VerticalDatum,
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
        vertical_datum: str | None = None,
    ) -> list[SubterraRecord]:
        """Records only. See `load()` for records plus the raster's SurveyFrame."""
        return self.load(path, dataset_id=dataset_id, sensor_type=sensor_type,
                         stride=stride, reproject=reproject,
                         vertical_datum=vertical_datum).records

    def load(
        self,
        path: str | Path,
        dataset_id: str,
        sensor_type: SensorType,
        stride: int = 10,
        reproject: bool = True,
        vertical_datum: str | None = None,
        band_is_elevation: bool | None = None,
        **kwargs,
    ) -> ConversionResult:
        """
        `reproject=True` (default, unchanged) transforms pixel centres to
        WGS84 at ingest. `reproject=False` keeps the raster's own projected
        coordinates and declares its native CRS on the frame, leaving any
        transform to the fusion layer where it is labelled derived.

        `vertical_datum` is an EXPLICIT caller declaration of what the band
        values are measured from. GeoTIFF has no field for it -- AHN's NAP is
        documented by PDOK and absent from the file -- so without this the
        frame states no datum and absolute elevation stays uncomputable.

        `band_is_elevation` is the same kind of declaration about what band 1
        MEANS. A GeoTIFF band carries numbers and no statement of what they
        measure: elevation, reflectance, temperature and slope are
        indistinguishable from the file. Until this stage the answer was
        inferred from the operator's declared MODALITY -- a raster called lidar
        got an elevation axis and one called satellite did not -- which is why
        the COP30 DEM held here has `AxisKind.NONE` and cannot anchor anything,
        while an AHN raster got an elevation axis nobody had actually asserted.

        Three states, and the difference matters:

            True   the caller asserts band 1 is elevation in metres
            False  the caller asserts it is not
            None   nobody has said; the modality inference is used and is
                   RECORDED AS AN INFERENCE on the frame rather than passing
                   silently as fact

        When the axis is an elevation, the band value is also written to
        `record.elevation`. It never was, for any raster -- which is why
        `assess_surface` saw no elevations even on a LiDAR raster whose axis
        said ELEVATION_M.
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

        # Decided ONCE, before any record is built, so every record and the
        # frame agree about what band 1 is.
        declared = band_is_elevation is not None
        is_elevation = (band_is_elevation if declared
                        else sensor_type == SensorType.LIDAR)

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
                        # THE BAND VALUE AS AN ELEVATION, when somebody has said
                        # that is what it is. `signal` keeps it either way, so
                        # nothing is lost when the claim is absent or withdrawn.
                        elevation=float(val) if is_elevation else None,
                        metadata={"band": 1, "stride": stride, "source_crs": str(ds.crs)},
                    )
                )

            frame = self._build_frame(
                path=path, dataset_id=dataset_id, sensor_type=sensor_type, ds=ds,
                stride=stride, reprojected=reprojected, n_records=len(records),
                reproject=reproject, vertical_datum=vertical_datum,
                is_elevation=is_elevation, elevation_declared=declared,
            )

        logger.info(f"GeoTIFFConverter: sampled {len(records)} points from {path.name} (stride={stride})")
        return ConversionResult(records=records, frames=[frame])

    def _build_frame(self, path, dataset_id, sensor_type, ds, stride, reprojected,
                     n_records, reproject=True, vertical_datum=None,
                     is_elevation=False, elevation_declared=False):
        """
        The frame's spatial_ref describes what the RECORDS hold, which after
        eager reprojection is EPSG:4326. The raster's native CRS -- the thing
        that used to be thrown away -- is preserved in source_metadata and in
        an explicit reprojection Assumption, so the transform stays traceable.
        """
        native_epsg = ds.crs.to_epsg() if ds.crs else None
        assumptions = []

        # WHAT BAND 1 MEANS, and on whose authority. Recorded either way: a
        # declaration is supplied_by_caller, and the modality fallback is an
        # INFERENCE that now says so instead of passing as fact. `verified` is
        # False in both cases -- nothing checked the band against anything.
        assumptions.append(Assumption(
            key="band_is_elevation",
            value=is_elevation,
            basis=(
                f"SUPPLIED BY CALLER: band 1 was declared "
                f"{'to be' if is_elevation else 'not to be'} elevation in metres. "
                f"The GeoTIFF states no band semantics."
                if elevation_declared else
                f"INFERRED from the declared modality {sensor_type.value!r}: the file "
                f"states no band semantics, and nobody declared any. A band of numbers "
                f"is elevation, reflectance or temperature indistinguishably; this is a "
                f"deduction, not something the raster said."
            ),
            verified=False,
        ))
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
                kind=AxisKind.ELEVATION_M if is_elevation else AxisKind.NONE,
                units="m" if is_elevation else "",
                origin="raster band 1 value",
                positive_down=False,
                n_samples=1,
                # Absent unless the caller declares it: the raster carries no
                # vertical CRS, no band units and no band description.
                vertical_datum=VerticalDatum(
                    code=vertical_datum,
                    provenance=CRSProvenance.SUPPLIED_BY_CALLER,
                    name=("asserted as ingest configuration; the GeoTIFF declares no "
                          "vertical CRS, band unit or band description"),
                ) if vertical_datum else None,
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
