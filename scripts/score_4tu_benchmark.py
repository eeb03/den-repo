"""
Score the detector against 4TU trial-trench truth, at activity level.

Reads the per-activity candidate counts the corpus characterisation already
produced (`artifacts/4tu/characterisation.json`) rather than reprocessing
235 million records, and joins them to `Metadata.csv` by LocationID -- which
is the only join the source supports.

    python scripts/score_4tu_benchmark.py --out artifacts/4tu/benchmark.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark import gates
from benchmark.fourtu_scoring import ActivityObservation, score_activities
from benchmark.fourtu_truth import DEFAULT_METADATA, load_truth, normalise_location_id


def load_observations(path: Path) -> dict[str, ActivityObservation]:
    """
    Per-activity candidate counts from the corpus characterisation.

    Keys go through the SAME normalisation the truth loader uses. The two
    sources spell project 13 differently -- the characterisation follows
    `Metadata.csv` (`13.N`), the directories say `013.N` -- and normalising only
    one side silently drops six activities from the join.
    """
    data = json.loads(path.read_text())
    activities = data["activities"]
    entries = activities.values() if isinstance(activities, dict) else activities
    out = {}
    for a in entries:
        loc = normalise_location_id(a["location_id"])
        out[loc] = ActivityObservation(
            location_id=loc,
            candidates=int(a["candidates"]),
            traces=int(a["traces"]),
        )
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--characterisation", type=Path,
                   default=Path("artifacts/4tu/characterisation.json"))
    p.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    p.add_argument("--out", type=Path, default=Path("artifacts/4tu/benchmark.json"))
    args = p.parse_args()

    truth = load_truth(args.metadata)
    obs = load_observations(args.characterisation)

    # A partial join must never pass as a full one.
    missing = sorted(set(truth.activities) - set(obs))
    extra = sorted(set(obs) - set(truth.activities))
    if missing or extra:
        print(f"WARNING: join is incomplete -- {len(missing)} activities in the "
              f"truth with no observation {missing[:6]}, {len(extra)} observations "
              f"with no truth {extra[:6]}")

    score = score_activities(truth, obs)

    report = {
        "benchmark": "4tu-nl-utility",
        "resolution": "activity (LocationID)",
        "scope": gates.FOURTU_SCOPE_STATEMENT,
        "object_level_status": gates.OBJECT_LEVEL_STATUS,
        "object_level_blocked_reason": gates.OBJECT_LEVEL_BLOCKED_REASON,
        "activity_level_status": gates.ACTIVITY_LEVEL_STATUS,
        "open_questions": [q.id for q in gates.FOURTU_OPEN_QUESTIONS],
        "truth_activities": len(truth.activities),
        "truth_positive": len(truth.positives),
        "truth_attested_zero": len(truth.attested_zeros),
        "truth_unrecorded": len(truth.unrecorded),
        "observations": len(obs),
        "join_complete": not (missing or extra),
        "truth_without_observation": missing,
        "observation_without_truth": extra,
        "score": score.as_dict(),
        "source_notes": list(truth.notes),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1))

    s = score
    print(f"activities: truth={len(truth.activities)} observed={len(obs)} "
          f"scored={s.n_activities_scored}")
    print(f"  positive={s.n_positive}  attested-zero={s.n_attested_zero}  "
          f"unrecorded={s.n_unrecorded}")
    print(f"  candidate density per 1k traces:")
    print(f"    utility-bearing : median {s.positive_group.median_per_1k}  "
          f"n={s.positive_group.n_activities}")
    print(f"    trench-empty    : median {s.attested_zero_group.median_per_1k}  "
          f"n={s.attested_zero_group.n_activities}")
    print(f"  separation AUC   : {s.density_separation['auc']}")
    print(f"  count agreement  : spearman rho={s.count_agreement['spearman_rho']} "
          f"(n={s.count_agreement['n_pairs']})")
    print(f"  unexplained response rate: {s.unexplained_response_rate} "
          f"({s.unexplained_response_basis})")
    print(f"  object-level: {gates.OBJECT_LEVEL_STATUS} "
          f"({gates.OBJECT_LEVEL_BLOCKED_REASON})")
    print(f"  -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
