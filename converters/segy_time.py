"""
The SEG-Y time axis, built one way for both byte orders.

THE FIELDS.
- Sample interval: binary-header bytes 3217-3218 (trace-header 117-118 as the
  fallback). The standard unit is microseconds; Subterra's GPR files write
  picoseconds there, which is why the interval is divided by 1000 and a GPR
  axis is labelled ns. segyio applies the same /1000 and labels the result ms.
- Recording delay: trace-header bytes 109-110, a signed 16-bit integer. The
  standard unit is milliseconds -- 1000 times the interval's unit -- so it is
  NOT divided by 1000; under the GPR shift that makes it nanoseconds.
- Time scalar: trace-header bytes 215-216, applied to the delay. 0 means 1,
  a positive value multiplies, a negative one divides by its magnitude. The
  standard permits only +-1, 10, 100, 1000, 10000; anything else is refused.
  NOT bytes 69-70: that is the ELEVATION scalar, which the little-endian reader
  used to borrow for time.

THE DIALECT THE BYTES CANNOT REVEAL. Some producers (the MATGPR export behind
the ADS Falerii Novi SEG-Y) write the delay in the SAME unit as the interval.
With a scalar of 0, a delay of 20 is 20 ns under the standard and 0.02 ns
under that convention, and both are plausible, so it is a caller declaration
(`delay_encoding`), never inferred -- the same contract as
`converters.segy_converter.COORDINATE_ENCODINGS`.
"""
from __future__ import annotations

DELAY_ENCODINGS = {
    "segy_standard": (
        "SEG-Y rev 1: DelayRecordingTime (bytes 109-110) is in the standard's delay unit "
        "(ms; ns under the GPR time shift), scaled by the time scalar at bytes 215-216"
    ),
    "sample_interval_unit": (
        "vendor deviation: DelayRecordingTime is written in the same unit as the sample "
        "interval, so after the bytes 215-216 time scalar it is divided by 1000 exactly as "
        "the interval is"
    ),
}

DEFAULT_DELAY_ENCODING = "segy_standard"

#: SEG-Y rev 1 bytes 215-216 permit these magnitudes (0 is read as 1).
STANDARD_TIME_SCALARS = frozenset({0, 1, 10, 100, 1000, 10000})


def validate_delay_encoding(value: str) -> None:
    """The single check for a known `delay_encoding`; raises ValueError."""
    if value not in DELAY_ENCODINGS:
        raise ValueError(
            f"unknown delay_encoding {value!r}; supported: {sorted(DELAY_ENCODINGS)}")


def start_time_from_header(delay_raw: int, time_scalar_raw: int, delay_encoding: str) -> float:
    """
    The first sample's time, in the unit of the converter's sample axis (the
    interval's raw value / 1000).

    Division is exact rather than multiplying by a reciprocal, so a 4TU delay
    of 2641 with scalar -1000 is exactly 2641 / 1000, as it always was.
    """
    validate_delay_encoding(delay_encoding)
    scalar = int(time_scalar_raw)
    if abs(scalar) not in STANDARD_TIME_SCALARS:
        raise ValueError(
            f"time scalar {scalar} at trace-header bytes 215-216 is not one SEG-Y permits "
            f"(0, +-1, 10, 100, 1000, 10000); refused rather than applied to "
            f"DelayRecordingTime={delay_raw}")
    delay = int(delay_raw)
    if scalar > 0:
        t0 = float(delay * scalar)
    elif scalar < 0:
        t0 = delay / abs(scalar)
    else:
        t0 = float(delay)
    if delay_encoding == "sample_interval_unit":
        t0 = t0 / 1000.0
    return t0


def sample_axis(n_samples: int, step: float, t0: float) -> list[float]:
    """`t0 + i * step`, the construction segyio uses, so a zero-delay axis is
    bit-identical to segyio's."""
    return [t0 + i * step for i in range(n_samples)]


def describe(delay_raw: int, time_scalar_raw: int, delay_encoding: str,
             interval_raw, t0: float, unit: str) -> str:
    """How the first sample's time was built, for the frame's provenance."""
    return (
        f"DelayRecordingTime (trace-header bytes 109-110) = {delay_raw}, time scalar "
        f"(bytes 215-216) = {time_scalar_raw}, sample interval (bytes 3217-3218) = "
        f"{interval_raw}, read as {delay_encoding!r}: {DELAY_ENCODINGS[delay_encoding]}. "
        f"First sample at {t0:g} {unit}."
    )
