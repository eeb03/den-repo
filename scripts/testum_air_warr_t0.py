"""
An independently measured time-zero, from TestUM's published air-WARR files.

RESULT: INCONCLUSIVE. THIS IS NOT A SUCCESSFUL CALIBRATION.

Over the complete corpus, 25 of 26 files analysed, TWO passed the slope check
below. The failures are not marginal -- observed slopes span -5.99 to +17.33
ns/m against an expected 3.336 -- which means the first-arrival picker in this
module is finding baseline turning points rather than arrivals on most files.

The two that pass are recorded as observations and NOT adopted as TestUM's t0:
20231205_t0_end recovers the air slope to 0.2% and gives 22.13 ns, and
20230824_t0_end to 4.6% giving 21.01 ns. They DISAGREE BY 1.12 ns, three months
apart. A calibration irreproducible on 23 of 25 files, whose two survivors
differ by more than a nanosecond, is not a measurement. A reproducible
inconclusive experiment is worth more than an unsupported number.

WHY THIS ONE IS NOT CIRCULAR, where stages 24-25 were. Every previous attempt
had to estimate t0 and velocity together from reflectors whose depth was the
thing being tested. Here the propagation medium is AIR, whose velocity is a
physical constant nobody fits, and the transmitter-receiver separation is set by
the operator and written into the dataset's own metadata. So:

    t_measured(X) = t0 + X / c_air

has exactly one unknown. The subsurface never enters it.

THE SLOPE IS A PREDICTION, AND THAT IS THE POINT. Fitting the line gives both an
intercept and a slope, and the slope is already known: 1/c_air = 3.336 ns/m. If
the recovered slope matches, the geometry, the units, the trace ordering and the
picking have all been read correctly, and the intercept means what it claims. If
it does not match, the intercept is not a time-zero and this script says so
rather than reporting it anyway. Nothing else in this project has had an
independent check of that kind available.

WHAT IS PICKED, AND WHOSE RULE IT IS. The authors state: "Maximum of first
arrivals are picked (in the borehole measurements also maxima are picked, as
they are determined more reliable in low signal-to-noise ratio)". This follows
that -- the maximum of the first arriving wavelet, not an onset, and not the
global maximum of the trace.

AND IT IS THE PART THAT DOES NOT WORK YET. The traces carry a large, smoothly
varying baseline that drifts by thousands of counts across the wavelet, so
amplitude thresholding picks the baseline and simple turning-point detection
picks its inflections. That is the whole reason for the inconclusive verdict.

A BUG IN THIS MODULE, RECORDED BECAUSE IT COST THE FIRST RESULT. The initial
picker returned nothing at all on every file. Samples 0-1 carry a marker value
(-469762048 was observed) rather than signal; included in the noise estimate they
made the threshold enormous, so no sample ever cleared it. The GSSI converter
already documents exactly this as `leading_samples_may_be_markers = 2`, and this
module now skips the same two samples (MARKER_SAMPLES). After the fix one file
gave 8 of 11 observations at t0 = 20.25-20.69 ns -- t - X/c_air constant across
separations, as the model predicts -- which is what suggests the approach is
sound and the PICKING is what is inadequate.

WHAT THIS SCRIPT REFUSES TO DO. It does not touch the subsurface traces. It does
not compute a velocity. It writes no declaration and no platform state. And it
does not transfer anything to 4TU: a t0 measured on a Tubewave-100 borehole
antenna pair says nothing about a 500 MHz air-launched array, and the number
produced here is TestUM's alone.

    python -m scripts.testum_air_warr_t0 --out artifacts/testum/air_warr_t0.json
"""
from __future__ import annotations

import argparse
import json
import math
import re
import struct
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

#: Electromagnetic propagation in air, m/ns. A physical constant. It is NOT
#: fitted, NOT a subsurface velocity, and is the reason this measurement is
#: independent of anything below the ground.
C_AIR = 0.299_792_458

RAW_DIR = Path("datasets/raw/pangaea/971978/raw")
METADATA = Path("datasets/raw/pangaea/971978/PANGAEA_971978_metadata.txt")


@dataclass(frozen=True)
class Calibration:
    """One air-WARR file: several separations, one t0."""
    file_name: str
    date: str
    slot: str
    protocol: str
    x_start_m: float
    x_end_m: float
    dx_m: float
    n_traces_published: int
    n_traces_in_file: int
    n_observations_used: int
    n_observations_rejected: int
    separations_m: tuple[float, ...]
    picked_times_ns: tuple[float, ...]
    #: Per-observation t0 = t_picked - X/c_air. Independent of the subsurface.
    t0_per_observation_ns: tuple[float, ...]
    t0_at_x3_ns: float | None
    fitted_t0_ns: float
    fitted_slope_ns_per_m: float
    expected_slope_ns_per_m: float
    slope_error_pct: float
    r_squared: float
    residual_rms_ns: float
    geometry_confirmed: bool


def parse_protocol(comment: str) -> tuple[float, float, float] | None:
    """`x_receiver_start=1m, x_receiver_end=3m, dx=0.2m` -> (1.0, 3.0, 0.2)."""
    m = re.search(r"x_receiver_start=([\d.]+)m.*?x_receiver_end=([\d.]+)m.*?dx=([\d.]+)m",
                  comment)
    return (float(m.group(1)), float(m.group(2)), float(m.group(3))) if m else None


def read_dzt(path: Path) -> tuple[list[list[float]], float]:
    """
    Traces and sample interval, decoded from the file itself.

    Deliberately independent of Subterra's converter: this is evidence about the
    dataset, and using the platform's own reader to produce it would make the
    platform its own referee.
    """
    raw = path.read_bytes()
    u16 = lambda o: struct.unpack_from("<H", raw, o)[0]          # noqa: E731
    f32 = lambda o: struct.unpack_from("<f", raw, o)[0]          # noqa: E731
    nsamp, bits, rng = u16(4), u16(6), f32(26)
    width = bits // 8
    header = u16(2) * 1024
    body = len(raw) - header
    n_traces = body // (nsamp * width)
    fmt = {2: "<h", 4: "<i"}[width]

    traces = []
    for t in range(n_traces):
        base = header + t * nsamp * width
        traces.append([float(struct.unpack_from(fmt, raw, base + s * width)[0])
                       for s in range(nsamp)])
    return traces, rng / nsamp


#: Samples 0-1 carry a marker value (e.g. -469762048), not signal. The GSSI
#: converter documents the same thing as `leading_samples_may_be_markers`.
#: Including them destroys any noise estimate, which is what made the first
#: version of this picker return nothing at all.
MARKER_SAMPLES = 2


def pick_first_arrival(trace: list[float], dt_ns: float) -> float | None:
    """
    Time of the MAXIMUM of the first arriving wavelet, per the authors' rule.

    "Maximum of first arrivals are picked" -- so this finds the first turning
    point of the trace, not the global maximum, which a later and stronger event
    would otherwise capture.

    The traces carry a large, smoothly varying baseline, so a fixed threshold on
    absolute amplitude picks the baseline rather than an arrival. The first
    arrival is instead located as the first LOCAL EXTREMUM whose prominence
    clears the local noise -- the point where the wavelet turns over.
    """
    n = len(trace)
    body = trace[MARKER_SAMPLES:]
    if len(body) < 20:
        return None

    # Noise from the quiet interval before any arrival is physically possible:
    # even X = 3 m in air is ~10 ns, i.e. ~68 samples at 0.146 ns.
    quiet = body[:20]
    mean = sum(quiet) / len(quiet)
    noise = math.sqrt(sum((v - mean) ** 2 for v in quiet) / len(quiet)) or 1.0

    for i in range(2, len(body) - 2):
        rising = body[i] - body[i - 1]
        falling = body[i + 1] - body[i]
        turning = (rising > 0 >= falling) or (rising < 0 <= falling)
        if turning and abs(body[i] - mean) > 5.0 * noise:
            return (i + MARKER_SAMPLES) * dt_ns
    return None


def analyse(path: Path, date: str, slot: str, comment: str,
            n_published: int) -> Calibration | None:
    protocol = parse_protocol(comment)
    if protocol is None:
        return None
    x0, x1, dx = protocol
    traces, dt = read_dzt(path)

    separations, times = [], []
    for k, trace in enumerate(traces):
        x = x0 + k * dx
        if x > x1 + 1e-9:
            break
        t = pick_first_arrival(trace, dt)
        if t is not None:
            separations.append(x)
            times.append(t)

    if len(separations) < 3:
        return None

    # ROBUSTNESS, NOT TUNING. A minority of traces pick a wrong turning point;
    # the model says t - X/c_air is CONSTANT, so an observation far from the
    # median of that quantity is a mis-pick and is dropped by a stated rule
    # rather than by eye. Every rejection is counted and reported.
    raw_t0 = [t - x / C_AIR for x, t in zip(separations, times)]
    med = sorted(raw_t0)[len(raw_t0) // 2]
    dev = sorted(abs(v - med) for v in raw_t0)
    mad = dev[len(dev) // 2] or 0.05
    keep = [i for i, v in enumerate(raw_t0) if abs(v - med) <= max(5.0 * mad, 0.5)]
    n_rejected = len(raw_t0) - len(keep)
    if len(keep) < 3:
        return None
    separations = [separations[i] for i in keep]
    times = [times[i] for i in keep]

    n = len(separations)
    mx = sum(separations) / n
    mt = sum(times) / n
    sxx = sum((x - mx) ** 2 for x in separations)
    sxy = sum((x - mx) * (t - mt) for x, t in zip(separations, times))
    slope = sxy / sxx
    intercept = mt - slope * mx

    predicted = [intercept + slope * x for x in separations]
    ss_res = sum((t - p) ** 2 for t, p in zip(times, predicted))
    ss_tot = sum((t - mt) ** 2 for t in times)
    rms = math.sqrt(ss_res / n)

    expected = 1.0 / C_AIR
    slope_err = abs(slope - expected) / expected * 100.0

    t0_each = [t - x / C_AIR for x, t in zip(separations, times)]
    t0_x3 = next((t0 for x, t0 in zip(separations, t0_each) if abs(x - 3.0) < 1e-6), None)

    return Calibration(
        file_name=path.name, date=date, slot=slot, protocol=comment,
        x_start_m=x0, x_end_m=x1, dx_m=dx,
        n_traces_published=n_published, n_traces_in_file=len(traces),
        n_observations_used=n, n_observations_rejected=n_rejected,
        separations_m=tuple(separations), picked_times_ns=tuple(round(t, 4) for t in times),
        t0_per_observation_ns=tuple(round(v, 4) for v in t0_each),
        t0_at_x3_ns=round(t0_x3, 4) if t0_x3 is not None else None,
        fitted_t0_ns=round(intercept, 4), fitted_slope_ns_per_m=round(slope, 5),
        expected_slope_ns_per_m=round(expected, 5), slope_error_pct=round(slope_err, 3),
        r_squared=round(1 - ss_res / ss_tot, 6) if ss_tot else 0.0,
        residual_rms_ns=round(rms, 4),
        #: The interpretation is only confirmed if the recovered slope is the
        #: air slope. 5% is generous against a 3.336 ns/m expectation.
        geometry_confirmed=slope_err < 5.0,
    )


def load_index() -> list[tuple[str, str, str, str, int]]:
    out = []
    for line in METADATA.read_text(errors="replace").splitlines():
        f = line.rstrip("\n").split("\t")
        if len(f) > 15 and "_t0_" in f[1]:
            slot = re.search(r"_t0_(\w+)\.", f[1])
            out.append((f[1], f[0], slot.group(1) if slot else "", f[15], int(f[9] or 0)))
    return out


def build(raw_dir: Path) -> dict:
    results = []
    missing = []
    for name, date, slot, comment, n_pub in load_index():
        path = raw_dir / name
        if not path.exists() or path.stat().st_size < 20_000:
            missing.append(name)
            continue
        r = analyse(path, date, slot, comment, n_pub)
        if r:
            results.append(r)

    confirmed = [r for r in results if r.geometry_confirmed]
    t0s = [r.fitted_t0_ns for r in confirmed]
    x3s = [r.t0_at_x3_ns for r in confirmed if r.t0_at_x3_ns is not None]

    def stats(values):
        if not values:
            return None
        n = len(values)
        m = sum(values) / n
        sd = math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
        return {"n": n, "mean_ns": round(m, 4), "sd_ns": round(sd, 4),
                "min_ns": round(min(values), 4), "max_ns": round(max(values), 4),
                "range_ns": round(max(values) - min(values), 4),
                "sem_ns": round(sd / math.sqrt(n), 4) if n > 1 else None}

    by_date: dict[str, list[float]] = {}
    for r in confirmed:
        by_date.setdefault(r.date, []).append(r.fitted_t0_ns)
    within_day = [max(v) - min(v) for v in by_date.values() if len(v) > 1]

    return {
        "experiment": "testum-air-warr-t0",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "model": "t_measured(X) = t0 + X / c_air",
        "c_air_m_per_ns": C_AIR,
        "independence": ("the propagation medium is air, whose velocity is a physical "
                         "constant; no subsurface reflector, depth or velocity enters"),
        "files_expected": len(load_index()),
        "files_analysed": len(results),
        "files_missing": missing,
        "geometry_confirmed_count": len(confirmed),
        "fitted_t0": stats(t0s),
        "t0_at_x3m_authors_rule": stats(x3s),
        "day_to_day": {
            "n_days": len(by_date),
            "per_day_mean_ns": {d: round(sum(v) / len(v), 4) for d, v in sorted(by_date.items())},
            "max_within_day_spread_ns": round(max(within_day), 4) if within_day else None,
        },
        "slope_check": stats([r.fitted_slope_ns_per_m for r in results]),
        "expected_slope_ns_per_m": round(1.0 / C_AIR, 5),
        "calibrations": [asdict(r) for r in results],
        "transferred_to_4tu": False,
        "declarations_written": [],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    res = build(args.raw_dir)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(res, indent=2))

    print(f"files: {res['files_analysed']}/{res['files_expected']} analysed, "
          f"{res['geometry_confirmed_count']} geometry-confirmed")
    sl = res["slope_check"]
    if sl:
        print(f"slope: {sl['mean_ns']} ns/m  (expected {res['expected_slope_ns_per_m']}, "
              f"air) sd={sl['sd_ns']}")
    for key in ("fitted_t0", "t0_at_x3m_authors_rule"):
        s = res[key]
        if s:
            print(f"{key}: n={s['n']} mean={s['mean_ns']} ns  sd={s['sd_ns']}  "
                  f"range={s['range_ns']} ns")
    d = res["day_to_day"]
    print(f"days: {d['n_days']}  max within-day spread: {d['max_within_day_spread_ns']} ns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
