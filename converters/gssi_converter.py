"""
GSSI (Geophysical Survey Systems Inc.) `.dzt` GPR converter.

The third and last vendor in the TU1208 controlled-site corpus, after IDS
and MALÅ. With this reader, all three instruments that surveyed the same
buried targets become comparable through one pipeline.

FIELD LAYOUT is taken from `readgssi.m`, the reference reader Dartmouth
shipped INSIDE the TU1208 archive alongside the data, and confirmed field
by field against all 40 local `.dzt` files. The data offset rule is its
rule verbatim: `1024 * rh_data` when `rh_data < 1024`, else
`1024 * rh_nchan`. Every one of the 40 files divides into whole traces
under it, with zero remainder.

WHERE THIS DELIBERATELY DIVERGES FROM THE REFERENCE, both times because
measurement contradicted it:

1. **Sample centring.** `readgssi.m` adds `rh_zero` to every sample. That
   is right for 16-bit (`rh_zero` = -32768, and the raw mean sits on
   32768) but WRONG for 8-bit, where `rh_zero` = +128 while the raw mean
   also sits on 128 -- adding it moves the baseline to 256 instead of 0.
   The actual rule, verified on real traces of all three depths, is a
   property of the storage: 8- and 16-bit samples are stored UNSIGNED and
   become signed by subtracting the midpoint 2^(bits-1); 32-bit is already
   signed and needs no shift. The file's own `rh_zero` is preserved in
   metadata either way, so the raw values remain recoverable.

2. **The first two samples.** `readgssi.m` overwrites samples 0 and 1 with
   sample 2. Measured across 2,000 traces, sample 0 lies outside the range
   of the rest of its trace in 65% of cases and sample 1 in only 6.3% --
   real but not categorical. Overwriting them would be fabricating data to
   hide an artefact, so they are read AS STORED and the measurement is
   recorded on the frame for a consumer to act on deliberately.

WHAT THE FORMAT DOES NOT CONTAIN, and what is therefore never invented
here:

- **No coordinates**, unless a `.dzg` GNSS sidecar accompanies the file.
  None of the 40 local files has one. Without it a distance-triggered line
  gets odometry and a time-triggered line gets `NoPosition` -- never a
  placeholder.
- **No CRS.**
- **No usable velocity.** `rhf_epsr` is present but is an operator display
  setting -- it is 0.00 in 17 of the 40 files, which is physically
  impossible -- so it is recorded and NEVER used to derive depth. Depth
  exists only when the caller supplies a velocity, exactly as in the IDS
  and MALÅ readers.
- **No antenna frequency.** `rh_antname` holds a model code ('5013',
  '3101 900MHz', 'D400HS'). A frequency is extracted only when the string
  literally contains one; mapping model codes to frequencies would be
  inventing metadata the file does not carry.
"""
from __future__ import annotations

import re
import struct
from datetime import datetime
from pathlib import Path

from converters.base import BaseConverter, ConversionResult
from converters.ids_dt_converter import (
    MAX_VELOCITY_M_PER_NS, MIN_VELOCITY_M_PER_NS, two_way_time_to_depth,
    validate_velocity,
)
from schemas.spatial import (
    Assumption, AxisKind, CRSKind, CRSProvenance, GeographicPosition, NoPosition,
    OdometryPosition, SpatialRef, VerticalAxis,
)
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame, make_frame_id
from utils.logger import get_logger

logger = get_logger(__name__)

MIN_HEADER_BYTES = 1024

#: bits -> (struct code, byte width, stored unsigned?). 8- and 16-bit are
#: stored unsigned and recentred; 32-bit is already signed.
SAMPLE_TYPES = {8: ("B", 1, True), 16: ("H", 2, True), 32: ("i", 4, False)}

#: Values seen in `rh_tag` across real GSSI files. Used only as a sanity
#: signal in the error path -- never to reject a file that otherwise parses.
KNOWN_TAGS = {0x00FF, 0x07FF}

_VELOCITY_BOUNDS_BASIS = (
    "physical bounds shared with the IDS and MALA readers: the lower bound is far "
    "below any geological medium, the upper bound is the speed of light in vacuum"
)

_NO_POSITION_REASON = (
    "GSSI .dzt header reports scans-per-metre 0 (a time-triggered acquisition) and no "
    ".dzg GNSS sidecar accompanies it, so the file carries no position of any kind"
)


class GSSIFormatError(ValueError):
    """Raised when a `.dzt` is malformed, truncated, or uses an unsupported variant."""


def _decode_dzt_datetime(raw: bytes) -> str | None:
    """
    GSSI packs a timestamp into 4 bytes: sec/2 (5b), min (6b), hour (5b),
    day (5b), month (4b), year-1980 (7b). Returns None when the field is
    zeroed or nonsensical rather than inventing a date.
    """
    v = int.from_bytes(raw, "little")
    sec, minute, hour = (v & 31) * 2, (v >> 5) & 63, (v >> 11) & 31
    day, month, year = (v >> 16) & 31, (v >> 21) & 15, 1980 + ((v >> 25) & 127)
    try:
        return datetime(year, month, day, hour, minute, min(sec, 59)).isoformat()
    except ValueError:
        return None


def parse_dzt_header(path: str | Path) -> dict:
    """
    Parses the fixed-layout `.dzt` header.

    Field order follows `readgssi.m` from the TU1208 archive; every offset
    was confirmed against all 40 local files.
    """
    path = Path(path)
    size = path.stat().st_size
    if size < MIN_HEADER_BYTES:
        raise GSSIFormatError(
            f"{path.name}: {size} bytes is shorter than a GSSI header "
            f"({MIN_HEADER_BYTES} bytes); this is not a .dzt file"
        )
    with open(path, "rb") as fh:
        raw = fh.read(MIN_HEADER_BYTES)

    u16 = lambda o: struct.unpack_from("<H", raw, o)[0]      # noqa: E731
    i16 = lambda o: struct.unpack_from("<h", raw, o)[0]      # noqa: E731
    f32 = lambda o: struct.unpack_from("<f", raw, o)[0]      # noqa: E731
    text = lambda o, n: raw[o:o + n].split(b"\x00")[0].decode("latin-1", "replace").strip()  # noqa: E731

    header = {
        "tag": u16(0), "data": u16(2), "n_samples": u16(4), "bits": u16(6),
        "zero": i16(8),
        "scans_per_second": f32(10), "scans_per_metre": f32(14),
        "metres_per_mark": f32(18),
        "position_ns": f32(22), "range_ns": f32(26),
        "n_pass": u16(30),
        "created": _decode_dzt_datetime(raw[32:36]),
        "modified": _decode_dzt_datetime(raw[36:40]),
        "rgain": u16(40), "n_rgain": u16(42),
        "text_offset": u16(44), "n_text": u16(46),
        "proc_offset": u16(48), "n_proc": u16(50),
        "n_channels": u16(52),
        "epsr": f32(54), "top": f32(58), "depth": f32(62),
        "dtype": raw[97],
        "antenna_name": text(98, 14),
        "channel_mask": u16(112),
        "name": text(114, 12),
        "file_size": size,
    }
    if header["n_samples"] <= 0:
        raise GSSIFormatError(
            f"{path.name}: header declares {header['n_samples']} samples per trace"
        )
    if header["bits"] not in SAMPLE_TYPES:
        raise GSSIFormatError(
            f"{path.name}: sample depth {header['bits']} bits is not one this reader "
            f"supports ({sorted(SAMPLE_TYPES)}). Refusing rather than decoding it "
            f"approximately."
        )
    if header["n_channels"] > 1:
        raise GSSIFormatError(
            f"{path.name}: the header declares {header['n_channels']} channels. "
            f"Multi-channel .dzt interleaves traces across channels, and this reader has "
            f"never been validated against one, so it refuses rather than silently "
            f"reading interleaved data as a single line."
        )
    header["data_offset"] = data_offset(header)
    return header


def data_offset(header: dict) -> int:
    """
    Where the sample block starts.

    `readgssi.m`'s rule verbatim; all 40 local files divide into whole
    traces under it with zero remainder.
    """
    if header["data"] < MIN_HEADER_BYTES:
        return MIN_HEADER_BYTES * header["data"]
    return MIN_HEADER_BYTES * max(header["n_channels"], 1)


def read_dzt(path: str | Path, header: dict) -> tuple[list[list[float]], int]:
    """
    Reads the sample block, recentred to a signed baseline.

    8- and 16-bit samples are stored UNSIGNED and are shifted by the
    midpoint 2^(bits-1); 32-bit is stored signed and is not shifted. See the
    module docstring for why this is measured rather than taken from the
    reference reader's `+rh_zero`.
    """
    path = Path(path)
    code, width, unsigned = SAMPLE_TYPES[header["bits"]]
    n_samples = header["n_samples"]
    offset = header["data_offset"]
    row_bytes = n_samples * width
    body = header["file_size"] - offset
    if body <= 0:
        raise GSSIFormatError(
            f"{path.name}: the header places the sample block at byte {offset}, but the "
            f"file is only {header['file_size']} bytes; it is truncated or mis-declared"
        )
    n_traces = body // row_bytes
    if n_traces < 1:
        raise GSSIFormatError(
            f"{path.name}: {body} bytes of data is less than one {row_bytes}-byte trace "
            f"({n_samples} samples x {width} bytes)"
        )
    if body % row_bytes:
        logger.warning(
            f"{path.name}: {body % row_bytes} trailing byte(s) after {n_traces} complete "
            f"traces; the remainder is ignored."
        )
    shift = (1 << (header["bits"] - 1)) if unsigned else 0
    with open(path, "rb") as fh:
        fh.seek(offset)
        raw = fh.read(n_traces * row_bytes)
    fmt = f"<{n_samples}{code}"
    traces = [
        [float(v - shift) for v in struct.unpack_from(fmt, raw, t * row_bytes)]
        for t in range(n_traces)
    ]
    return traces, n_traces


def derive_time_axis(header: dict, path: Path) -> dict:
    """
    The MEASURED time axis: `rhf_range` nanoseconds over `rh_nsamp` samples.

    `rhf_position` is NOT applied. Across the local corpus it holds -10, -0
    and +99.04 ns against 60-110 ns windows, and the first breaks land 3.5-15
    ns into the record regardless -- so whatever the field means, it is not a
    usable time-zero offset for these files. It is preserved in metadata and
    the axis starts at instrument time-zero.
    """
    n_samples, range_ns = header["n_samples"], header["range_ns"]
    if not range_ns > 0:
        raise GSSIFormatError(
            f"{path.name}: header declares a time range of {range_ns} ns, so no time "
            f"axis exists and no depth could be derived from it"
        )
    return {
        "n_samples": n_samples,
        "time_window_ns": float(range_ns),
        "sample_interval_ns": float(range_ns) / n_samples,
    }


def derive_along_track(header: dict) -> tuple[dict | None, str | None]:
    """
    Trace spacing from `rhf_spm` (scans per metre), or (None, reason).

    `rhf_spm` is 0.00 in 22 of the 40 local files -- those are time-triggered
    acquisitions with `rhf_sps` set instead. A time-triggered line has no
    distance axis at all, and deriving one from an assumed tow speed would be
    fabricating survey geometry.
    """
    spm = header.get("scans_per_metre") or 0.0
    if not spm > 0:
        return None, (
            f"scans-per-metre is {spm}: this line was time-triggered "
            f"(scans-per-second {header.get('scans_per_second')}), so its traces have no "
            f"along-track coordinate"
        )
    return {"trace_spacing_m": 1.0 / spm, "scans_per_metre": float(spm)}, None


def find_sidecar(path: Path, extensions) -> Path | None:
    """Finds a same-stem sidecar, trying case variants."""
    for ext in extensions:
        for variant in (ext, ext.upper(), ext.capitalize()):
            candidate = path.with_suffix(variant)
            if candidate.exists():
                return candidate
    return None


def parse_dzg(path: str | Path) -> dict[int, tuple[float, float]]:
    """
    Parses a GSSI `.dzg` GNSS sidecar into {trace_number: (lat, lon)}.

    The format interleaves NMEA sentences with GSSI `$GSSIS` scan markers:

        $GSSIS,<scan>,<...>
        $GPGGA,<utc>,<lat>,<N/S>,<lon>,<E/W>,<quality>,...

    A fix is attached to the most recent preceding scan marker. Sentences
    with GPS quality 0 (no fix) are DISCARDED -- a no-fix NMEA line still
    carries numbers, and treating them as a position would place traces at a
    stale or null location.

    Returns {} for an absent or empty file. No local `.dzt` has a `.dzg`, so
    this path is exercised by tests rather than by the corpus.
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    fixes: dict[int, tuple[float, float]] = {}
    scan: int | None = None
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("$GSSIS"):
            parts = line.split(",")
            try:
                scan = int(parts[1])
            except (IndexError, ValueError):
                scan = None
        elif line.startswith(("$GPGGA", "$GNGGA")):
            parts = line.split(",")
            if len(parts) < 7:
                continue
            try:
                quality = int(parts[6])
            except ValueError:
                continue
            if quality == 0:                      # no fix: not a position
                continue
            try:
                lat = _nmea_degrees(float(parts[2]), parts[3])
                lon = _nmea_degrees(float(parts[4]), parts[5])
            except (TypeError, ValueError):
                continue
            if scan is not None:
                fixes[scan] = (lat, lon)
    return fixes


def _nmea_degrees(value: float, hemisphere: str) -> float:
    """NMEA ddmm.mmmm -> signed decimal degrees."""
    degrees = int(abs(value) // 100)
    out = degrees + (abs(value) - 100 * degrees) / 60.0
    return -out if hemisphere.strip().upper() in ("S", "W") else out


def parse_dzx(path: str | Path) -> dict:
    """
    Pulls the few informative scalars out of a `.dzx` XML sidecar.

    Supplementary only: everything here also appears in the `.dzt` header,
    so a missing `.dzx` costs nothing. Parsed with a regex rather than an XML
    parser because the file embeds base64 blobs that are not always
    well-formed, and a malformed sidecar must not fail the acquisition.
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return {}
    out = {}
    for tag in ("system", "softwareVersion", "dielectric", "unitsPerScan",
                "unitsPerMark", "depthRange", "scanPerMeters", "gridId",
                "verticalUnit", "horizontalUnit"):
        match = re.search(rf"<{tag}>(.*?)</{tag}>", text)
        if match:
            out[tag] = match.group(1).strip()
    return out


def antenna_frequency_mhz(header: dict) -> float | None:
    """
    A frequency ONLY if `rh_antname` literally states one.

    Local names include '3101 900MHz' (states it) and '5013', 'D400HS',
    '50270S' (model codes that do not). Mapping model codes to frequencies
    would be inventing metadata the file does not carry, so those return None.
    """
    match = re.search(r"(\d+(?:\.\d+)?)\s*MHz", header.get("antenna_name") or "", re.I)
    return float(match.group(1)) if match else None


class GSSIConverter(BaseConverter):
    format_name = "gssi"
    supported_extensions = (".dzt",)

    def can_convert(self, path: Path) -> bool:
        return Path(path).suffix.lower() in self.supported_extensions

    def convert(self, path, dataset_id: str, sensor_type: SensorType = SensorType.GPR,
                velocity_m_per_ns: float | None = None, **kwargs) -> list[SubterraRecord]:
        """Records only. See `load()` for records plus the file's SurveyFrame."""
        return self.load(path, dataset_id=dataset_id, sensor_type=sensor_type,
                         velocity_m_per_ns=velocity_m_per_ns, **kwargs).records

    def load(self, path, dataset_id: str, sensor_type: SensorType = SensorType.GPR,
             velocity_m_per_ns: float | None = None, **kwargs) -> ConversionResult:
        """
        `velocity_m_per_ns` is an EXPLICIT caller declaration with no default.
        The header's `rhf_epsr` is an operator display setting -- zero in 17 of
        the 40 local files -- so it is never turned into a velocity. Without an
        explicit value `depth` stays None and records carry only the measured
        time axis.
        """
        path = Path(path)
        header = parse_dzt_header(path)
        time_axis = derive_time_axis(header, path)
        traces, n_traces = read_dzt(path, header)
        n_samples = time_axis["n_samples"]
        interval_ns = time_axis["sample_interval_ns"]

        along_track, along_track_rejected = derive_along_track(header)
        if along_track_rejected:
            logger.warning(
                f"GSSIConverter: {path.name}: {along_track_rejected}. Records will carry "
                f"NoPosition unless a .dzg supplies coordinates."
            )

        dzg = find_sidecar(path, (".dzg",))
        fixes = parse_dzg(dzg) if dzg else {}
        dzx = find_sidecar(path, (".dzx",))
        dzx_meta = parse_dzx(dzx) if dzx else {}

        velocity, velocity_rejected = validate_velocity(
            velocity_m_per_ns, bounds_basis=_VELOCITY_BOUNDS_BASIS)
        if velocity_rejected and velocity_m_per_ns is not None:
            logger.warning(
                f"GSSIConverter: {path.name}: {velocity_rejected}. Depth will NOT be "
                f"derived; records keep the measured time axis only."
            )

        frame_id = make_frame_id(dataset_id, path.name)
        spacing = along_track["trace_spacing_m"] if along_track else None
        no_position = NoPosition(reason=along_track_rejected or _NO_POSITION_REASON)

        records: list[SubterraRecord] = []
        for trace_index in range(n_traces):
            row = traces[trace_index]
            along = trace_index * spacing if spacing is not None else None
            fix = fixes.get(trace_index)
            if fix is not None:
                position = GeographicPosition(lat=fix[0], lon=fix[1])
                position_source = "gssi_dzg_gnss"
                latitude, longitude = fix
            elif along is not None:
                position = OdometryPosition(along_track_m=along, path_id=path.stem)
                position_source = "gssi_survey_wheel"
                latitude = longitude = None
            else:
                position = no_position
                position_source = "none"
                latitude = longitude = None

            for sample_index in range(n_samples):
                two_way_ns = sample_index * interval_ns
                records.append(SubterraRecord(
                    dataset_id=dataset_id,
                    sensor_type=sensor_type,
                    latitude=latitude, longitude=longitude,
                    position=position,
                    frame_id=frame_id,
                    elevation=None,
                    depth=(two_way_time_to_depth(two_way_ns, velocity)
                           if velocity is not None else None),
                    signal=[row[sample_index]],
                    metadata={
                        "source_file": path.name,
                        "trace_index": trace_index,
                        "sample_index": sample_index,
                        "two_way_time_ns": two_way_ns,
                        **({"along_track_m": along, "trace_spacing_m": spacing}
                           if along is not None else {}),
                        **({"velocity_m_per_ns": velocity,
                            "velocity_source": "supplied_by_caller",
                            "depth_is_velocity_derived": True}
                           if velocity is not None else {}),
                        "position_source": position_source,
                        "trace_count": n_traces,
                        "sample_count": n_samples,
                    },
                ))

        logger.info(
            f"GSSIConverter: parsed {path.name} -> {n_traces} traces x {n_samples} samples "
            f"({len(records):,} records), {time_axis['time_window_ns']:.1f} ns window, "
            f"antenna {header['antenna_name']!r}, {header['bits']}-bit"
        )
        return ConversionResult(records=records, frames=[self._build_frame(
            path, dataset_id, sensor_type, header, frame_id, time_axis, n_traces,
            velocity, velocity_rejected, along_track, along_track_rejected,
            bool(fixes), dzg, dzx, dzx_meta)])

    def _build_frame(self, path, dataset_id, sensor_type, header, frame_id, time_axis,
                     n_traces, velocity, velocity_rejected, along_track,
                     along_track_rejected, has_gnss, dzg, dzx, dzx_meta) -> SurveyFrame:
        """Describes the line as a whole: measured, assumed, and absent, kept apart."""
        if has_gnss:
            ref = SpatialRef(
                kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                crs_provenance=CRSProvenance.INFERRED,
                name=("GSSI .dzg GNSS sidecar. The file states no datum; WGS84 is inferred "
                      "because that is what NMEA-reporting receivers emit."),
                horizontal_units="deg",
            )
        elif along_track is not None:
            ref = SpatialRef(
                kind=CRSKind.ACQUISITION,
                name=("survey-wheel distance along this line only. The acquisition carries "
                      "no geographic or projected reference, and none is inferred."),
                horizontal_units="m",
            )
        else:
            ref = SpatialRef(kind=CRSKind.UNKNOWN,
                             name=along_track_rejected or _NO_POSITION_REASON)

        assumptions = [
            Assumption(
                key="time_axis", value=time_axis["sample_interval_ns"],
                basis=(
                    f"MEASURED: the header declares rhf_range="
                    f"{time_axis['time_window_ns']} ns over rh_nsamp="
                    f"{time_axis['n_samples']}, giving "
                    f"{time_axis['sample_interval_ns']:.6f} ns per sample."
                ),
                verified=True,
            ),
            Assumption(
                key="time_zero_offset_not_applied", value=header["position_ns"],
                basis=(
                    f"the header's rhf_position is {header['position_ns']} ns, but it is NOT "
                    f"applied. Across the local corpus this field holds -10, -0 and +99.04 ns "
                    f"against 60-110 ns windows while first breaks land 3.5-15 ns into the "
                    f"record regardless, so whatever it means it is not a usable time-zero "
                    f"offset for these files. The axis starts at instrument time-zero and the "
                    f"raw value is preserved here."
                ),
                verified=False,
            ),
            Assumption(
                key="sample_centring",
                value=f"{header['bits']}-bit, "
                      f"{'unsigned, midpoint subtracted' if SAMPLE_TYPES[header['bits']][2] else 'signed, unshifted'}",
                basis=(
                    f"MEASURED: 8- and 16-bit .dzt samples are stored unsigned (raw means sit "
                    f"on 128 and 32768 respectively) and are recentred by subtracting "
                    f"2^(bits-1); 32-bit is stored signed and is not shifted. The archive's own "
                    f"readgssi.m instead ADDS rh_zero, which is correct at 16-bit "
                    f"(rh_zero=-32768) but wrong at 8-bit (rh_zero=+128 moves the baseline to "
                    f"256). The file's rh_zero={header['zero']} is preserved in source_metadata."
                ),
                verified=True,
            ),
            Assumption(
                key="leading_samples_may_be_markers", value=2,
                basis=(
                    "MEASURED across 2,000 local traces: sample 0 falls outside the range of "
                    "the rest of its trace in 65% of traces and sample 1 in 6.3%. The archive's "
                    "readgssi.m overwrites both with sample 2; this reader does NOT, because "
                    "the evidence is not categorical and overwriting would fabricate data to "
                    "hide an artefact. Samples are read as stored; exclude them deliberately "
                    "downstream if required."
                ),
                verified=True,
            ),
        ]
        if along_track is not None:
            assumptions.append(Assumption(
                key="along_track_spacing", value=along_track["trace_spacing_m"],
                basis=(
                    f"MEASURED: rhf_spm={along_track['scans_per_metre']} scans per metre gives "
                    f"{along_track['trace_spacing_m']:.6f} m between traces. This positions "
                    f"traces along their own line; it does NOT georeference the line."
                ),
                verified=True,
            ))
        else:
            assumptions.append(Assumption(
                key="along_track_unavailable", value=None,
                basis=f"No along-track coordinate: {along_track_rejected}. Records carry NoPosition.",
                verified=True,
            ))
        if not has_gnss:
            assumptions.append(Assumption(
                key="gnss_absent", value=None,
                basis=(
                    f"no populated .dzg sidecar accompanies this line "
                    f"({'present but empty of usable fixes' if dzg else 'no .dzg file'}), so the "
                    f"acquisition recorded no satellite position. This is an ABSENCE in the "
                    f"survey, not a read failure."
                ),
                verified=True,
            ))
        assumptions.append(Assumption(
            key="epsr_not_used_for_velocity", value=header["epsr"],
            basis=(
                f"the header reports rhf_epsr={header['epsr']}, but it is NOT converted into a "
                f"propagation velocity. It is an operator display setting rather than a site "
                f"measurement -- it is 0.00 in 17 of the 40 local files, which is physically "
                f"impossible -- so depth comes only from a caller-supplied velocity."
            ),
            verified=True,
        ))
        if velocity is not None:
            assumptions.append(Assumption(
                key="gpr_velocity", value=velocity,
                basis=(
                    f"SUPPLIED BY CALLER: {velocity} m/ns, used as "
                    f"depth_m = two_way_time_ns * velocity / 2. This is an ASSERTION about the "
                    f"subsurface, not a measurement of it, so every depth derived from it is "
                    f"assumed while the time axis above remains measured."
                ),
                verified=False,
            ))
        else:
            assumptions.append(Assumption(
                key="depth_conversion", value="not applied",
                basis=(
                    f"no usable velocity was supplied ({velocity_rejected}), so record.depth is "
                    f"None and only the measured time axis is carried. Nothing is defaulted."
                ),
                verified=True,
            ))

        return SurveyFrame(
            frame_id=frame_id,
            dataset_id=dataset_id,
            modality=sensor_type,
            modality_source="user_supplied",
            source_format=self.format_name,
            source_file=path.name,
            spatial_ref=ref,
            vertical_axis=VerticalAxis(
                kind=AxisKind.TWO_WAY_TIME_NS,
                units="ns",
                origin="instrument time-zero at each trace",
                positive_down=True,
                n_samples=time_axis["n_samples"],
                sample_interval=time_axis["sample_interval_ns"],
                conversion={
                    "method": "constant_velocity",
                    "velocity_m_per_ns": velocity,
                    "formula": "depth_m = two_way_time_ns * velocity_m_per_ns / 2",
                    "target_axis": AxisKind.DEPTH_M.value,
                } if velocity is not None else None,
            ),
            n_positions=n_traces,
            position_index_name="trace_index",
            assumptions=assumptions,
            source_metadata={
                "dzt_tag": header["tag"],
                "dzt_tag_known": header["tag"] in KNOWN_TAGS,
                "bits": header["bits"],
                "rh_zero": header["zero"],
                "data_offset": header["data_offset"],
                "antenna_name": header["antenna_name"] or None,
                "antenna_mhz": antenna_frequency_mhz(header),
                "time_window_ns": time_axis["time_window_ns"],
                "position_ns_raw": header["position_ns"],
                "sample_count": time_axis["n_samples"],
                "trace_count": n_traces,
                "scans_per_metre": header["scans_per_metre"],
                "scans_per_second": header["scans_per_second"],
                "metres_per_mark": header["metres_per_mark"],
                "epsr_reported": header["epsr"],
                "n_channels": header["n_channels"],
                "created": header["created"],
                "modified": header["modified"],
                "file_name_field": header["name"] or None,
                "dzx_sidecar": dzx.name if dzx else None,
                "dzx": dzx_meta or None,
                "dzg_sidecar": dzg.name if dzg else None,
                "velocity_bounds_m_per_ns": [MIN_VELOCITY_M_PER_NS, MAX_VELOCITY_M_PER_NS],
            },
        )
