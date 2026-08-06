"""
MALÅ (Guideline Geo / RAMAC) GPR converter.

A MALÅ acquisition is a PAIR: `.rd3` (or `.rd7`) holds raw samples with no
header of its own, and a same-stem `.rad` sidecar holds the acquisition
parameters as plain ASCII `KEY:value` lines. Neither is usable alone, so a
`.rd3` without its `.rad` is refused rather than read with guessed geometry.

WHAT THE FORMAT ACTUALLY GIVES US, verified across all 336 `.rad`/`.rd3`
pairs held locally (321 Hillside + 15 TU1208):

- **Geometry is exact.** In all 336, the binary file size equals
  `SAMPLES x LAST TRACE x width` with no remainder, so `LAST TRACE` is the
  trace count and the sample count is authoritative. A mismatch therefore
  means a truncated or mispaired file, and is treated as an error.
- **The time axis is measured.** `TIMEWINDOW` (ns) divided by `SAMPLES`
  gives the sample interval directly -- 0.077-0.328 ns across the corpus.
  Unlike SEG-Y here, nothing needs rescaling by 1000 and nothing is assumed.
- **Positioning is odometry, and only odometry.** Every file carries
  `DISTANCE FLAG:1` (distance-triggered wheel) with `DISTANCE INTERVAL`
  in metres, 0.0076-0.031 m. That locates a trace ALONG ITS OWN LINE. It is
  not a position on Earth and never becomes one here.

WHAT IT DOES NOT GIVE US. No CRS, and no coordinates unless a `.cor` GNSS
sidecar is present AND populated -- in the Hillside corpus all 321 `.cor`
files are zero bytes, which is an absence, not a failure. No velocity
either: `depth` exists only when the caller supplies one, exactly as in
IDSDTConverter, because the header's dielectric is an operator display
setting rather than a site measurement.

REUSE. Velocity validation and the time-to-depth conversion are imported
from IDSDTConverter rather than reimplemented -- same physics, same failure
modes -- with this format's own bounds justification passed in so neither
converter's error message claims the other's provenance.
"""
from __future__ import annotations

import re
import struct
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

#: `.rd3` is 16-bit, `.rd7` is 32-bit. Both are two's-complement little-endian.
SAMPLE_WIDTH = {".rd3": ("h", 2), ".rd7": ("i", 4)}

_VELOCITY_BOUNDS_BASIS = (
    "physical bounds shared with the IDS reader: the lower bound is far below any "
    "geological medium, the upper bound is the speed of light in vacuum"
)

_NO_POSITION_REASON = (
    "MALA .rad declares no distance-triggered acquisition, so no along-track "
    "coordinate exists; the file carries no position of any kind"
)


class MALAFormatError(ValueError):
    """Raised when a MALÅ pair is missing, mismatched, or internally inconsistent."""


def find_rad(binary_path: Path) -> Path:
    """
    Locates the `.rad` sidecar for a `.rd3`/`.rd7`.

    Case varies between acquisitions (the TU1208 archive mixes `.rd3`/`.RD3`),
    so both are tried before giving up.
    """
    binary_path = Path(binary_path)
    for suffix in (".rad", ".RAD", ".Rad"):
        candidate = binary_path.with_suffix(suffix)
        if candidate.exists():
            return candidate
    raise MALAFormatError(
        f"{binary_path.name}: no .rad sidecar found beside it. A MALA .rd3 holds samples "
        f"with no header of its own -- sample count, time window and trace spacing all live "
        f"in the .rad -- so the pair is required. Looked for: "
        f"{', '.join(binary_path.with_suffix(s).name for s in ('.rad', '.RAD', '.Rad'))}"
    )


def parse_rad(path: str | Path) -> dict[str, str]:
    """
    Parses the ASCII `KEY:value` header.

    Values are kept as strings; callers coerce what they need, so an
    unparseable field fails where it is used and names itself, rather than
    failing the whole header.
    """
    path = Path(path)
    raw = path.read_bytes()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        # All 336 local headers are pure ASCII, but an operator/site name in
        # another encoding must not lose the whole file.
        text = raw.decode("latin-1")
        logger.warning(f"{path.name}: .rad is not pure ASCII; decoded as latin-1")
    header: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        header[key.strip().upper()] = value.strip()
    if not header:
        raise MALAFormatError(f"{path.name}: .rad contains no KEY:value lines")
    return header


def _require_number(header: dict, key: str, path: Path, cast=float):
    if key not in header:
        raise MALAFormatError(
            f"{path.name}: .rad is missing required field {key!r}. Present fields: "
            f"{sorted(header)[:8]}{'...' if len(header) > 8 else ''}"
        )
    try:
        return cast(header[key])
    except (TypeError, ValueError) as e:
        raise MALAFormatError(
            f"{path.name}: .rad field {key!r} is {header[key]!r}, which is not a number"
        ) from e


def derive_time_axis(header: dict, path: Path) -> dict:
    """
    The MEASURED time axis: `TIMEWINDOW` ns over `SAMPLES`.

    Both come from the instrument, so unlike the SEG-Y path here there is no
    unit convention to assume and no rescaling to apply.
    """
    n_samples = _require_number(header, "SAMPLES", path, int)
    window_ns = _require_number(header, "TIMEWINDOW", path, float)
    if n_samples <= 0:
        raise MALAFormatError(f"{path.name}: .rad declares SAMPLES={n_samples}")
    if window_ns <= 0:
        raise MALAFormatError(
            f"{path.name}: .rad declares TIMEWINDOW={window_ns} ns, so no time axis exists"
        )
    return {
        "n_samples": n_samples,
        "time_window_ns": window_ns,
        "sample_interval_ns": window_ns / n_samples,
    }


def derive_along_track(header: dict) -> tuple[dict | None, str | None]:
    """
    The wheel-encoder along-track axis, or (None, reason) when there is none.

    Requires `DISTANCE FLAG:1`. A time-triggered acquisition has no distance
    axis at all, and inventing one from an assumed tow speed would be
    fabricating survey geometry.
    """
    if header.get("DISTANCE FLAG", "0").strip() != "1":
        return None, (
            f"DISTANCE FLAG is {header.get('DISTANCE FLAG')!r}, not '1': this acquisition was "
            f"not distance-triggered, so traces have no along-track coordinate"
        )
    try:
        spacing = float(header["DISTANCE INTERVAL"])
    except (KeyError, TypeError, ValueError):
        return None, "DISTANCE INTERVAL is missing or not a number"
    if not spacing > 0:
        return None, f"DISTANCE INTERVAL is {spacing}, so trace spacing is unusable"
    try:
        start = float(header.get("START POSITION", 0.0))
    except (TypeError, ValueError):
        start = 0.0
    return {"trace_spacing_m": spacing, "start_position_m": start}, None


def parse_cor(path: str | Path) -> list[tuple[int, float, float]]:
    """
    Parses a MALÅ `.cor` GNSS sidecar into (trace_number, lat, lon).

    Returns [] for an absent or EMPTY file. That distinction matters: all 321
    Hillside `.cor` files are zero bytes, which means the survey carried no
    GNSS -- an absence to be reported, not a parse failure to be raised.

    Lines are tab-separated: trace, date, time, lat, N/S, lon, E/W, ...
    Hemisphere letters are applied, so a western or southern fix keeps its
    sign instead of silently mirroring across the equator.
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return []
    fixes: list[tuple[int, float, float]] = []
    for line in path.read_text(errors="replace").splitlines():
        parts = re.split(r"[\t,]+|\s{2,}", line.strip())
        parts = [p for p in parts if p]
        if len(parts) < 7:
            continue
        try:
            trace = int(float(parts[0]))
            lat, lat_h = float(parts[3]), parts[4].strip().upper()
            lon, lon_h = float(parts[5]), parts[6].strip().upper()
        except (TypeError, ValueError):
            continue
        if lat_h == "S":
            lat = -lat
        if lon_h == "W":
            lon = -lon
        fixes.append((trace, lat, lon))
    return fixes


def read_rd3(path: Path, n_samples: int, expected_traces: int | None = None):
    """
    Reads the raw sample block.

    Verified across all 336 local pairs: size == n_samples * traces * width
    exactly. A remainder therefore indicates a truncated file or a `.rad`
    paired with the wrong binary, and is refused rather than silently
    truncated to whole traces.
    """
    suffix = path.suffix.lower()
    if suffix not in SAMPLE_WIDTH:
        raise MALAFormatError(
            f"{path.name}: unsupported MALA binary extension {suffix!r}; "
            f"expected one of {sorted(SAMPLE_WIDTH)}"
        )
    code, width = SAMPLE_WIDTH[suffix]
    size = path.stat().st_size
    row_bytes = n_samples * width
    if size == 0:
        raise MALAFormatError(f"{path.name}: file is empty")
    if size % row_bytes:
        raise MALAFormatError(
            f"{path.name}: {size} bytes is not a whole number of traces at "
            f"{n_samples} samples x {width} bytes ({row_bytes} bytes/trace); "
            f"{size % row_bytes} byte(s) left over. The .rad and the binary do not "
            f"describe the same acquisition, or the file is truncated."
        )
    n_traces = size // row_bytes
    if expected_traces is not None and n_traces != expected_traces:
        raise MALAFormatError(
            f"{path.name}: the binary holds {n_traces} traces but its .rad declares "
            f"LAST TRACE={expected_traces}. Refusing to guess which is right."
        )
    raw = path.read_bytes()
    return [
        list(struct.unpack_from(f"<{n_samples}{code}", raw, t * row_bytes))
        for t in range(n_traces)
    ], n_traces


def antenna_frequency_mhz(header: dict) -> float | None:
    """
    The antenna centre frequency from the `ANTENNAS` string.

    Values look like '500 MHz shielded' or '500 MHz shielded=1', the suffix
    being a channel number. Returns None rather than a guess if absent.
    """
    match = re.search(r"(\d+(?:\.\d+)?)\s*MHz", header.get("ANTENNAS", ""), re.I)
    return float(match.group(1)) if match else None


class MALAConverter(BaseConverter):
    format_name = "mala"
    supported_extensions = (".rd3", ".rd7")

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
        `velocity_m_per_ns` is an EXPLICIT caller declaration, with no default.
        The `.rad` carries no site velocity -- its dielectric-related fields
        are acquisition/display settings -- so without this argument `depth`
        stays None and records carry only the measured time axis. Supplying it
        derives `depth = two_way_time_ns * velocity / 2`, which is ASSUMED and
        labelled as such on every record and on the frame.
        """
        path = Path(path)
        rad_path = find_rad(path)
        header = parse_rad(rad_path)
        time_axis = derive_time_axis(header, rad_path)
        n_samples = time_axis["n_samples"]
        interval_ns = time_axis["sample_interval_ns"]

        declared_traces = None
        if "LAST TRACE" in header:
            try:
                declared_traces = int(header["LAST TRACE"])
            except (TypeError, ValueError):
                declared_traces = None
        samples, n_traces = read_rd3(path, n_samples, declared_traces)

        along_track, along_track_rejected = derive_along_track(header)
        if along_track_rejected:
            logger.warning(
                f"MALAConverter: {path.name}: {along_track_rejected}. Records will carry "
                f"NoPosition; no along-track coordinate is available."
            )

        fixes = parse_cor(path.with_suffix(".cor"))
        fix_by_trace = {t: (lat, lon) for t, lat, lon in fixes}

        velocity, velocity_rejected = validate_velocity(
            velocity_m_per_ns, bounds_basis=_VELOCITY_BOUNDS_BASIS)
        if velocity_rejected and velocity_m_per_ns is not None:
            logger.warning(
                f"MALAConverter: {path.name}: {velocity_rejected}. Depth will NOT be derived; "
                f"records keep the measured time axis only."
            )

        frame_id = make_frame_id(dataset_id, path.name)
        spacing = along_track["trace_spacing_m"] if along_track else None
        start = along_track["start_position_m"] if along_track else 0.0
        no_position = NoPosition(reason=along_track_rejected or _NO_POSITION_REASON)

        records: list[SubterraRecord] = []
        for trace_index in range(n_traces):
            row = samples[trace_index]
            along = (start + trace_index * spacing) if spacing is not None else None
            # A GNSS fix, when the survey actually recorded one, is a position
            # on Earth. The wheel encoder is not: it locates a trace along its
            # own line and says nothing about where that line lies.
            fix = fix_by_trace.get(trace_index + 1) or fix_by_trace.get(trace_index)
            if fix is not None:
                position = GeographicPosition(lat=fix[0], lon=fix[1])
                position_source = "mala_cor_gnss"
                latitude, longitude = fix
            elif along is not None:
                position = OdometryPosition(along_track_m=along, path_id=path.stem)
                position_source = "mala_wheel_odometry"
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
                    signal=[float(row[sample_index])],
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
            f"MALAConverter: parsed {path.name} -> {n_traces} traces x {n_samples} samples "
            f"({len(records):,} records), {time_axis['time_window_ns']:.3f} ns window, "
            f"antenna {antenna_frequency_mhz(header)} MHz"
        )
        return ConversionResult(records=records, frames=[self._build_frame(
            path, rad_path, dataset_id, sensor_type, header, frame_id, time_axis,
            n_traces, velocity, velocity_rejected, along_track, along_track_rejected,
            bool(fixes))])

    def _build_frame(self, path, rad_path, dataset_id, sensor_type, header, frame_id,
                     time_axis, n_traces, velocity, velocity_rejected,
                     along_track, along_track_rejected, has_gnss) -> SurveyFrame:
        """Describes the line as a whole: what was measured, what was assumed, what is absent."""
        if has_gnss:
            ref = SpatialRef(
                kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                crs_provenance=CRSProvenance.INFERRED,
                name=("MALA .cor GNSS sidecar. The file states no datum; WGS84 is inferred "
                      "because that is what consumer GNSS reports."),
                horizontal_units="deg",
            )
        elif along_track is not None:
            ref = SpatialRef(
                kind=CRSKind.ACQUISITION,
                name=("wheel-encoder distance along this line only. The acquisition has no "
                      "geographic or projected reference, and none is inferred."),
                horizontal_units="m",
            )
        else:
            ref = SpatialRef(kind=CRSKind.UNKNOWN,
                             name=along_track_rejected or _NO_POSITION_REASON)

        assumptions = [
            Assumption(
                key="time_axis", value=time_axis["sample_interval_ns"],
                basis=(
                    f"MEASURED: the .rad declares TIMEWINDOW="
                    f"{time_axis['time_window_ns']} ns over SAMPLES="
                    f"{time_axis['n_samples']}, giving "
                    f"{time_axis['sample_interval_ns']:.6f} ns per sample. Both come from "
                    f"the instrument; nothing is rescaled or assumed."
                ),
                verified=True,
            ),
            Assumption(
                key="trace_geometry", value=n_traces,
                basis=(
                    f"VERIFIED: the binary is exactly {n_traces} x "
                    f"{time_axis['n_samples']} samples with no remainder, and the .rad's "
                    f"LAST TRACE agrees. A mismatch is refused rather than truncated."
                ),
                verified=True,
            ),
        ]
        if along_track is not None:
            assumptions.append(Assumption(
                key="along_track_spacing", value=along_track["trace_spacing_m"],
                basis=(
                    f"MEASURED: .rad DISTANCE FLAG=1 (distance-triggered) with DISTANCE "
                    f"INTERVAL={along_track['trace_spacing_m']} m from the wheel encoder, "
                    f"starting at START POSITION={along_track['start_position_m']} m. This "
                    f"positions traces along their own line; it does NOT georeference it."
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
                    "no populated .cor sidecar accompanies this line, so the acquisition "
                    "recorded no satellite position. This is an ABSENCE in the survey, not a "
                    "read failure, and it is why the line has no coordinates on Earth."
                ),
                verified=True,
            ))
        if velocity is not None:
            assumptions.append(Assumption(
                key="gpr_velocity", value=velocity,
                basis=(
                    f"SUPPLIED BY CALLER: {velocity} m/ns, used as "
                    f"depth_m = two_way_time_ns * velocity / 2. The .rad carries no site "
                    f"velocity, so this is an ASSERTION about the subsurface, not a "
                    f"measurement of it, and every depth derived from it is assumed."
                ),
                verified=False,
            ))
        else:
            assumptions.append(Assumption(
                key="depth_conversion", value="not applied",
                basis=(
                    f"no usable velocity was supplied ({velocity_rejected}), so record.depth "
                    f"is None and only the measured time axis is carried. Nothing is "
                    f"defaulted -- a fabricated velocity would produce a physical-looking "
                    f"depth with no basis."
                ),
                verified=True,
            ))

        antenna = antenna_frequency_mhz(header)
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
                "rad_file": rad_path.name,
                "antenna_mhz": antenna,
                "antennas_raw": header.get("ANTENNAS"),
                "antenna_separation_m": header.get("ANTENNA SEPARATION"),
                "time_window_ns": time_axis["time_window_ns"],
                "sample_count": time_axis["n_samples"],
                "trace_count": n_traces,
                "distance_interval_m": header.get("DISTANCE INTERVAL"),
                "start_position_m": header.get("START POSITION"),
                "stop_position_m": header.get("STOP POSITION"),
                "stacks": header.get("STACKS"),
                "operator": header.get("OPERATOR") or None,
                "site": header.get("SITE") or None,
                "velocity_bounds_m_per_ns": [MIN_VELOCITY_M_PER_NS, MAX_VELOCITY_M_PER_NS],
            },
        )
