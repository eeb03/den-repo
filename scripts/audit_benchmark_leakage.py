"""
Audit the 4TU corpus for duplicate evaluation units, and rescore without them.

    python scripts/audit_benchmark_leakage.py --out artifacts/4tu/leakage.json

The 4TU score treats an ACTIVITY as the evaluation unit and compares candidate
density between activities whose trench found utilities and activities whose
trench was attested empty. That comparison assumes activities are independent
measurements. This checks whether they are, by hashing every radargram in the
corpus and asking which activities are built from the same bytes.

It then recomputes the score with each measurement counted exactly once, and
reports both numbers. The corpus is never modified: the archive is read-only
here, and de-duplication happens in the accounting, not on disk.

WHY THE BOOTSTRAP IS HERE TOO. The published AUC rests on seven negatives. A
point estimate from seven samples carries an interval wide enough to change
what the number means, and reporting the point estimate alone -- in either
direction -- claims a precision the corpus does not have.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np

from benchmark.fourtu_scoring import ActivityObservation, score_activities
from benchmark.fourtu_truth import load_truth, normalise_location_id
from benchmark.leakage import find_duplicates, retained_files

DEFAULT_CORPUS = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted")
DEFAULT_CHARACTERISATION = Path("artifacts/4tu/characterisation.json")
#: Directory component that names the activity, e.g. .../011/011/011.16/Radargrams/x.sgy
ACTIVITY_DIR = re.compile(r"/(\d+\.\d+)/")
BOOTSTRAP_SEED = 20260813
BOOTSTRAP_DRAWS = 4000


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build_manifest(corpus: Path) -> dict[str, dict[str, str]]:
    """activity -> {filename: checksum}, from the files on disk."""
    manifest: dict[str, dict[str, str]] = {}
    for path in sorted(corpus.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".sgy", ".segy"}:
            continue
        match = ACTIVITY_DIR.search(str(path))
        if not match:
            continue
        activity = normalise_location_id(match.group(1))
        manifest.setdefault(activity, {})[path.name] = sha256(path)
    return manifest


def observations_from(characterisation: dict,
                      keep: dict[str, tuple[str, ...]] | None) -> dict[str, ActivityObservation]:
    """
    Per-activity counts, optionally restricted to a retained set of files.

    `keep=None` reproduces the published observation exactly. Restricting sums
    only the per-file entries, so an activity whose files are all owned
    elsewhere yields zero traces and drops out of the comparison rather than
    appearing as an activity with no candidates -- which would be a different
    and false claim.
    """
    out: dict[str, ActivityObservation] = {}
    activities = characterisation["activities"]
    entries = activities.values() if isinstance(activities, dict) else activities
    for entry in entries:
        loc = normalise_location_id(entry["location_id"])
        if keep is None:
            candidates, traces = int(entry["candidates"]), int(entry["traces"])
        else:
            allowed = set(keep.get(loc, ()))
            files = [f for f in entry.get("files", []) if f["file"] in allowed]
            candidates = sum(int(f["candidates"] or 0) for f in files)
            traces = sum(int(f["traces"] or 0) for f in files)
        if keep is not None and not traces:
            continue
        out[loc] = ActivityObservation(location_id=loc, candidates=candidates, traces=traces)
    return out


def densities(truth, observations) -> tuple[np.ndarray, np.ndarray]:
    def group(activities):
        values = []
        for a in activities:
            o = observations.get(normalise_location_id(a.location_id))
            if o is not None and o.per_1k_traces is not None:
                values.append(o.per_1k_traces)
        return np.array(values, dtype=float)
    return group(truth.positives), group(truth.attested_zeros)


def auc(a: np.ndarray, b: np.ndarray) -> float | None:
    if not len(a) or not len(b):
        return None
    return float(np.mean([[(x > y) + 0.5 * (x == y) for y in b] for x in a]))


def auc_interval(a: np.ndarray, b: np.ndarray) -> dict:
    """Percentile bootstrap over both groups, resampled independently."""
    point = auc(a, b)
    if point is None:
        return {"auc": None, "note": "one group is empty"}
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = np.array([
        auc(rng.choice(a, len(a)), rng.choice(b, len(b))) for _ in range(BOOTSTRAP_DRAWS)
    ])
    lo, hi = (float(v) for v in np.percentile(draws, [2.5, 97.5]))
    return {
        "auc": point, "n_positive": int(len(a)), "n_negative": int(len(b)),
        "ci95_low": lo, "ci95_high": hi, "ci95_width": hi - lo,
        "contains_chance": bool(lo <= 0.5 <= hi),
        "method": "percentile bootstrap, groups resampled independently",
        "draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    p.add_argument("--characterisation", type=Path, default=DEFAULT_CHARACTERISATION)
    p.add_argument("--out", type=Path, default=Path("artifacts/4tu/leakage.json"))
    args = p.parse_args()

    manifest = build_manifest(args.corpus)
    report = find_duplicates(manifest)
    keep = retained_files(manifest, report)
    characterisation = json.loads(args.characterisation.read_text())
    truth = load_truth()

    published = observations_from(characterisation, None)
    deduped = observations_from(characterisation, keep)

    pub_a, pub_b = densities(truth, published)
    ded_a, ded_b = densities(truth, deduped)

    negatives_touched = sorted(
        {u.unit_id for u in report.affected_units}
        & {normalise_location_id(a.location_id) for a in truth.attested_zeros}
    )

    payload = {
        "benchmark": "4tu-nl-utility",
        "corpus": str(args.corpus),
        "unit": "activity (LocationID)",
        "leakage": report.as_dict(),
        "negatives_sharing_data_with_another_activity": negatives_touched,
        "why_that_matters": (
            "the separation AUC rests on seven negatives; an activity that shares "
            "measurements with a positive is not an independent negative"
        ),
        "published": {
            "n_activities_scored": len(published),
            "separation": auc_interval(pub_a, pub_b),
            "score": score_activities(truth, published).as_dict(),
        },
        "deduplicated": {
            "n_activities_scored": len(deduped),
            "activities_dropped": sorted(set(published) - set(deduped)),
            "separation": auc_interval(ded_a, ded_b),
            "score": score_activities(truth, deduped).as_dict(),
        },
        "corpus_unmodified": True,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"files={report.n_files} unique={report.n_unique_checksums} "
          f"cross-unit duplicate groups={len(report.cross_unit_groups)}")
    for u in report.affected_units:
        print(f"  {u.unit_id}: {u.n_shared}/{u.n_files} shared with {', '.join(u.shares_with)}"
              f"{'  [FULLY DUPLICATED]' if u.fully_duplicated else ''}")
    print(f"  negatives affected: {negatives_touched or 'none'}")
    for label, block in (("published", payload["published"]), ("deduplicated", payload["deduplicated"])):
        sep = block["separation"]
        print(f"  {label}: activities={block['n_activities_scored']} auc={sep.get('auc')} "
              f"ci95=[{sep.get('ci95_low')}, {sep.get('ci95_high')}] "
              f"contains_chance={sep.get('contains_chance')}")
    print(f"  -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
