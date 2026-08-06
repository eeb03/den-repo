"""
SEG-Y converter for Subterra.

Converts SEG-Y files (GPR or seismic) into Universal Subterra Records plus
one SurveyFrame per file (a SEG-Y file IS one acquisition line here).

COORDINATES. SourceX/SourceY are reported in whatever CRS the acquisition
system used, and SEG-Y has no field that declares which one. This converter
therefore classifies rather than guesses:

- values inside WGS84 lon/lat range -> GeographicPosition
- any other non-zero pair          -> ProjectedPosition (easting/northing),
                                      with the CRS recorded as undeclared
- (0, 0)                           -> NoPosition, with the reason recorded

Previously the middle case was thrown away: out-of-range headers were
overwritten with a literal (0.0, 0.0). On the INGV-UNISA lines that
discarded a genuine UTM position (easting ~501134, northing ~4544705, i.e.
zone 33N near 41N 15E) and replaced it with a coordinate in the Gulf of
Guinea. `position` now preserves it.

`latitude`/`longitude` keep their previous values EXACTLY, including the
(0.0, 0.0) fallback, so every existing consumer is unaffected. They are the
legacy view; `position` is the truth.

The acquisition-track mapping supplied separately by the ingestion layer
(ingestion/kmz_georeference.py, applied per-trace in
api/routes/datasets.py::ingest_zip_from_url) still overwrites latitude/
longitude as before.

MODALITY. SEG-Y carries GPR and seismic alike, but their vertical axes are
not interchangeable. This converter used to apply a GPR soil velocity of
0.1 m/ns to EVERY sensor_type, so ingesting a seismic SEG-Y silently
produced a depth computed from the wrong physics. Only GPR now gets a depth
conversion; every other modality keeps its time axis and leaves `depth`
unset, because converting seismic travel time to depth requires a velocity
model this platform does not have. Non-GPR SEG-Y is READ but NOT VALIDATED
-- no real seismic file has been parsed here, and the frame says so.

GPR two-way travel time is commonly written into the SEG-Y binary header's
"microseconds" sample-interval field pre-scaled by 1000 so it round-trips
as the correct nanosecond value (confirmed on this dataset: header
Interval=293 -> segyio sample step 0.293, i.e. a 0.293 ns interval and a
~141 ns two-way window -- physically sane for a shallow GPR survey; taken
as literal microseconds it would imply an absurd multi-km penetration
depth). `depth` is derived from that time axis via a standard constant-
velocity conversion, not the raw time value itself -- and because that
velocity is ASSUMED rather than measured, the frame records it as an
explicit Assumption instead of leaving it implicit in this module.
"""

from pathlib import Path

from converters.base import BaseConverter, ConversionResult, MissingDependencyError
from schemas.spatial import (
    Assumption, AxisKind, CRSKind, CRSProvenance, GeographicPosition, NoPosition,
    ProjectedPosition, SpatialRef, VerticalAxis,
)
from schemas.subterra_record import SubterraRecord, SensorType
from schemas.survey_frame import SurveyFrame, make_frame_id


# Typical near-surface soil GPR velocity (relative permittivity ~9);
# override with converter_kwargs={"velocity_m_per_ns": ...} when a
# site-specific velocity (e.g. from a CMP survey) is known.
DEFAULT_GPR_VELOCITY_M_PER_NS = 0.1

_NO_HEADER_POSITION = (
    "SEG-Y trace header SourceX/SourceY are (0, 0); the file carries no trace position"
)


def _parse_declared_crs(crs, path):
    """
    Parses a CRS the CALLER declared. Never guesses: an unparseable or
    ambiguous value fails loudly rather than falling back to some default,
    because a silently wrong CRS relocates an entire survey.
    """
    try:
        from rasterio.crs import CRS
    except ImportError as e:
        raise MissingDependencyError(
            "rasterio is required to use an explicitly supplied CRS for SEG-Y ingest. "
            "Install with: pip install rasterio"
        ) from e
    if not str(crs).strip():
        raise ValueError(
            f"{path.name}: crs was supplied but is empty. Either omit it entirely -- leaving the "
            f"projected header coordinates preserved but unconvertible -- or give an unambiguous "
            f"identifier such as 'EPSG:32633'."
        )
    try:
        parsed = CRS.from_user_input(crs)
    except Exception as e:
        raise ValueError(
            f"{path.name}: could not interpret the supplied crs={crs!r}. Supply an unambiguous "
            f"identifier such as 'EPSG:32633'. SEG-Y declares no CRS of its own, so nothing "
            f"can be assumed here."
        ) from e
    return parsed


def _to_wgs84(declared_crs, x: float, y: float) -> tuple[float, float]:
    """Derives (lat, lon) from projected coordinates using a CRS the caller declared."""
    from rasterio.warp import transform as rio_transform

    lons, lats = rio_transform(declared_crs, "EPSG:4326", [x], [y])
    return float(lats[0]), float(lons[0])


def _classify_position(x: float, y: float):
    """Maps a SEG-Y header coordinate pair to an explicit Position (see module docstring)."""
    if x == 0.0 and y == 0.0:
        return NoPosition(reason=_NO_HEADER_POSITION)
    if -90.0 <= y <= 90.0 and -180.0 <= x <= 180.0:
        return GeographicPosition(lat=y, lon=x)
    return ProjectedPosition(easting=x, northing=y)


class SEGYConverter(BaseConverter):
    format_name = "segy"
    supported_extensions = (".sgy", ".segy")

    def can_convert(self, path: Path) -> bool:
        return path.suffix.lower() in self.supported_extensions

    def convert(
        self,
        path: Path,
        dataset_id: str,
        sensor_type: SensorType,
        velocity_m_per_ns: float = DEFAULT_GPR_VELOCITY_M_PER_NS,
        crs: str | None = None,
        **kwargs,
    ) -> list[SubterraRecord]:
        """Records only. See `load()` for records plus the file's SurveyFrame."""
        return self.load(
            path, dataset_id=dataset_id, sensor_type=sensor_type,
            velocity_m_per_ns=velocity_m_per_ns, crs=crs, **kwargs,
        ).records

    def load(
        self,
        path: Path,
        dataset_id: str,
        sensor_type: SensorType,
        velocity_m_per_ns: float = DEFAULT_GPR_VELOCITY_M_PER_NS,
        crs: str | None = None,
        **kwargs,
    ) -> ConversionResult:
        """
        `crs` is an EXPLICIT declaration by the caller of what SourceX/SourceY
        are expressed in. SEG-Y has no field for this, so without it the
        header coordinates are preserved as ProjectedPosition but cannot be
        turned into latitude/longitude -- and nothing here infers one. When
        supplied, the native easting/northing remain authoritative and a
        geographic view is DERIVED from them for the legacy fields.
        """

        try:
            import segyio
        except ImportError as e:
            raise MissingDependencyError(
                "segyio is required to convert SEG-Y files. "
                "Install with: pip install segyio"
            ) from e

        path = Path(path)
        records = []
        trace_positions = []   # one Position per trace, for frame-level summary

        # GPR is the only modality this converter has a depth conversion for.
        # See _build_frame for what non-GPR modalities get instead.
        is_gpr = sensor_type == SensorType.GPR
        declared_crs = _parse_declared_crs(crs, path) if crs is not None else None

        with segyio.open(str(path), "r", ignore_geometry=True) as f:

            trace_count = f.tracecount
            samples = list(f.samples)

            for trace_idx in range(trace_count):

                trace = f.trace[trace_idx]
                header = f.header[trace_idx]

                # SEG-Y coordinate scalar.
                scalar = header.get(
                    segyio.TraceField.SourceGroupScalar,
                    1,
                ) or 1

                raw_x = header.get(
                    segyio.TraceField.SourceX,
                    0,
                )

                raw_y = header.get(
                    segyio.TraceField.SourceY,
                    0,
                )

                try:
                    scalar = float(scalar)

                    if scalar < 0:
                        scale = 1.0 / abs(scalar)
                    else:
                        scale = scalar

                    x = float(raw_x) * scale
                    y = float(raw_y) * scale

                except Exception:
                    x = 0.0
                    y = 0.0

                position = _classify_position(x, y)
                trace_positions.append(position)

                # Legacy lat/lon. Unchanged when no CRS was declared: trusted
                # as real WGS84 only when actually in range, else the
                # historical (0.0, 0.0). `position` above preserves the
                # projected case either way.
                if -90.0 <= y <= 90.0 and -180.0 <= x <= 180.0:
                    latitude, longitude = y, x
                elif declared_crs is not None:
                    # The caller declared what these coordinates ARE, so a
                    # geographic view can be DERIVED. Native easting/northing
                    # stay authoritative in `position`.
                    latitude, longitude = _to_wgs84(declared_crs, x, y)
                else:
                    latitude, longitude = 0.0, 0.0

                sample_interval = f.bin.get(segyio.BinField.Interval, None)

                # Store the complete trace as individual samples.
                #
                # This preserves the actual GPR waveform instead of
                # collapsing the entire trace into a single value.
                for sample_idx, value in enumerate(trace):

                    sample_time = float(samples[sample_idx])
                    if is_gpr:
                        depth = (sample_time * velocity_m_per_ns) / 2.0
                        axis_metadata = {
                            "two_way_time_ns": sample_time,
                            "velocity_m_per_ns": velocity_m_per_ns,
                        }
                    else:
                        # No velocity model exists for this modality, so no
                        # depth is produced. Fabricating one with a GPR soil
                        # velocity -- which is what this converter used to do
                        # for every sensor_type -- would be a wrong number
                        # presented as a measurement.
                        depth = None
                        axis_metadata = {"two_way_time_ms": sample_time}

                    record = SubterraRecord(
                        dataset_id=dataset_id,
                        latitude=latitude,
                        longitude=longitude,
                        position=position,
                        frame_id=make_frame_id(dataset_id, path.name),
                        elevation=None,
                        depth=depth,
                        signal=[float(value)],
                        sensor_type=sensor_type,
                        ground_truth="none",
                        metadata={
                            "source_file": path.name,
                            "trace_index": trace_idx,
                            "sample_index": sample_idx,
                            **axis_metadata,
                            "sample_interval": sample_interval,
                            "segy_x": x,
                            "segy_y": y,
                            "position_source": (
                                "segy_header" if position.kind != "none" else "none"
                            ),
                            "trace_count": trace_count,
                            "sample_count": len(samples),
                        },
                    )

                    records.append(record)

            frame = self._build_frame(
                path=path, dataset_id=dataset_id, sensor_type=sensor_type,
                trace_positions=trace_positions, samples=samples,
                sample_interval=f.bin.get(segyio.BinField.Interval, None),
                velocity_m_per_ns=velocity_m_per_ns, trace_count=trace_count,
                declared_crs=declared_crs, declared_crs_input=crs,
            )

        return ConversionResult(records=records, frames=[frame])

    def _build_frame(
        self, path, dataset_id, sensor_type, trace_positions, samples,
        sample_interval, velocity_m_per_ns, trace_count,
        declared_crs=None, declared_crs_input=None,
    ) -> SurveyFrame:
        """Describes the acquisition line as a whole: CRS, vertical axis, provenance, assumptions."""
        kinds = {p.kind for p in trace_positions}
        if kinds == {"geographic"}:
            ref = SpatialRef(
                kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                crs_provenance=(CRSProvenance.SUPPLIED_BY_CALLER if declared_crs is not None
                                else CRSProvenance.INFERRED),
                name=(
                    "SEG-Y SourceX/SourceY, in WGS84 lon/lat range. SEG-Y declares no CRS, so "
                    "WGS84 is inferred from the values' range unless a caller supplied one."
                ),
                horizontal_units="deg",
            )
        elif kinds == {"projected"}:
            if declared_crs is not None:
                epsg = declared_crs.to_epsg()
                ref = SpatialRef(
                    kind=CRSKind.PROJECTED,
                    code=f"EPSG:{epsg}" if epsg else declared_crs.to_string(),
                    crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER,
                    name=(
                        f"SEG-Y SourceX/SourceY easting/northing. The FILE DECLARES NO CRS; "
                        f"{declared_crs_input!r} was supplied externally as ingest configuration "
                        f"and applies to this dataset only."
                    ),
                    horizontal_units="m",
                )
            else:
                ref = SpatialRef(
                    kind=CRSKind.PROJECTED, code=None,
                    crs_provenance=CRSProvenance.NONE,
                    name="SEG-Y SourceX/SourceY easting/northing; SEG-Y declares no CRS for them",
                    horizontal_units="m",
                )
        elif kinds == {"none"}:
            ref = SpatialRef(kind=CRSKind.UNKNOWN, name=_NO_HEADER_POSITION)
        else:
            # Mixed header quality within one line: refuse to characterise the
            # line as a whole rather than pick whichever kind is commoner.
            ref = SpatialRef(
                kind=CRSKind.UNKNOWN,
                name=f"SEG-Y trace headers are inconsistent across this line (kinds: {sorted(kinds)})",
            )

        is_gpr = sensor_type == SensorType.GPR

        if is_gpr:
            assumptions = [
                Assumption(
                    key="gpr_velocity", value=velocity_m_per_ns,
                    basis=(
                        "assumed default (typical near-surface soil, relative permittivity ~9)"
                        if velocity_m_per_ns == DEFAULT_GPR_VELOCITY_M_PER_NS
                        else "supplied by caller"
                    ),
                    verified=False,
                ),
                Assumption(
                    key="two_way_time_units", value="ns",
                    basis="SEG-Y binary header Interval is pre-scaled by 1000 in this family of files",
                    verified=False,
                ),
            ]
        else:
            assumptions = [
                Assumption(
                    key="two_way_time_units", value="ms",
                    basis=(
                        "ASSUMED: SEG-Y rev-1 convention, where the binary header Interval is in "
                        "microseconds and the sample axis is therefore in milliseconds. NOT verified "
                        "against a real file of this modality."
                    ),
                    verified=False,
                ),
                Assumption(
                    key="depth_conversion", value="not applied",
                    basis=(
                        "no velocity model is available for this modality, so record.depth is left "
                        "unset rather than computed. This converter previously applied a GPR soil "
                        "velocity of 0.1 m/ns to every sensor_type, which produced a wrong depth for "
                        "anything that is not GPR."
                    ),
                    verified=True,
                ),
                Assumption(
                    key="modality_support", value=f"{sensor_type.value} SEG-Y is UNVALIDATED",
                    basis=(
                        "no real file of this modality has been parsed and validated; the time axis "
                        "is read but its units and geometry semantics are unconfirmed"
                    ),
                    verified=False,
                ),
            ]

        # Whether the header gives a genuine per-trace track or one static
        # value repeated -- downstream lateral-extent maths must not treat
        # the latter as a survey path.
        if declared_crs is not None:
            assumptions.append(Assumption(
                key="crs_supplied_by_caller", value=declared_crs_input,
                basis=(
                    "SEG-Y has no field for a coordinate reference system, so this was asserted "
                    "as ingest configuration for this dataset. It is NOT declared by the file and "
                    "NOT inferred from the data; nothing generalises it to other datasets. "
                    "latitude/longitude are derived from it; record.position keeps the native "
                    "easting/northing."
                ),
                verified=False,
            ))

        distinct = {p.model_dump_json() for p in trace_positions}
        if trace_positions:
            assumptions.append(
                Assumption(
                    key="per_trace_position",
                    value="varies" if len(distinct) > 1 else "constant across all traces",
                    basis=f"observed: {len(distinct)} distinct header position(s) across {trace_count} traces",
                    verified=True,
                )
            )

        step = float(samples[1] - samples[0]) if len(samples) > 1 else None

        return SurveyFrame(
            frame_id=make_frame_id(dataset_id, path.name),
            dataset_id=dataset_id,
            modality=sensor_type,
            modality_source="user_supplied",
            source_format=self.format_name,
            source_file=path.name,
            spatial_ref=ref,
            vertical_axis=VerticalAxis(
                kind=AxisKind.TWO_WAY_TIME_NS if is_gpr else AxisKind.TWO_WAY_TIME_MS,
                units="ns" if is_gpr else "ms",
                origin="instrument time-zero at each trace",
                positive_down=True,
                n_samples=len(samples),
                sample_interval=step,
                # `conversion` is present only when a depth conversion was
                # actually applied. Its absence is the machine-readable form
                # of "these records carry time, not depth".
                conversion={
                    "method": "constant_velocity",
                    "velocity_m_per_ns": velocity_m_per_ns,
                    "formula": "depth_m = two_way_time_ns * velocity_m_per_ns / 2",
                    "target_axis": AxisKind.DEPTH_M.value,
                } if is_gpr else None,
            ),
            n_positions=trace_count,
            position_index_name="trace_index",
            assumptions=assumptions,
            source_metadata={
                "segy_binary_interval": sample_interval,
                "trace_count": trace_count,
                "sample_count": len(samples),
                "time_min_ns": float(samples[0]) if samples else None,
                "time_max_ns": float(samples[-1]) if samples else None,
            },
        )
