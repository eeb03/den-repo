"""
Component ablation for Candidate V2 (companion to scripts.bam_candidate_v2_experiment).

For each term of final_score, the term is removed (its weight set to zero), the
operating threshold is RE-FROZEN on the development scan (L-XZ recall >= 0.80)
and the frozen threshold is then applied to the test and control scans. The
hard filters and all other parameters stay at their frozen values. Same split,
same matching rule, no tuning on test scans.

    venv/bin/python -m scripts.bam_candidate_v2_components
"""
from __future__ import annotations

import json
from pathlib import Path

from benchmark import candidate_v2 as v2
from scripts.bam_candidate_v2_experiment import (CONTROL, DEV, TARGET_RECALL, TEST, VAL, Scan,
                                                 fp_at_recall, operating_threshold, pr_curve, r4,
                                                 score)

RESULTS = Path("artifacts/bam/candidate_v2/results.json")
OUT = Path("artifacts/bam/candidate_v2/component_ablation.json")


def rescored(props, drop):
    out = []
    for p in props:
        q = dict(p)
        if drop:
            q["final_score"] = p["final_score"] - v2.WEIGHTS[drop] * p[drop]
        out.append(q)
    return out


def main() -> int:
    val = json.loads(VAL.read_text())
    frozen = v2.V2Params(**json.loads(RESULTS.read_text())["frozen"]["params"])
    props = {}
    for spec, scan in [DEV, *TEST, *CONTROL]:
        sc = Scan(spec, scan, val)
        vol = sc.volume()
        props[(spec, scan)] = (sc, v2.propose(vol, sc.s.grid.x, sc.s.grid.y, sc.s.grid.z, frozen))
        del vol
        print("proposed", spec, scan, flush=True)
    res = {"protocol": __doc__, "variants": {}}
    for drop in [None, *v2.WEIGHTS]:
        name = f"without_{drop}" if drop else "full_score"
        sc, pr = props[DEV]
        dets = v2.select(rescored(pr, drop), frozen)
        op = operating_threshold(pr_curve(dets, sc, "final_score", n=200), TARGET_RECALL)
        row = {"dev_operating_threshold": op}
        for spec, scan in [*TEST, *CONTROL]:
            sc, pr = props[(spec, scan)]
            dets = v2.select(rescored(pr, drop), frozen)
            s = score(dets, sc, "final_score", op if op is not None else float("inf"))
            row[f"{spec}_{scan}"] = {
                **{k: s[k] for k in ("recall", "precision", "false_positives_per_line", "n_detections")},
                "fp_per_line_at_recall_0.8": (fp_at_recall(pr_curve(dets, sc, "final_score"), 0.8) or {}).get(
                    "false_positives_per_line"),
                "max_recall": max((c["recall"] or 0.0 for c in pr_curve(dets, sc, "final_score")), default=None),
            }
        res["variants"][name] = row
        print(name, json.dumps(r4(row)), flush=True)
    OUT.write_text(json.dumps(r4(res), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
