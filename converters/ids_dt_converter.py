"""
IDS GeoRadar .dt converter.

FORMAT. `.dt` is IDS GeoRadar's proprietary acquisition format (K2/Aladdin
family). It is not publicly specified. The layout implemented here was
established two ways that agree: by direct inspection of real files from
the Guangzhou University GPR dataset (Zenodo record 14637589), and against
the documented reader in RGPR's `readDT()` (GPL, R). No code was copied
from RGPR -- a file layout is a fact, not an implementation -- and every
field below was confirmed against the real files.

    offset 0        'V'  magic
    offset 1..3     file version, three 1-byte integers (observed 4.0.0)
    offset 4..5     len_rec, little-endian uint16 (observed 1028)

    header records at every multiple of len_rec, each starting with a short
    NUL-padded ASCII code:
       I    survey/zone id            FZ   zone
       C    acquisition timestamp     FX   offset x
       AH   height                    FQ   marker quantum
       AC1  acquisition counters      AM   line/marker info
       ATR  antenna parameters        S    channel description
       FW   channel/stacking ints     H    sampler geometry
       R    LAST header record; trace data begins in the NEXT record

    trace records, each len_rec bytes:
       2-byte marker 1 (observed 'R'), 2-byte marker 2,
       then (len_rec - 4) / 2 little-endian uint16 samples.

TIME AXIS. The acquisition time window IS carried by the file, in the H
record: 11 little-endian int32s followed by 10 fixed-width "%16.6E" ASCII
fields (the same "11 integers + 10 ASCII fields" RGPR's readDT()
documents). Field 2 is the sweep time in SECONDS -- the two-way time window
of one trace -- and it is repeated at field 3 in every file examined, which
makes the pair a stable anchor even though other fields shift position
between format versions. The per-sample interval is the window divided by
the sample count, and the software's own vertical cell size (field 9) is
read purely as a cross-check on that.

Confirmed against real files spanning both versions and four sample counts:

    samples  sweep time   interval      cell x n == sweep?
      256     5 ns        19.53 ps      yes
      384     7 ns        18.23 ps      yes
      512    10 / 20 ns   19.53 / 39.06 ps   yes
     1024    10 ns         9.77 ps      yes
      512    80 ns (v3)  156.25 ps      NO -- v3 stores half that value

The v3 disagreement is why the interval is DERIVED from the window and
sample count rather than taken from the stored cell size, with the
cross-check recorded on the frame instead of silently trusted.

WHAT THE FORMAT DOES NOT CARRY: coordinates (FX/AH are 0.000000E+00
throughout) and a CRS. Position is therefore NoPosition.

DEPTH IS NOT DERIVED. The H record does contain a propagation velocity, but
it is whatever the operator configured (3.0e8 m/s -- vacuum -- on one pipe
line, 1.0e8 m/s on others), not a site measurement. Converting the measured
time axis to depth on that basis would present an assumed number as a
measured one, so `depth` is left unset and the configured value is recorded
as an unverified assumption for a caller to accept or override.

COMPANION FILES. A .dt never stands alone: it lives in a `<date>.ZON`
directory beside per-line `Ini000N.ini` (acquisition software
configuration), `Igr000N.Bkg`/`.Stc`, and `Mark000N.txt`/`Nmkr000N.txt`
marker files. Those observed alongside the file are recorded on the frame
as provenance. None is required to read the trace data, and none is parsed
here -- claiming to interpret them without having established their layout
would be exactly the speculation this module avoids.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from converters.base import BaseConverter, ConversionResult
from schemas.spatial import (
    Assumption, AxisKind, CRSKind, NoPosition, OdometryPosition, SpatialRef, VerticalAxis,
)
from schemas.subterra_record import SubterraRecord, SensorType
from schemas.survey_frame import SurveyFrame, make_frame_id
from utils.logger import get_logger

logger = get_logger(__name__)

MAGIC = b"V"
#: The H record carries the acquisition geometry: 11 little-endian int32s
#: followed by 10 fixed-width ASCII fields in "%16.6E" form. Both the count
#: and the layout match RGPR's documented readDT() ("11 x 4-byte integers +
#: 10 ASCII fields") and were confirmed against real files spanning both
#: format versions and four different sample counts.
_H_INT_COUNT = 11
_H_ASCII_FIELDS = 10
_H_ASCII_WIDTH = 16
#: Index of the sweep time (the acquisition time window, seconds) within the
#: ASCII block. It is stored TWICE, at 2 and 3, in every file examined --
#: v3 and v4 alike -- which makes the pair a robust anchor even though other
#: fields shift position between versions.
_H_SWEEP_TIME = 2
_H_SWEEP_TIME_DUP = 3
#: Propagation velocity the OPERATOR configured (m/s). Not a measurement.
_H_PROP_VELOCITY = 1
#: The software's own vertical cell size. Used only as a cross-check.
_H_Y_CELL = 9
#: Along-track trace spacing in METRES, from the wheel encoder. Like the sweep
#: time it is stored twice (6 and 8), which gives a free cross-check, and both
#: indices hold in v3 and v4 alike. Ini000N.ini corroborates the value and its
#: derivation: "data_x_cell = 0.024" under ";;Wheel_Compress * Wheel_dx", with
#: Wheel_Compress = 12 and Wheel_dx = 0.002.
_H_X_CELL = 6
_H_X_CELL_DUP = 8
_H_WHEEL_DX = 7

#: Header record codes whose payload is ASCII text worth keeping verbatim.
_TEXT_CODES = {"I", "C", "AH", "FZ", "FX", "FQ", "FM", "AM", "ATR", "S"}
#: The record code that terminates the header block; data starts after it.
_DATA_SENTINEL = "R"
_MAX_HEADER_RECORDS = 256   # guards against scanning a whole file on garbage input

_NO_POSITION_REASON = (
    "IDS .dt carries no per-trace coordinates; its header position fields are "
    "empty in this dataset and the format declares no CRS"
)


class IDSDTParseError(ValueError):
    """Raised when a file is not a readable IDS .dt."""


def _parse_acquisition(raw: bytes, len_rec: int) -> dict:
    """
    Reads the H record's acquisition block: 11 int32s then 10 ASCII floats.

    Returns {} when the record is absent or unreadable, so the caller can
    fail loudly instead of proceeding with a fabricated time axis.
    """
    h_offset = None
    for k in range(1, min(len(raw) // max(len_rec, 1), _MAX_HEADER_RECORDS)):
        if raw[k * len_rec: k * len_rec + 1] == b"H":
            h_offset = k * len_rec
            break
    if h_offset is None:
        return {}

    body = raw[h_offset + 4: h_offset + len_rec]
    need = _H_INT_COUNT * 4 + _H_ASCII_FIELDS * _H_ASCII_WIDTH
    if len(body) < need:
        return {}

    ints = struct.unpack_from(f"<{_H_INT_COUNT}i", body, 0)
    block = body[_H_INT_COUNT * 4: need].decode("latin-1", "replace")
    fields = []
    for i in range(_H_ASCII_FIELDS):
        text = block[i * _H_ASCII_WIDTH:(i + 1) * _H_ASCII_WIDTH].strip()
        try:
            fields.append(float(text))
        except ValueError:
            fields.append(None)
    return {"h_offset": h_offset, "ints": list(ints), "ascii_fields": fields}


#: Bounds for a caller-supplied EM propagation velocity, in m/ns. These are
#: NOT invented: the IDS acquisition software records its own permitted range
#: in Ini000N.ini as "MaxPropVel = 30 / MinPropVel = 1" under the comment
#: ";; cm/ns", i.e. 0.01-0.30 m/ns. The upper bound is also the speed of
#: light, so anything above it is unphysical regardless of provenance.
MIN_VELOCITY_M_PER_NS = 0.01
MAX_VELOCITY_M_PER_NS = 0.30

#: Plausible bounds for wheel-encoder trace spacing, in metres. A GPR cart
#: triggering every 4 mm to a few cm is normal; anything past a metre per
#: trace is not a profile, and zero means the encoder was not recording.
MIN_TRACE_SPACING_M = 1e-4
MAX_TRACE_SPACING_M = 1.0

#: Widest plausible GPR two-way time window. Real windows are tens of ns;
#: 1 ms would imply kilometres of penetration and means the field is not a
#: sweep time at all.
_MAX_PLAUSIBLE_SWEEP_S = 1e-3


def derive_time_axis(acquisition: dict, n_samples: int) -> dict:
    """
    Builds the two-way time axis from the H record's acquisition block.

    Raises IDSDTParseError when the window is absent, unparseable, or
    physically implausible -- an explicit failure is the only acceptable
    alternative to a fabricated axis, because a wrong time axis silently
    becomes a wrong depth axis downstream.
    """
    fields = (acquisition or {}).get("ascii_fields") or []
    if len(fields) <= _H_Y_CELL:
        raise IDSDTParseError(
            "acquisition H record is missing or truncated, so the time window cannot be "
            "recovered. Refusing to construct a time axis without it."
        )
    sweep = fields[_H_SWEEP_TIME]
    if sweep is None:
        raise IDSDTParseError(
            f"acquisition time window (H record ASCII field {_H_SWEEP_TIME}) is not a number."
        )
    if not (0 < sweep <= _MAX_PLAUSIBLE_SWEEP_S):
        raise IDSDTParseError(
            f"acquisition time window {sweep!r} s is outside the plausible range for GPR "
            f"(0, {_MAX_PLAUSIBLE_SWEEP_S}]; refusing to build a time axis from it."
        )
    if n_samples <= 0:
        raise IDSDTParseError(f"cannot build a time axis over {n_samples} samples")

    interval_s = sweep / n_samples
    stored_cell = fields[_H_Y_CELL]
    # The file's own cell size should equal window/samples. Where it does not
    # (observed on v3), the definitional value wins and the disagreement is
    # reported rather than hidden.
    cell_agrees = (
        stored_cell is not None
        and stored_cell > 0
        and abs(stored_cell * n_samples - sweep) <= 1e-6 * sweep
    )
    duplicate = fields[_H_SWEEP_TIME_DUP]
    return {
        "time_window_ns": sweep * 1e9,
        "sample_interval_ns": interval_s * 1e9,
        "n_samples": n_samples,
        "duplicate_field_agrees": duplicate == sweep,
        "stored_cell_size_s": stored_cell,
        "stored_cell_size_agrees": cell_agrees,
        "configured_velocity_m_per_s": fields[_H_PROP_VELOCITY],
    }


def derive_along_track(acquisition: dict) -> tuple[dict | None, str | None]:
    """
    Recovers the along-track geometry from the H record's acquisition block.

    This is the ONLY positional information IDS .dt carries: a wheel-encoder
    trace spacing in metres. It is a MEASURED acquisition parameter, not an
    assumption, but it locates traces along their own survey line and says
    nothing about where that line is on Earth -- hence OdometryPosition
    rather than a geographic or projected one.

    Returns (geometry, None) when usable, or (None, reason) when not.
    """
    fields = (acquisition or {}).get("ascii_fields") or []
    if len(fields) <= _H_X_CELL_DUP:
        return None, "acquisition H record is missing or truncated"
    spacing = fields[_H_X_CELL]
    if spacing is None:
        return None, f"trace spacing (H record ASCII field {_H_X_CELL}) is not a number"
    if not (MIN_TRACE_SPACING_M <= spacing <= MAX_TRACE_SPACING_M):
        return None, (
            f"trace spacing {spacing} m is outside the plausible range "
            f"[{MIN_TRACE_SPACING_M}, {MAX_TRACE_SPACING_M}] m; the wheel encoder "
            f"most likely was not recording for this acquisition"
        )
    duplicate = fields[_H_X_CELL_DUP]
    return {
        "trace_spacing_m": spacing,
        "duplicate_field_agrees": duplicate == spacing,
        "wheel_dx_m": fields[_H_WHEEL_DX],
    }, None


def validate_velocity(velocity) -> tuple[float | None, str | None]:
    """
    Validates a CALLER-SUPPLIED propagation velocity in m/ns.

    Returns (velocity, None) when usable, or (None, reason) when not. A
    rejected velocity never becomes a depth axis: the caller gets depth=None
    and the reason is logged and recorded on the frame, so a mistyped value
    is discoverable rather than silently producing physical-looking numbers.
    """
    if velocity is None:
        return None, "no velocity supplied"
    try:
        v = float(velocity)
    except (TypeError, ValueError):
        return None, f"velocity {velocity!r} is not a number"
    if v != v or v in (float("inf"), float("-inf")):
        return None, f"velocity {velocity!r} is not finite"
    if not (MIN_VELOCITY_M_PER_NS <= v <= MAX_VELOCITY_M_PER_NS):
        return None, (
            f"velocity {v} m/ns is outside the physically plausible range "
            f"[{MIN_VELOCITY_M_PER_NS}, {MAX_VELOCITY_M_PER_NS}] m/ns "
            f"(the IDS software's own MinPropVel/MaxPropVel limits; the upper "
            f"bound is the speed of light). Note the expected unit is m/ns, "
            f"not cm/ns."
        )
    return v, None


def two_way_time_to_depth(two_way_time_ns: float, velocity_m_per_ns: float) -> float:
    """
    Standard constant-velocity conversion, identical to the one SEGYConverter
    applies: the pulse travels to the reflector and back, so one-way depth is
    half the round-trip path.

        depth_m = two_way_time_ns * velocity_m_per_ns / 2
    """
    return two_way_time_ns * velocity_m_per_ns / 2.0


def _read_code(raw: bytes, offset: int) -> str:
    """The short ASCII code at the start of a header record, NUL/garbage-terminated."""
    chunk = raw[offset:offset + 4]
    out = []
    for b in chunk:
        if b == 0 or not (0x20 <= b <= 0x7E):
            break
        out.append(chr(b))
    return "".join(out)


def parse_dt(path: str | Path) -> dict:
    """
    Parses one .dt file into its header records and trace matrix.

    Returns a dict with `version`, `len_rec`, `header` (code -> value),
    `data_start`, `n_traces`, `n_samples`, `markers` and `samples`
    (n_traces x n_samples uint16). Raises IDSDTParseError on anything that
    is not a readable .dt rather than guessing at a layout.
    """
    path = Path(path)
    raw = path.read_bytes()

    if len(raw) < 8 or raw[0:1] != MAGIC:
        raise IDSDTParseError(
            f"{path.name}: not an IDS .dt file (expected magic {MAGIC!r} at byte 0, "
            f"found {raw[0:1]!r})"
        )
    version = tuple(raw[1:4])
    len_rec = struct.unpack_from("<H", raw, 4)[0]
    if len_rec < 8 or len_rec > 1 << 20:
        raise IDSDTParseError(f"{path.name}: implausible record length {len_rec} in header")

    header: dict[str, str | tuple] = {}
    data_start = None
    n_records = len(raw) // len_rec
    for k in range(1, min(n_records, _MAX_HEADER_RECORDS)):
        offset = k * len_rec
        code = _read_code(raw, offset)
        if not code:
            continue
        if code == _DATA_SENTINEL:
            data_start = (k + 1) * len_rec
            break
        body = raw[offset + 4: offset + len_rec]
        if code in _TEXT_CODES:
            header[code] = body.split(b"\x00")[0].decode("latin-1", "replace").strip()
        else:
            n_ints = min(11, len(body) // 4)
            header[code] = struct.unpack_from(f"<{n_ints}i", body, 0)

    if data_start is None:
        raise IDSDTParseError(
            f"{path.name}: no '{_DATA_SENTINEL}' header record found, so the start of trace "
            f"data is undetermined. The file is truncated or is not an IDS .dt."
        )

    acquisition = _parse_acquisition(raw, len_rec)
    n_samples = (len_rec - 4) // 2
    body = raw[data_start:]
    n_traces = len(body) // len_rec
    if n_traces == 0:
        raise IDSDTParseError(f"{path.name}: header parsed but the file contains no trace records.")

    block = np.frombuffer(body[: n_traces * len_rec], dtype=np.uint8).reshape(n_traces, len_rec)
    markers = block[:, :4].copy().view("<u2")
    samples = block[:, 4:].copy().view("<u2")

    return {
        "version": version,
        "len_rec": len_rec,
        "acquisition": acquisition,
        "header": header,
        "data_start": data_start,
        "n_traces": int(n_traces),
        "n_samples": int(n_samples),
        "trailing_bytes": len(body) % len_rec,
        "markers": markers,
        "samples": samples,
    }


class IDSDTConverter(BaseConverter):
    format_name = "ids_dt"
    supported_extensions = (".dt",)

    def convert(self, path, dataset_id: str, sensor_type: SensorType = SensorType.GPR,
                velocity_m_per_ns: float | None = None, **kwargs) -> list[SubterraRecord]:
        """Records only. See `load()` for records plus the file's SurveyFrame."""
        return self.load(path, dataset_id=dataset_id, sensor_type=sensor_type,
                         velocity_m_per_ns=velocity_m_per_ns, **kwargs).records

    def load(self, path, dataset_id: str, sensor_type: SensorType = SensorType.GPR,
             velocity_m_per_ns: float | None = None, **kwargs) -> ConversionResult:
        """
        `velocity_m_per_ns` is an EXPLICIT declaration by the caller of the
        electromagnetic propagation velocity to use for time-to-depth
        conversion. The dataset does not supply a usable one -- the value in
        its header is an operator display setting, not a site measurement --
        so without this argument `depth` stays None and the records carry
        only the measured time axis.

        Supplying it derives depth as `two_way_time_ns * velocity / 2`. The
        result is ASSUMED, not measured, and is labelled as such throughout.
        """
        path = Path(path)
        parsed = parse_dt(path)
        samples = parsed["samples"]
        n_traces, n_samples = parsed["n_traces"], parsed["n_samples"]
        # Raises rather than proceeding without a real time axis.
        time_axis = derive_time_axis(parsed["acquisition"], n_samples)
        interval_ns = time_axis["sample_interval_ns"]
        frame_id = make_frame_id(dataset_id, path.name)

        along_track, along_track_rejected = derive_along_track(parsed["acquisition"])
        if along_track_rejected:
            logger.warning(
                f"IDSDTConverter: {path.name}: {along_track_rejected}. Records will carry "
                f"NoPosition; no along-track coordinate is available."
            )

        velocity, velocity_rejected = validate_velocity(velocity_m_per_ns)
        if velocity_rejected and velocity_m_per_ns is not None:
            logger.warning(
                f"IDSDTConverter: {path.name}: {velocity_rejected}. Depth will NOT be derived; "
                f"records keep the measured time axis only."
            )

        # One record per (trace, sample), matching SEGYConverter's shape so the
        # existing trace/depth tooling sees a familiar structure.
        no_position = NoPosition(
            reason=(along_track_rejected or _NO_POSITION_REASON)
            if along_track is None else _NO_POSITION_REASON
        )
        spacing = along_track["trace_spacing_m"] if along_track else None

        records: list[SubterraRecord] = []
        for trace_index in range(n_traces):
            row = samples[trace_index]
            # The wheel encoder locates each trace ALONG ITS OWN LINE. That is
            # a real measurement, but it is not a position on Earth, so it is
            # an odometry coordinate and never a geographic one.
            position = (
                OdometryPosition(along_track_m=trace_index * spacing, path_id=path.stem)
                if spacing is not None else no_position
            )
            for sample_index in range(n_samples):
                records.append(SubterraRecord(
                    dataset_id=dataset_id,
                    sensor_type=sensor_type,
                    # No geographic position exists for this format, so the
                    # legacy view is left unset rather than fabricated.
                    latitude=None, longitude=None,
                    position=position,
                    frame_id=frame_id,
                    elevation=None,
                    # Depth exists ONLY when the caller supplied a velocity.
                    # The measured time axis below is preserved either way.
                    depth=(two_way_time_to_depth(sample_index * interval_ns, velocity)
                           if velocity is not None else None),
                    signal=[float(row[sample_index])],
                    metadata={
                        "source_file": path.name,
                        "trace_index": trace_index,
                        "sample_index": sample_index,
                        "two_way_time_ns": sample_index * interval_ns,
                        **({"along_track_m": trace_index * spacing,
                            "trace_spacing_m": spacing}
                           if spacing is not None else {}),
                        **({"velocity_m_per_ns": velocity,
                            "velocity_source": "supplied_by_caller",
                            "depth_is_velocity_derived": True}
                           if velocity is not None else {}),
                        "position_source": (
                            "ids_wheel_odometry" if spacing is not None else "none"),
                        "trace_count": n_traces,
                        "sample_count": n_samples,
                    },
                ))

        logger.info(
            f"IDSDTConverter: parsed {path.name} -> {n_traces} traces x {n_samples} samples "
            f"({len(records):,} records), version={parsed['version']}"
        )
        return ConversionResult(records=records, frames=[self._build_frame(
            path, dataset_id, sensor_type, parsed, frame_id, time_axis,
            velocity, velocity_rejected, along_track, along_track_rejected)])

    @staticmethod
    def _along_track_assumption(along_track, rejected) -> Assumption:
        """States whether an along-track coordinate exists and where it came from."""
        if along_track is None:
            return Assumption(
                key="along_track_unavailable", value=None,
                basis=(
                    f"No along-track coordinate: {rejected or 'trace spacing not recoverable'}. "
                    f"Records carry NoPosition."
                ),
                verified=True,
            )
        return Assumption(
            key="along_track_spacing", value=along_track["trace_spacing_m"],
            basis=(
                f"MEASURED: wheel-encoder trace spacing from the .dt H record, in metres "
                f"(Ini000N.ini corroborates it as data_x_cell = Wheel_Compress * Wheel_dx, "
                f"with Wheel_dx = {along_track['wheel_dx_m']} m). The duplicate field agrees: "
                f"{along_track['duplicate_field_agrees']}. This positions traces along their "
                f"own line; it does NOT georeference the line."
            ),
            verified=bool(along_track["duplicate_field_agrees"]),
        )

    @staticmethod
    def _depth_assumption(velocity, velocity_rejected, time_axis) -> Assumption:
        """States, in the data, whether a depth axis exists and on whose authority."""
        if velocity is not None:
            return Assumption(
                key="depth_conversion", value=velocity,
                basis=(
                    f"SUPPLIED BY CALLER: depth was derived as two_way_time_ns * {velocity} / 2 "
                    f"(m/ns). This velocity was NOT recovered from the dataset -- the file's own "
                    f"header value ({time_axis['configured_velocity_m_per_s']} m/s) is an operator "
                    f"display setting, not a site measurement. The resulting depth is ASSUMED, "
                    f"not measured; the measured two-way time axis is preserved alongside it."
                ),
                verified=False,
            )
        reason = velocity_rejected or "no velocity supplied"
        return Assumption(
            key="depth_not_derived", value=time_axis["configured_velocity_m_per_s"],
            basis=(
                f"record.depth is unset because {reason}. The H record does carry a propagation "
                f"velocity, but it is whatever the operator configured (3.0e8 m/s -- vacuum -- on "
                f"some lines, 1.0e8 m/s on others), not a site measurement, so it is not applied. "
                f"Supply velocity_m_per_ns explicitly to derive depth."
            ),
            verified=False,
        )

    def _build_frame(self, path: Path, dataset_id: str, sensor_type: SensorType,
                     parsed: dict, frame_id: str, time_axis: dict,
                     velocity: float | None = None,
                     velocity_rejected: str | None = None,
                     along_track: dict | None = None,
                     along_track_rejected: str | None = None) -> SurveyFrame:
        header = parsed["header"]
        companions = sorted(
            p.name for p in path.parent.iterdir()
            if p.is_file() and p != path and not p.name.startswith("._")
        ) if path.parent.exists() else []

        assumptions = [
            Assumption(
                key="coordinates", value=None,
                basis=(
                    "IDS .dt carries no per-trace coordinates. Position is recorded as "
                    "NoPosition rather than defaulted; a georeferenced result would need an "
                    "external track supplied alongside the acquisition."
                ),
                verified=True,
            ),
            Assumption(
                key="time_window", value=time_axis["time_window_ns"],
                basis=(
                    f"MEASURED: read from the .dt H record's sweep-time field (ns). "
                    f"Sample interval {time_axis['sample_interval_ns']:.6g} ns = window / "
                    f"{time_axis['n_samples']} samples. Duplicate field agrees: "
                    f"{time_axis['duplicate_field_agrees']}; the file's own vertical cell size "
                    f"agrees: {time_axis['stored_cell_size_agrees']}."
                ),
                verified=bool(time_axis["duplicate_field_agrees"]
                              and time_axis["stored_cell_size_agrees"]),
            ),
            self._depth_assumption(velocity, velocity_rejected, time_axis),
            self._along_track_assumption(along_track, along_track_rejected),
            Assumption(
                key="format_specification", value="reverse-engineered",
                basis=(
                    "IDS .dt is not publicly specified. The layout was established by inspecting "
                    "real files from Zenodo record 14637589 and cross-checked against RGPR's "
                    "documented readDT(). Fields beyond those read here remain uninterpreted."
                ),
                verified=False,
            ),
        ]

        return SurveyFrame(
            frame_id=frame_id,
            dataset_id=dataset_id,
            modality=sensor_type,
            modality_source="user_supplied",
            source_format=self.format_name,
            source_file=path.name,
            spatial_ref=(
                SpatialRef(
                    kind=CRSKind.ACQUISITION,
                    name=(
                        "along-track distance from the wheel encoder. IDS .dt carries no "
                        "geographic or projected coordinates, so this locates traces along "
                        "their own survey line only."
                    ),
                    horizontal_units="m",
                    origin_description=(
                        f"trace 0 of {path.name}; spacing "
                        f"{along_track['trace_spacing_m']} m per trace"
                    ),
                )
                if along_track is not None
                else SpatialRef(kind=CRSKind.UNKNOWN, name=_NO_POSITION_REASON)
            ),
            vertical_axis=VerticalAxis(
                # The axis this frame MEASURES is always two-way time. When a
                # velocity was supplied, `conversion` records the derived
                # depth; its absence means no depth exists.
                kind=AxisKind.TWO_WAY_TIME_NS,
                units="ns",
                origin="instrument time-zero at each trace",
                positive_down=True,
                n_samples=parsed["n_samples"],
                sample_interval=time_axis["sample_interval_ns"],
                conversion=({
                    "method": "constant_velocity",
                    "velocity_m_per_ns": velocity,
                    "velocity_source": "supplied_by_caller",
                    "formula": "depth_m = two_way_time_ns * velocity_m_per_ns / 2",
                    "target_axis": AxisKind.DEPTH_M.value,
                    "derived_not_measured": True,
                } if velocity is not None else None),
            ),
            n_positions=parsed["n_traces"],
            position_index_name="trace_index",
            assumptions=assumptions,
            source_metadata={
                "ids_version": ".".join(str(v) for v in parsed["version"]),
                "record_length_bytes": parsed["len_rec"],
                "data_start_offset": parsed["data_start"],
                "trailing_bytes": parsed["trailing_bytes"],
                "header_records": {k: (list(v) if isinstance(v, tuple) else v)
                                   for k, v in header.items()},
                "survey_id": header.get("I"),
                "acquired_at_raw": header.get("C"),
                "zone": header.get("FZ"),
                "antenna_raw": header.get("ATR"),
                "channels_raw": header.get("S"),
                "time_axis": time_axis,
                "along_track": along_track,
                "companion_files": companions,
            },
        )
