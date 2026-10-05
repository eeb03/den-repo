"""
Yesan: test competing explanations of the 2.8% distance-scale discrepancy.

    python -m scripts.yesan_scale_hypotheses [--json OUT]

DATA-FREE AND REPRODUCIBLE. Every input is a number already recorded, with its
source, in docs/yesan-registration-investigation.md (sections 2 and 4) and
benchmark/manifests/yesan-fullscale.targets.json, read there from the six
`.rad` headers and the authors' `summary of GPR data and formula.xlsx`. No raw
file is needed to re-run it, and nothing here reads a target, a detector or a
radargram.

THE QUESTION. The header interval is DISTANCE INTERVAL = 0.008429 m
(= 3 pulses / WHEEL CALIBRATION 355.9 pulses/m). The authors' sheet uses
dx = 0.0086649550706 m. Ratio 1.02796. Why?

Each hypothesis is stated, its expected effect computed, compared with the
observed ratio, and given a verdict: ACCEPT, REJECT or UNRESOLVED.
"""
from __future__ import annotations

import argparse
import json
import math
from fractions import Fraction

HEADER_INTERVAL_M = 0.008429          # .rad DISTANCE INTERVAL (6 decimals as printed)
HEADER_WHEEL_CAL = 355.9              # .rad WHEEL CALIBRATION, pulses per metre
PULSES_PER_TRACE = 3                  # 0.008429 = 3 / 355.9 (doc section 4)
SHEET_DX_M = 0.0086649550706          # authors' sheet, 11 significant digits
SHEET_DX_REL_PRECISION = 0.5e-13 / SHEET_DX_M   # half a unit in the last printed digit
ANTENNA_SEPARATION_M = 0.18           # .rad ANTENNA SEPARATION
STACKS = 1                            # .rad STACKS
#: file -> (traces, authors' 0 m trace), doc section 2 table
FILES = {"DAT_0066": (10801, 65), "DAT_0068": (10627, 80), "DAT_0069": (10760, 107),
         "DAT_0071": (10578, 60), "DAT_0072": (10767, 96), "DAT_0074": (10674, 60)}
#: Steepest plausible grade along a bridge-transition pavement test road. A design
#: limit for expressways is a few percent; 10% is a deliberately generous bound.
MAX_PLAUSIBLE_GRADE = 0.10
#: Largest map-projection point scale error near Yesan (126.8 E) in Korea's TM
#: belts / UTM 52N is well under 0.1%; a generous bound.
MAX_PROJECTION_SCALE_ERROR = 0.001


def observed_ratio() -> float:
    return SHEET_DX_M / HEADER_INTERVAL_M


def rational_calibration(max_metres: int = 100) -> dict:
    """
    Is the authors' effective wheel calibration 3/dx a whole number of pulses over a
    whole number of metres? If so, dx came from counting over a measured distance,
    not from a fit. Also the chance of such a match for an arbitrary value.
    """
    cal = PULSES_PER_TRACE / SHEET_DX_M
    frac = Fraction(cal).limit_denominator(1000)
    rel_err = abs(cal - float(frac)) / cal
    candidates = []
    for metres in range(1, max_metres + 1):
        pulses = cal * metres
        if abs(pulses - round(pulses)) / pulses < 1e-9:
            candidates.append({"metres": metres, "pulses": int(round(pulses)),
                               "traces": round(pulses) / PULSES_PER_TRACE})
    # Look-elsewhere-corrected chance: an arbitrary calibration in a 20 pulses/m
    # window lands, within the sheet's PRINTED precision, on SOME fraction whose
    # denominator is no larger than the one found. (Counting every fraction of
    # denominator <= q in the window, each with a +/- tolerance interval.)
    tol_abs = max(rel_err, SHEET_DX_REL_PRECISION) * cal
    q = frac.denominator
    n_fractions = sum(20 * sum(1 for k in range(1, d + 1) if math.gcd(k, d) == 1) / d * d
                      for d in range(1, q + 1))
    p_chance = n_fractions * 2 * tol_abs
    return {"effective_calibration_pulses_per_m": cal,
            "as_fraction": f"{frac.numerator}/{frac.denominator}",
            "relative_error_of_fraction": rel_err,
            "dx_as_fraction_m": str(Fraction(SHEET_DX_M).limit_denominator(10000)),
            "whole_metre_whole_pulse_candidates": candidates[:6],
            "chance_probability_upper_bound": p_chance}


def hypotheses() -> list[dict]:
    r = observed_ratio()
    excess = r - 1
    out = []

    def add(hid, statement, expected, verdict, reasoning):
        out.append({"id": hid, "hypothesis": statement, "expected_effect": expected,
                    "observed": f"ratio {r:.6f} (+{excess * 100:.3f}%), sheet longer",
                    "verdict": verdict, "reasoning": reasoning})

    printed_err = 0.5e-6 / HEADER_INTERVAL_M
    true_header = PULSES_PER_TRACE / HEADER_WHEEL_CAL
    add("H1-header-rounding",
        "The header interval is a rounded print of the true spacing.",
        f"at most +/-{printed_err * 100:.4f}% (6 printed decimals); 3/355.9 = {true_header:.8f}",
        "REJECT", f"{printed_err * 100:.4f}% << {excess * 100:.3f}%")

    rc = rational_calibration()
    add("H2-field-recalibration",
        "The authors replaced the wheel calibration with one counted over a measured distance.",
        "3/dx is a ratio of whole pulses to whole metres, to the sheet's printed precision",
        "ACCEPT (mechanism); UNRESOLVED (which distance)",
        f"3/dx = {rc['effective_calibration_pulses_per_m']:.10f} = {rc['as_fraction']} pulses/m "
        f"(relative error {rc['relative_error_of_fraction']:.1e}); smallest whole-metre run "
        f"{rc['whole_metre_whole_pulse_candidates'][0]}; chance of such a match "
        f"<= {rc['chance_probability_upper_bound']:.1e}. Equivalently dx = "
        f"{rc['dx_as_fraction_m']} m: 3116 traces over 27 m. The 90 m section also fits "
        f"(31160 pulses), so the run length is not identified.")

    add("H3-constant-offset",
        "A start/end or antenna offset (0.18 m separation, 0 m trace 60-107) explains it.",
        f"an additive shift (<= {ANTENNA_SEPARATION_M} m or <= 0.93 m), independent of length",
        "REJECT", "the authors' formula is distance = (trace - zero_trace) x dx: the factor is "
                  "multiplicative by construction, and an additive term cannot produce it")

    grade = math.sqrt(r ** 2 - 1)
    add("H4-slope-distance",
        "One scale is slope distance, the other horizontal.",
        f"needs a grade of {grade * 100:.1f}% ({math.degrees(math.atan(grade)):.1f} deg), and "
        f"the wheel (along the surface) would read LONGER than horizontal",
        "REJECT", f"grade > {MAX_PLAUSIBLE_GRADE * 100:.0f}% is implausible on a pavement "
                  f"test road, and the sign is wrong: the sheet is the longer one")

    add("H5-projection-scale",
        "A map-projection scale factor separates the two.",
        f"<= {MAX_PROJECTION_SCALE_ERROR * 100:.1f}%; and wheel distances are never projected",
        "REJECT", "no coordinates exist in any file; magnitude 30x too small")

    add("H6-resampling-cropping-stacking",
        "Traces were resampled, stacked or cropped.",
        f"STACKS={STACKS}; cropping changes the trace count, not the spacing",
        "REJECT", "trace counts in the sheet equal the .rad LAST TRACE for all six files")

    add("H7-direction-reversal",
        "One profile was reversed.", "a reversal maps x -> L - x; it preserves scale",
        "REJECT", "cannot change a spacing (it matters for the origin, not the scale)")

    add("H8-parser-error",
        "Subterra mis-reads the interval.",
        "converters/mala_converter.py reads DISTANCE INTERVAL verbatim",
        "REJECT", f"3/{HEADER_WHEEL_CAL} = {true_header:.7f} reproduces the header independently")

    add("H9-figure-scaling",
        "The published figures carry their own axis scale.",
        "figure apexes would match neither convention",
        "REJECT (as a third scale)", "doc section 6: three apexes match the sheet convention "
                                     "within 0.02 m, so the figures use dx")

    add("H10-which-is-physical",
        "The sheet scale is the physically correct one.",
        "requires the measured reference distance to be independent and correct",
        "UNRESOLVED", "H2 shows dx was counted over a whole-metre distance, which favours it "
                      "over a preset wheel constant, but the distance and its measurement are "
                      "undocumented")
    return out


def line_lengths() -> dict:
    return {f: {"header_m_from_0m_trace": round((n - z) * HEADER_INTERVAL_M, 3),
                "sheet_m_from_0m_trace": round((n - z) * SHEET_DX_M, 3),
                "difference_m": round((n - z) * (SHEET_DX_M - HEADER_INTERVAL_M), 3)}
            for f, (n, z) in FILES.items()}


def report() -> dict:
    return {"observed_ratio": observed_ratio(), "rational_calibration": rational_calibration(),
            "hypotheses": hypotheses(), "line_lengths": line_lengths()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--json", help="write the full report as JSON")
    args = ap.parse_args(argv)
    rep = report()
    print(f"observed ratio sheet/header = {rep['observed_ratio']:.6f}")
    rc = rep["rational_calibration"]
    print(f"3/dx = {rc['effective_calibration_pulses_per_m']:.10f} = {rc['as_fraction']} "
          f"pulses/m; dx = {rc['dx_as_fraction_m']} m; chance <= "
          f"{rc['chance_probability_upper_bound']:.1e}")
    for h in rep["hypotheses"]:
        print(f"  {h['id']:<34} {h['verdict']}")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(rep, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
