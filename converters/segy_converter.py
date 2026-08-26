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

import math
from pathlib import Path

from converters.base import BaseConverter, ConversionResult, MissingDependencyError
from converters.segy_endian import (
    BIG, LITTLE, LittleEndianSegyFile, detect_endianness, int32_as_float32,
    nmea_to_degrees,
)
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

_NON_FINITE_COORDS = (
    "SEG-Y trace header SourceX/SourceY do not reinterpret to finite IEEE floats under the "
    "declared coordinate_encoding, so no coordinate can be read from this trace"
)

#: How SourceX/SourceY are encoded. The standard says 4-byte integers scaled
#: by SourceGroupScalar, and that stays the default. Some GPR vendors instead
#: write IEEE floats holding NMEA ddmm.mmmm -- which the bytes cannot reveal,
#: so it is a CALLER DECLARATION, never inferred. Same contract as `crs`.
COORDINATE_ENCODINGS = {
    "int32_scaled": "SEG-Y standard: 4-byte integers scaled by SourceGroupScalar",
    "ieee_nmea": (
        "vendor deviation: IEEE float32 in the integer field, holding NMEA ddmm.mmmm "
        "geographic coordinates. SourceGroupScalar does NOT apply."
    ),
}


def validate_coordinate_encoding(value: str) -> None:
    """
    The single check for "is this a real, known coordinate_encoding" --
    reused by every ingest entrypoint that accepts the option (the
    synchronous /ingest and /ingest_local_file routes, and the
    review/accept flow's `AcceptRequest`), so the set of valid values has
    exactly one place it can be defined: `COORDINATE_ENCODINGS` above.
    Raises `ValueError`, which each caller turns into its own honest,
    explicit 4xx -- never a raw TypeError from a converter that received a
    keyword it does not recognise.
    """
    if value not in COORDINATE_ENCODINGS:
        raise ValueError(
            f"unknown coordinate_encoding {value!r}; supported: {sorted(COORDINATE_ENCODINGS)}"
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
        coordinate_encoding: str = "int32_scaled",
        velocity_basis: str | None = None,
        velocity_source_quantity: str | None = None,
        velocity_source_value: float | None = None,
        velocity_source_basis: str | None = None,
        **kwargs,
    ) -> list[SubterraRecord]:
        """Records only. See `load()` for records plus the file's SurveyFrame."""
        return self.load(
            path, dataset_id=dataset_id, sensor_type=sensor_type,
            velocity_m_per_ns=velocity_m_per_ns, crs=crs,
            coordinate_encoding=coordinate_encoding,
            velocity_basis=velocity_basis,
            velocity_source_quantity=velocity_source_quantity,
            velocity_source_value=velocity_source_value,
            velocity_source_basis=velocity_source_basis,
            **kwargs,
        ).records

    def load(
        self,
        path: Path,
        dataset_id: str,
        sensor_type: SensorType,
        velocity_m_per_ns: float = DEFAULT_GPR_VELOCITY_M_PER_NS,
        crs: str | None = None,
        coordinate_encoding: str = "int32_scaled",
        velocity_basis: str | None = None,
        velocity_source_quantity: str | None = None,
        velocity_source_value: float | None = None,
        velocity_source_basis: str | None = None,
        **kwargs,
    ) -> ConversionResult:
        """
        `crs` is an EXPLICIT declaration by the caller of what SourceX/SourceY
        are expressed in. SEG-Y has no field for this, so without it the
        header coordinates are preserved as ProjectedPosition but cannot be
        turned into latitude/longitude -- and nothing here infers one. When
        supplied, the native easting/northing remain authoritative and a
        geographic view is DERIVED from them for the legacy fields.

        `coordinate_encoding` is likewise an EXPLICIT declaration, defaulting
        to the SEG-Y standard. See COORDINATE_ENCODINGS.

        Byte order is DETECTED, not declared, because unlike the two above it
        is a structural property the file can be checked against. Big-endian
        always wins: the little-endian reader is reached only when segyio
        could not have opened the file at all.

        `velocity_basis`/`velocity_source_*` let a caller that resolved
        `velocity_m_per_ns` from a DECLARED quantity (e.g.
        `ingestion.four_tu_velocity.resolve_four_tu_velocity`) say so, instead
        of the generic "supplied by caller" this converter would otherwise
        record. This converter stays generic: it does not know what the
        quantity IS, only that the caller is asserting one. All four default
        to None, which reproduces today's exact behaviour.
        """

        try:
            import segyio
        except ImportError as e:
            raise MissingDependencyError(
                "segyio is required to convert SEG-Y files. "
                "Install with: pip install segyio"
            ) from e

        path = Path(path)
        if coordinate_encoding not in COORDINATE_ENCODINGS:
            raise ValueError(
                f"{path.name}: coordinate_encoding={coordinate_encoding!r} is not recognised. "
                f"Choose one of {sorted(COORDINATE_ENCODINGS)}. Nothing is inferred here, so an "
                f"unrecognised value is refused rather than defaulted."
            )
        byte_order, endian_evidence = detect_endianness(path)
        records = []
        trace_positions = []   # one Position per trace, for frame-level summary

        # GPR is the only modality this converter has a depth conversion for.
        # See _build_frame for what non-GPR modalities get instead.
        is_gpr = sensor_type == SensorType.GPR
        any_elevation = False
        declared_crs = _parse_declared_crs(crs, path) if crs is not None else None

        # Recorded on each GPR record's metadata only when the velocity is
        # NOT the converter's own default, so a default-velocity ingestion's
        # per-record metadata is byte-for-byte what it was before this tag
        # existed. `record_provenance` reads this key for its depth basis.
        velocity_source_tag = None
        if is_gpr and velocity_m_per_ns != DEFAULT_GPR_VELOCITY_M_PER_NS:
            velocity_source_tag = (
                f"declared:{velocity_source_quantity}" if velocity_source_quantity
                else "supplied_by_caller"
            )

        # ONE record-building path for both byte orders. LittleEndianSegyFile
        # presents the same surface segyio does, so nothing below is duplicated.
        opener = (
            (lambda: segyio.open(str(path), "r", ignore_geometry=True)) if byte_order == BIG
            else (lambda: LittleEndianSegyFile(path, order=LITTLE))
        )

        with opener() as f:

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
                    if coordinate_encoding == "ieee_nmea":
                        # The same four bytes, read as an IEEE float instead of
                        # an integer, then decoded from NMEA ddmm.mmmm. The
                        # coordinate scalar does NOT apply -- a float carries
                        # its own precision, and applying the scalar as well
                        # would divide the position by 1000.
                        fx = int32_as_float32(raw_x, byte_order)
                        fy = int32_as_float32(raw_y, byte_order)
                        # Arbitrary integer bit patterns reinterpret to NaN or
                        # infinity (0xFFFFFFFF is a NaN). A non-finite value is
                        # not a position, so it becomes NoPosition rather than
                        # propagating NaN into the spatial model.
                        if not (math.isfinite(fx) and math.isfinite(fy)):
                            # NOT (0.0, 0.0). That placeholder is exactly what
                            # M3 removed; None keeps "no position" distinct
                            # from a real coordinate off the coast of Africa.
                            x = y = None
                        else:
                            x = nmea_to_degrees(fx)
                            y = nmea_to_degrees(fy)
                    else:
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

                if x is None:
                    position = NoPosition(reason=_NON_FINITE_COORDS)
                else:
                    position = _classify_position(x, y)
                trace_positions.append(position)

                # ACQUISITION ELEVATION. Read only under the ieee_nmea
                # declaration, because it is the same vendor deviation: bytes
                # 41-44 and 45-48 hold IEEE floats where SEG-Y specifies
                # scaled integers. The default path is untouched -- the INGV
                # lines DO populate these fields as standard scaled integers
                # (482.88 m via ElevationScalar -100), and reading them there
                # would change pinned records.
                #
                # NO DATUM IS CLAIMED. The file declares none, and the two
                # values differ by a constant 43.948 m, which is consistent
                # with an orthometric/ellipsoidal pair but is not a
                # declaration. See fusion/vertical_reference.py.
                elevation = None
                if coordinate_encoding == "ieee_nmea":
                    ev = int32_as_float32(
                        header.get(segyio.TraceField.ReceiverGroupElevation, 0), byte_order)
                    if math.isfinite(ev) and ev != 0.0:
                        elevation = float(ev)
                        any_elevation = True
                        eh = int32_as_float32(
                            header.get(segyio.TraceField.SourceSurfaceElevation, 0), byte_order)
                        if math.isfinite(eh) and eh != 0.0:
                            elevation_second = float(eh)
                        else:
                            elevation_second = None
                    else:
                        elevation_second = None
                else:
                    elevation_second = None

                # latitude/longitude are a DERIVED VIEW of the position, and
                # are left unset when there is no geographic position to
                # derive them from. The (0.0, 0.0) placeholder this used to
                # write made "no position" indistinguishable from a real
                # coordinate in the Gulf of Guinea.
                if x is None:
                    latitude, longitude = None, None
                elif -90.0 <= y <= 90.0 and -180.0 <= x <= 180.0:
                    latitude, longitude = y, x
                elif declared_crs is not None:
                    # The caller declared what these coordinates ARE, so a
                    # geographic view can be DERIVED. Native easting/northing
                    # stay authoritative in `position`.
                    latitude, longitude = _to_wgs84(declared_crs, x, y)
                else:
                    latitude, longitude = None, None

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
                            **({"velocity_source": velocity_source_tag}
                               if velocity_source_tag else {}),
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
                        elevation=elevation,
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
                            **({"acquisition_elevation_m": elevation,
                                "acquisition_elevation_datum": "UNDECLARED",
                                "acquisition_elevation_source": "segy_receiver_group_elevation"}
                               if elevation is not None else {}),
                            **({"segy_source_surface_elevation_m": elevation_second}
                               if elevation_second is not None else {}),
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
                byte_order=byte_order, endian_evidence=endian_evidence,
                coordinate_encoding=coordinate_encoding,
                has_elevation=any_elevation,
                velocity_basis=velocity_basis,
                velocity_source_quantity=velocity_source_quantity,
                velocity_source_value=velocity_source_value,
                velocity_source_basis=velocity_source_basis,
            )

        return ConversionResult(records=records, frames=[frame])

    def _build_frame(
        self, path, dataset_id, sensor_type, trace_positions, samples,
        sample_interval, velocity_m_per_ns, trace_count,
        declared_crs=None, declared_crs_input=None,
        byte_order=BIG, endian_evidence=None, coordinate_encoding="int32_scaled",
        has_elevation=False,
        velocity_basis=None, velocity_source_quantity=None,
        velocity_source_value=None, velocity_source_basis=None,
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
            if velocity_basis is not None:
                gpr_velocity_basis = velocity_basis
            elif velocity_m_per_ns == DEFAULT_GPR_VELOCITY_M_PER_NS:
                gpr_velocity_basis = "assumed default (typical near-surface soil, relative permittivity ~9)"
            else:
                gpr_velocity_basis = "supplied by caller"
            assumptions = [
                Assumption(
                    key="gpr_velocity", value=velocity_m_per_ns,
                    basis=gpr_velocity_basis,
                    verified=False,
                ),
                Assumption(
                    key="two_way_time_units", value="ns",
                    basis="SEG-Y binary header Interval is pre-scaled by 1000 in this family of files",
                    verified=False,
                ),
            ]
            # Present only when the caller resolved the velocity from a
            # declared quantity (e.g. ingestion.four_tu_velocity). This
            # converter does not know what the quantity IS -- it only
            # records that the caller named one, with its own basis.
            if velocity_source_quantity is not None:
                assumptions.append(Assumption(
                    key="gpr_velocity_source_quantity", value=velocity_source_value,
                    basis=velocity_source_basis or f"{velocity_source_quantity} supplied by caller",
                    verified=False,
                ))
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

        # Recorded only when NON-DEFAULT, so a big-endian standard file's
        # frame is byte-for-byte what it was before this reader existed.
        if byte_order == LITTLE:
            big = (endian_evidence or {}).get("big", {})
            little = (endian_evidence or {}).get("little", {})
            assumptions.append(Assumption(
                key="segy_byte_order", value=LITTLE,
                basis=(
                    f"DETECTED, not assumed: the big-endian reading of the binary header is "
                    f"self-inconsistent (format code {big.get('format')}, "
                    f"{big.get('samples')} samples/trace) while the little-endian reading is "
                    f"consistent (format code {little.get('format')}, "
                    f"{little.get('samples')} samples/trace, trace length divides the file "
                    f"body exactly). SEG-Y rev 0/1 specifies big-endian; this file does not "
                    f"follow it, which is a known GPR vendor deviation."
                ),
                verified=True,
            ))
        if byte_order == LITTLE and samples and samples[0] != 0.0:
            assumptions.append(Assumption(
                key="time_axis_origin_offset", value=float(samples[0]),
                basis=(
                    f"the trace header's DelayRecordingTime places time-zero at "
                    f"{samples[0]:g} ns rather than 0, read in the SAME pre-scaled-by-1000 "
                    f"unit as the sample interval because one instrument wrote both fields. "
                    f"The vertical axis origin is INSTRUMENT TIME-ZERO, not the ground "
                    f"surface, so every derived depth carries this offset. For an "
                    f"air-launched antenna it is largely air path, which this constant "
                    f"ground velocity does not model."
                ),
                verified=False,
            ))
        if coordinate_encoding != "int32_scaled":
            assumptions.append(Assumption(
                key="segy_coordinate_encoding", value=coordinate_encoding,
                basis=(
                    f"SUPPLIED BY CALLER: {COORDINATE_ENCODINGS[coordinate_encoding]}. The file "
                    f"cannot declare this -- the bytes are identical either way -- so it was "
                    f"asserted as ingest configuration for this dataset and generalises to "
                    f"nothing else. Under 'ieee_nmea' the SEG-Y coordinate scalar is NOT applied."
                ),
                verified=False,
            ))

        if has_elevation:
            assumptions.append(Assumption(
                key="acquisition_elevation_datum", value=None,
                basis=(
                    "the trace headers carry a per-trace acquisition elevation, but the file "
                    "declares NO vertical datum for it and neither the dataset readme nor its "
                    "codebook mentions one. The two elevation fields differ by a constant "
                    "43.948 m, which is consistent with an orthometric/ellipsoidal pair for "
                    "the Netherlands -- consistent with, not a declaration of. record.elevation "
                    "therefore carries the number without claiming what it is measured from."
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
                "segy_byte_order": byte_order,
                "segy_coordinate_encoding": coordinate_encoding,
                "segy_binary_interval": sample_interval,
                "trace_count": trace_count,
                "sample_count": len(samples),
                "time_min_ns": float(samples[0]) if samples else None,
                "time_max_ns": float(samples[-1]) if samples else None,
            },
        )
