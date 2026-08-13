"""
Build the versioned ground-truth benchmark definition.

    python scripts/build_benchmark_definition.py --out artifacts/benchmark/definition.json

Reads the published truth sources, applies the checksum duplicate audit, counts
what independently survives, and computes what that population can resolve. It
scores no detector and reads no detector output: this describes the measuring
instrument, not a measurement.

The corpus is opened read-only and never modified. De-duplication happens in the
accounting.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark import definition as bench_def
from benchmark.bam_truth import load_control, load_targets
from benchmark.ground_truth import (
    apply_duplicate_audit, bam_units, fourtu_units, independent_negatives,
    independent_positives,
)
from benchmark.leakage import find_duplicates, retained_files
from benchmark.fourtu_truth import load_truth
from scripts.audit_benchmark_leakage import DEFAULT_CORPUS, build_manifest


def bootstrap_cross_check(n_positive: int, n_negative: int,
                          draws: int = 4000, seed: int = 20260813) -> dict:
    """
    Check the Hanley-McNeil approximation against a resampled chance corpus.

    A sample-size recommendation that says "collect more data" should not rest
    on an approximation nobody tested. This draws both groups from the SAME
    distribution -- so the true AUC is 0.5 by construction -- and reports how
    wide the observed interval is. If the analytic SE is honest, the bootstrap
    interval half-width should be close to 1.96 x SE.
    """
    import numpy as np

    if n_positive < 1 or n_negative < 1:
        return {"available": False, "reason": "a group is empty"}

    rng = np.random.default_rng(seed)

    def auc(a, b):
        return float(np.mean([[(x > y) + 0.5 * (x == y) for y in b] for x in a]))

    values = rng.lognormal(0.0, 1.0, size=n_positive + n_negative)
    observed = []
    for _ in range(draws):
        a = rng.choice(values, n_positive)
        b = rng.choice(values, n_negative)
        observed.append(auc(a, b))
    lo, hi = (float(v) for v in np.percentile(observed, [2.5, 97.5]))
    return {
        "available": True,
        "note": "both groups drawn from one distribution, so the true AUC is 0.5",
        "ci95_low": lo, "ci95_high": hi, "half_width": (hi - lo) / 2.0,
        "draws": draws, "seed": seed,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    p.add_argument("--out", type=Path, default=Path("artifacts/benchmark/definition.json"))
    p.add_argument("--skip-hashing", action="store_true",
                   help="build without the checksum audit; readiness will say so")
    args = p.parse_args()

    # --- 4TU: activities, with the duplicate audit applied -----------------
    truth = load_truth()
    units = fourtu_units(truth)

    audit_complete = False
    if not args.skip_hashing and args.corpus.exists():
        manifest = build_manifest(args.corpus)
        report = find_duplicates(manifest)
        kept = retained_files(manifest, report)
        owner = {unit: (unit if files else next(
            (o for o, f in kept.items() if f and o != unit), unit))
            for unit, files in kept.items()}
        units = apply_duplicate_audit(units, report, owner_of_unit=owner)
        audit_complete = True

    fourtu = bench_def.build(
        "4tu-nl-utility", units, duplicate_audit_complete=audit_complete,
        open_questions=bench_def.fourtu_open_questions())

    # --- BAM: the two specimens --------------------------------------------
    bam_defn = None
    try:
        from benchmark.bam_ingest import DEFAULT_ROOT, load_scan
        scan = load_scan("Pk266", "Pk266_3D_Dataset_1_5_GHz_Rot00", root=DEFAULT_ROOT)
        bam = bam_units(load_targets(scan.grid, "Pk266"), load_control("Pk050"))
        bam_defn = bench_def.build(
            "bam-concrete-gpr", bam, duplicate_audit_complete=True,
            open_questions=bench_def.bam_open_questions())
    except Exception as exc:  # noqa: BLE001 -- archive absent is a legitimate state
        bam_defn = None
        bam_reason = f"{type(exc).__name__}: {exc}"

    payload = {
        "generated_by": "scripts/build_benchmark_definition.py",
        "reads_detector_output": False,
        "corpus_unmodified": True,
        "benchmarks": {"4tu-nl-utility": fourtu.as_dict()},
        "bootstrap_cross_check": bootstrap_cross_check(
            len(independent_positives(units)), len(independent_negatives(units))),
    }
    if bam_defn is not None:
        payload["benchmarks"]["bam-concrete-gpr"] = bam_defn.as_dict()
    else:
        payload["benchmarks"]["bam-concrete-gpr"] = {
            "unavailable": True, "reason": bam_reason}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")

    for name, block in payload["benchmarks"].items():
        if block.get("unavailable"):
            print(f"{name}: unavailable ({block['reason'][:60]})")
            continue
        counts, power = block["counts"], block["power"]
        print(f"{name}  version={block['version']}")
        print(f"  units={counts['units']}  by label={counts['by_label']}")
        print(f"  duplicate status={counts['by_duplicate_status']}")
        print(f"  independent: {counts['independent_positives']} positive, "
              f"{counts['independent_negatives']} negative")
        if power:
            print(f"  smallest detectable AUC={power['smallest_detectable_auc']}")
            print(f"  negatives required={power['negatives_required']}")
        for d in block["readiness"]:
            print(f"    {d['readiness']:8} {d['name']}")
    print(f"  -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
