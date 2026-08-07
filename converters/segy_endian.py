"""
Reading SEG-Y files that were written little-endian.

WHY THIS EXISTS. SEG-Y rev 0/1 specifies big-endian, and `segyio` enforces
it. Several GPR vendors ignore that and write the whole file -- binary
header, trace headers and samples -- in the host's little-endian order. The
4TU Netherlands utility survey is one: all 759 of its `.sgy` files are
little-endian, and segyio rejects every one with

    RuntimeError: trace count inconsistent with file size

because it reads the sample count as 2 instead of 512 and the implied trace
length no longer divides the file.

HOW IT AVOIDS BREAKING BIG-ENDIAN. `detect_endianness` treats little-endian
strictly as a RESCUE: it is chosen only when the big-endian reading is
INVALID and the little-endian reading is VALID. Any file segyio can already
open keeps taking the segyio path byte for byte, so no existing dataset can
change behaviour no matter what this module concludes.

HOW IT AVOIDS DUPLICATING THE CONVERTER. `LittleEndianSegyFile` presents
the same surface the converter already uses from a segyio handle --
`tracecount`, `samples`, `trace[i]`, `header[i]`, `bin` -- keyed by the same
`segyio.TraceField` / `segyio.BinField` offsets. The converter's record-
building loop is therefore shared verbatim between the two readers rather
than written twice.

WHAT IT DOES NOT DO. It does not guess what the coordinates MEAN. Deciding
that a 4-byte field holds an IEEE float rather than the standard integer is
a semantic judgement the bytes cannot settle, so it stays a caller
declaration (`coordinate_encoding`), exactly like `crs`.
"""
from __future__ import annotations

import struct
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)

TEXTUAL_HEADER_BYTES = 3200
BINARY_HEADER_BYTES = 400
HEADER_BYTES = TEXTUAL_HEADER_BYTES + BINARY_HEADER_BYTES   # 3600
TRACE_HEADER_BYTES = 240

BIG, LITTLE = "big", "little"
_STRUCT = {BIG: ">", LITTLE: "<"}

#: SEG-Y data-sample format codes this reader can decode, and their widths.
#: Code 1 (IBM 4-byte float) is deliberately absent -- see UNSUPPORTED_FORMATS.
SAMPLE_FORMATS = {
    2: ("i", 4),    # 4-byte two's complement integer
    3: ("h", 2),    # 2-byte two's complement integer
    5: ("f", 4),    # 4-byte IEEE float
    8: ("b", 1),    # 1-byte two's complement integer
}

#: Format codes that are valid SEG-Y but that this reader refuses rather
#: than decoding approximately. Listed so callers get a precise message.
UNSUPPORTED_FORMATS = {
    1: "IBM 4-byte floating point (rev-0 mainframe format; needs a mantissa/exponent conversion)",
    4: "4-byte fixed point with gain (withdrawn in SEG-Y rev 1)",
    6: "reserved",
    7: "reserved",
}

#: Every format code the standard defines, valid or not -- used to judge
#: whether a binary header was read in the right byte order.
ALL_FORMAT_CODES = set(SAMPLE_FORMATS) | set(UNSUPPORTED_FORMATS)

# Byte offsets within the 400-byte binary header (0-based within the block).
_BH_INTERVAL = 16     # bytes 3217-3218, 1-based
_BH_SAMPLES = 20      # bytes 3221-3222
_BH_FORMAT = 24       # bytes 3225-3226

# segyio's BinField/TraceField keys are 1-based byte positions, so the
# adapter's dicts use the same integers and `header.get(TraceField.SourceX)`
# resolves without segyio being involved.
BIN_INTERVAL, BIN_SAMPLES, BIN_FORMAT = 3217, 3221, 3225
TF_RECV_ELEVATION, TF_SOURCE_SURFACE_ELEVATION = 41, 45
TF_SCALAR, TF_SOURCE_X, TF_SOURCE_Y = 71, 73, 77
TF_GROUP_X, TF_GROUP_Y = 81, 85
TF_SCALAR_TRACE_HEADER = 69
TF_DELAY = 109
TF_SAMPLE_COUNT, TF_SAMPLE_INTERVAL = 115, 117


class SegyEndianError(ValueError):
    """Raised when a SEG-Y file cannot be read in either byte order."""


class SegyFormatError(ValueError):
    """Raised when the sample format is valid SEG-Y but unsupported here."""


def _read_binary_header(path: Path) -> bytes:
    size = path.stat().st_size
    if size < HEADER_BYTES:
        raise SegyEndianError(
            f"{path.name}: {size} bytes is shorter than a SEG-Y header ({HEADER_BYTES} bytes); "
            f"this is not a SEG-Y file"
        )
    with open(path, "rb") as f:
        f.seek(TEXTUAL_HEADER_BYTES)
        return f.read(BINARY_HEADER_BYTES)


def _reading(block: bytes, order: str) -> dict:
    """The binary header's three structural fields under one byte order."""
    s = _STRUCT[order]
    return {
        "interval": struct.unpack(s + "h", block[_BH_INTERVAL:_BH_INTERVAL + 2])[0],
        "samples": struct.unpack(s + "h", block[_BH_SAMPLES:_BH_SAMPLES + 2])[0],
        "format": struct.unpack(s + "h", block[_BH_FORMAT:_BH_FORMAT + 2])[0],
    }


def _assess(reading: dict, file_size: int) -> dict:
    """
    Whether a byte order yields a self-consistent file.

    Two independent checks, because either alone is weak: the format code
    must be one the standard defines, and the implied trace length must
    divide the file body exactly. A wrong byte order essentially never
    satisfies both.
    """
    fmt, ns = reading["format"], reading["samples"]
    code_ok = fmt in ALL_FORMAT_CODES
    count_ok = ns > 0
    width = SAMPLE_FORMATS.get(fmt, (None, None))[1]
    body = file_size - HEADER_BYTES
    divides = None
    if code_ok and count_ok and width is not None:
        record = TRACE_HEADER_BYTES + ns * width
        divides = body > 0 and body % record == 0
    return {
        **reading,
        "format_code_defined": code_ok,
        "sample_count_positive": count_ok,
        "body_divides_evenly": divides,
        # `divides is None` means the code is defined but unsupported here,
        # so the record length is unknown -- not evidence against the order.
        "valid": bool(code_ok and count_ok and divides is not False),
    }


def detect_endianness(path: str | Path) -> tuple[str, dict]:
    """
    Returns ("big" | "little", evidence).

    BIG-ENDIAN WINS EVERY TIE. Little-endian is returned only when the
    big-endian reading is invalid and the little-endian one is valid. That
    asymmetry is the whole safety argument: a file that already parses as
    big-endian cannot be rerouted by this function, so adding little-endian
    support cannot alter any existing dataset's output.
    """
    path = Path(path)
    block = _read_binary_header(path)
    size = path.stat().st_size
    big = _assess(_reading(block, BIG), size)
    little = _assess(_reading(block, LITTLE), size)

    if big["valid"]:
        order = BIG
    elif little["valid"]:
        order = LITTLE
        logger.info(
            f"{path.name}: big-endian reading is invalid (format code {big['format']}, "
            f"{big['samples']} samples/trace) but little-endian is consistent "
            f"(format code {little['format']}, {little['samples']} samples/trace). "
            f"Reading as little-endian SEG-Y."
        )
    else:
        raise SegyEndianError(
            f"{path.name}: not readable in either byte order. Big-endian gives format code "
            f"{big['format']} with {big['samples']} samples/trace; little-endian gives format "
            f"code {little['format']} with {little['samples']}. Neither is a self-consistent "
            f"SEG-Y header, so the file is malformed, truncated, or not SEG-Y."
        )
    return order, {"chosen": order, "big": big, "little": little, "file_size": size}


def int32_as_float32(value: int, order: str) -> float:
    """
    Reinterprets a 4-byte header field's bits as an IEEE float.

    The bytes are the same either way; only the interpretation differs. This
    exists because some vendors write floating-point coordinates into
    SourceX/SourceY, which the standard defines as integers.
    """
    s = _STRUCT[order]
    return struct.unpack(s + "f", struct.pack(s + "i", int(value)))[0]


def nmea_to_degrees(value: float) -> float:
    """
    Converts NMEA `ddmm.mmmm` (or `dddmm.mmmm`) to decimal degrees.

    5214.3369 -> 52 + 14.3369/60 -> 52.23895. Sign is preserved, so a
    western longitude or southern latitude survives the conversion.
    """
    sign = -1.0 if value < 0 else 1.0
    value = abs(value)
    degrees = int(value // 100)
    return sign * (degrees + (value - 100 * degrees) / 60.0)


class _TraceAccessor:
    """`f.trace[i]`, matching segyio's indexable trace accessor."""

    def __init__(self, owner):
        self._owner = owner

    def __getitem__(self, index: int):
        return self._owner._read_trace(index)

    def __len__(self):
        return self._owner.tracecount


class LittleEndianSegyFile:
    """
    A minimal little-endian SEG-Y reader shaped like a segyio handle.

    Only the surface `SEGYConverter.load` actually uses is implemented --
    deliberately. This is a compatibility shim for one vendor deviation, not
    a second SEG-Y library, and a wider surface would be a wider promise.
    """

    def __init__(self, path: str | Path, order: str = LITTLE):
        self.path = Path(path)
        self.order = order
        self._s = _STRUCT[order]
        self._fh = open(self.path, "rb")
        try:
            self._fh.seek(TEXTUAL_HEADER_BYTES)
            block = self._fh.read(BINARY_HEADER_BYTES)
            r = _reading(block, order)
            self.format = r["format"]
            if self.format in UNSUPPORTED_FORMATS:
                raise SegyFormatError(
                    f"{self.path.name}: SEG-Y data-sample format code {self.format} "
                    f"({UNSUPPORTED_FORMATS[self.format]}) is not supported by the little-endian "
                    f"reader. Supported codes: {sorted(SAMPLE_FORMATS)}."
                )
            if self.format not in SAMPLE_FORMATS:
                raise SegyFormatError(
                    f"{self.path.name}: SEG-Y data-sample format code {self.format} is not "
                    f"defined by the standard. Supported codes: {sorted(SAMPLE_FORMATS)}."
                )
            self._code, self._width = SAMPLE_FORMATS[self.format]
            self.n_samples = r["samples"]
            if self.n_samples <= 0:
                raise SegyEndianError(
                    f"{self.path.name}: binary header declares {self.n_samples} samples per trace"
                )
            self.interval = r["interval"]
            self._record = TRACE_HEADER_BYTES + self.n_samples * self._width
            body = self.path.stat().st_size - HEADER_BYTES
            self.tracecount = body // self._record
            if self.tracecount < 1:
                raise SegyEndianError(
                    f"{self.path.name}: header implies {self._record}-byte traces but only "
                    f"{body} bytes of data follow the header; the file is truncated"
                )
            if body % self._record:
                logger.warning(
                    f"{self.path.name}: {body % self._record} trailing byte(s) after "
                    f"{self.tracecount} complete traces; the remainder is ignored."
                )
            # Time axis. segyio computes `arange(ns) * dt/1000 + delrt *
            # abs(delay_scalar)`, and the /1000 is what makes this converter's
            # GPR files come out in nanoseconds -- these vendors write the
            # time fields pre-scaled by 1000 (i.e. in picoseconds).
            #
            # THE SAME SCALING MUST APPLY TO THE DELAY. It is one instrument
            # writing one unit into both time fields, and treating only `dt`
            # as pre-scaled produces a start time a thousand times too large:
            # on the 4TU corpus, delrt values of 293-10958 became a 293-10958
            # ns start against a ~50 ns recording window, which then propagated
            # into depths of hundreds of metres. Read in the same unit as `dt`
            # they are 0.3-11 ns -- an instrument time-zero/air-path offset,
            # which is what an air-launched antenna actually has.
            #
            # The axis origin stays "instrument time-zero", NOT the ground
            # surface, so any depth derived from it carries that offset. That
            # is recorded on the frame rather than silently removed here.
            header0 = self.header[0]
            delay_scalar = header0.get(TF_SCALAR_TRACE_HEADER, 0) or 0
            if delay_scalar == 0:
                delay_scalar = 1
            elif delay_scalar < 0:
                delay_scalar = 1.0 / delay_scalar
            raw_delay = header0.get(TF_DELAY, 0) or 0
            step = self.interval / 1000.0
            self.delay_raw = raw_delay
            self.t0 = (raw_delay * abs(delay_scalar)) / 1000.0
            self.samples = [self.t0 + i * step for i in range(self.n_samples)]
            window = step * self.n_samples
            if window > 0 and self.t0 > window:
                logger.warning(
                    f"{self.path.name}: start time {self.t0:g} exceeds the "
                    f"{window:g}-unit recording window (DelayRecordingTime={raw_delay}, "
                    f"scalar={delay_scalar}). The delay field is not being used as a delay "
                    f"in this file; the time axis is reported as read, not corrected."
                )
            self.bin = {
                BIN_INTERVAL: self.interval,
                BIN_SAMPLES: self.n_samples,
                BIN_FORMAT: self.format,
            }
            self.trace = _TraceAccessor(self)
        except Exception:
            self._fh.close()
            raise

    # --- segyio-shaped surface ---

    @property
    def header(self):
        return _HeaderAccessor(self)

    def _trace_offset(self, index: int) -> int:
        if not 0 <= index < self.tracecount:
            raise IndexError(
                f"trace {index} out of range for {self.path.name} "
                f"({self.tracecount} traces)"
            )
        return HEADER_BYTES + index * self._record

    def _read_trace_header(self, index: int) -> dict:
        self._fh.seek(self._trace_offset(index))
        raw = self._fh.read(TRACE_HEADER_BYTES)
        s = self._s
        i32 = lambda o: struct.unpack(s + "i", raw[o:o + 4])[0]      # noqa: E731
        i16 = lambda o: struct.unpack(s + "h", raw[o:o + 2])[0]      # noqa: E731
        return {
            TF_RECV_ELEVATION: i32(40),
            TF_SOURCE_SURFACE_ELEVATION: i32(44),
            TF_SCALAR_TRACE_HEADER: i16(68),
            TF_SCALAR: i16(70),
            TF_SOURCE_X: i32(72),
            TF_SOURCE_Y: i32(76),
            TF_GROUP_X: i32(80),
            TF_GROUP_Y: i32(84),
            TF_DELAY: i16(108),
            TF_SAMPLE_COUNT: i16(114),
            TF_SAMPLE_INTERVAL: i16(116),
        }

    def _read_trace(self, index: int) -> list[float]:
        self._fh.seek(self._trace_offset(index) + TRACE_HEADER_BYTES)
        raw = self._fh.read(self.n_samples * self._width)
        if len(raw) < self.n_samples * self._width:
            raise SegyEndianError(
                f"{self.path.name}: trace {index} is truncated "
                f"({len(raw)} of {self.n_samples * self._width} expected bytes)"
            )
        return list(struct.unpack(f"{self._s}{self.n_samples}{self._code}", raw))

    def close(self):
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _HeaderAccessor:
    """`f.header[i]`, returning a dict keyed by segyio's byte offsets."""

    def __init__(self, owner):
        self._owner = owner

    def __getitem__(self, index: int) -> dict:
        return self._owner._read_trace_header(index)

    def __len__(self):
        return self._owner.tracecount
