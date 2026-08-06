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

WHAT THE FORMAT DOES NOT CARRY. Verified across every file in the sample:
no coordinates (FX/AH are 0.000000E+00 throughout), no CRS, and no
declared time window or sample interval. Consequently this converter emits
NoPosition and leaves `depth` unset rather than inventing either. The
sample axis is two-way travel time by construction, but without the
acquisition software's time window a sample index cannot be converted to
nanoseconds or to depth, so `sample_interval` is left None and the frame
says so explicitly.

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
    Assumption, AxisKind, CRSKind, NoPosition, SpatialRef, VerticalAxis,
)
from schemas.subterra_record import SubterraRecord, SensorType
from schemas.survey_frame import SurveyFrame, make_frame_id
from utils.logger import get_logger

logger = get_logger(__name__)

MAGIC = b"V"
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
                **kwargs) -> list[SubterraRecord]:
        """Records only. See `load()` for records plus the file's SurveyFrame."""
        return self.load(path, dataset_id=dataset_id, sensor_type=sensor_type, **kwargs).records

    def load(self, path, dataset_id: str, sensor_type: SensorType = SensorType.GPR,
             **kwargs) -> ConversionResult:
        path = Path(path)
        parsed = parse_dt(path)
        samples = parsed["samples"]
        n_traces, n_samples = parsed["n_traces"], parsed["n_samples"]
        frame_id = make_frame_id(dataset_id, path.name)

        # One record per (trace, sample), matching SEGYConverter's shape so the
        # existing trace/depth tooling sees a familiar structure.
        position = NoPosition(reason=_NO_POSITION_REASON)
        records: list[SubterraRecord] = []
        for trace_index in range(n_traces):
            row = samples[trace_index]
            for sample_index in range(n_samples):
                records.append(SubterraRecord(
                    dataset_id=dataset_id,
                    sensor_type=sensor_type,
                    latitude=0.0, longitude=0.0,   # legacy view; `position` is the truth
                    position=position,
                    frame_id=frame_id,
                    elevation=None,
                    # No time window and no velocity are declared by the format,
                    # so a depth cannot be derived and is not invented.
                    depth=None,
                    signal=[float(row[sample_index])],
                    metadata={
                        "source_file": path.name,
                        "trace_index": trace_index,
                        "sample_index": sample_index,
                        "position_source": "none",
                        "trace_count": n_traces,
                        "sample_count": n_samples,
                    },
                ))

        logger.info(
            f"IDSDTConverter: parsed {path.name} -> {n_traces} traces x {n_samples} samples "
            f"({len(records):,} records), version={parsed['version']}"
        )
        return ConversionResult(records=records, frames=[self._build_frame(
            path, dataset_id, sensor_type, parsed, frame_id)])

    def _build_frame(self, path: Path, dataset_id: str, sensor_type: SensorType,
                     parsed: dict, frame_id: str) -> SurveyFrame:
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
                key="time_axis_unresolved", value="sample index only",
                basis=(
                    "The format declares no time window or sample interval, so a sample index "
                    "cannot be converted to nanoseconds, and without a velocity model it cannot "
                    "be converted to depth either. record.depth is therefore unset."
                ),
                verified=True,
            ),
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
            spatial_ref=SpatialRef(
                kind=CRSKind.UNKNOWN,
                name=_NO_POSITION_REASON,
            ),
            vertical_axis=VerticalAxis(
                kind=AxisKind.TWO_WAY_TIME_NS,
                units="ns",
                origin="instrument time-zero at each trace",
                positive_down=True,
                n_samples=parsed["n_samples"],
                # None is the machine-readable "the scale of this axis is unknown".
                sample_interval=None,
                conversion=None,
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
                "companion_files": companions,
            },
        )
