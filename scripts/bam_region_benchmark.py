"""
CONTROLLED BENCHMARK EVALUATION of Interpretation V1 response regions on BAM.
Not a pristine held-out test: BAM has been studied extensively in this
repository (Candidate V2, Volume V1, calibration). Rot90 in particular is
not untouched.

    python -m scripts.bam_region_benchmark --phase dev  --out artifacts/bam/interp/dev.json
    python -m scripts.bam_region_benchmark --phase eval --out evidence/bam/results/interpretation_v1_benchmark.json

PROTOCOL (committed with the matching rule, benchmark/region_matching.py,
before any target-level region result was computed):
  * region proposals never see a target: they run on the volume arrays only
  * DEVELOPMENT subset: Pk266 1.5 GHz Rot00 (ducts) + Pk050 1.5 GHz Rot00 (no
    targets). If any parameter needs changing it is changed on these only,
    then frozen in FROZEN below and committed before --phase eval.
  * EVALUATION: every other depth-scoreable scan (calibration sufficient):
    Pk266 2.6 Rot00, Pk266 1.5 / 2.6 Rot90, Pk401 1.5 Rot00 / Rot90,
    Pk050 1.5 Rot90. 2.6 GHz Pk401 / Pk050 have no sufficient calibration:
    time-domain volumes, counted but not depth-scored.
  * outputs compared (where meaningful): A production ring z-score
    (z >= 3), B envelope E1 (T >= 10), C Candidate V2 calibrated (frozen
    25352a9: final_score >= 0.65) -- all from the cached detections of the
    Candidate V2 experiment, depth-converted with the same scan's back-wall
    calibration -- and D response regions. Candidate V2 code and labels are
    NOT used; only its stored detections, for comparison.
  * region variants (ablations): migration off; local contrast off; support
    filtering off; min size 1 / 200; 26-connectivity; closing on; lobe
    merging off; and a sparse-line volume (every second line removed,
    linear_bounded gridding) for the interpolation handling.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import pickle
import tempfile
import time
from pathlib import Path

import numpy as np

from benchmark.region_matching import Output, score, targets_from_csv

DEV = [("Pk266", "1_5_GHz_Rot00"), ("Pk050", "1_5_GHz_Rot00")]
EVAL = [("Pk266", "2_6_GHz_Rot00"), ("Pk266", "1_5_GHz_Rot90"), ("Pk266", "2_6_GHz_Rot90"),
        ("Pk401", "1_5_GHz_Rot00"), ("Pk401", "1_5_GHz_Rot90"), ("Pk050", "1_5_GHz_Rot90"),
        ("Pk401", "2_6_GHz_Rot00"), ("Pk050", "2_6_GHz_Rot00")]
FROZEN: dict = {}          # RegionConfig overrides; empty = the committed defaults
VARIANTS = {
    "frozen": {},
    "no_local_contrast": {"use_local_contrast": False},
    "no_support_filtering": {"min_supported_fraction": 0.0, "refuse_interpolation_only": False},
    "min_voxels_1": {"min_voxels": 1},
    "min_voxels_200": {"min_voxels": 200},
    "connectivity_26": {"connectivity": 26},
    "closing_on": {"closing": True},
    "no_lobe_merging": {"merge_stacked_lobes": False},
}
CACHE = Path("artifacts/bam/interp")
V2CAL_CACHE = Path("artifacts/bam/v2cal")


class _DB:
    def add(self, _x):
        pass

    def commit(self):
        pass


def volumes_for(spec, scan, sparse=False):
    """Build (or load cached) none + stolt volumes through the product path. Returns dict."""
    from configs.settings import settings
    from scripts.bam_volume_focusing import setup
    from reconstruction.volume import build
    from schemas.volume import VolumeConfig

    tag = f"{spec}_{scan}" + ("_sparse" if sparse else "")
    out = {}
    CACHE.mkdir(parents=True, exist_ok=True)
    metas = sorted(CACHE.glob(f"{tag}__*.json"))
    if metas:
        for m in metas:
            mig = m.stem.split("__")[1]
            d = np.load(m.with_suffix(".npz"))
            out[mig] = ({k: d[k] for k in d.files}, json.loads(m.read_text()))
        return out
    tmp = tempfile.mkdtemp()
    old = settings.data_root
    settings.data_root = Path(tmp)
    try:
        for s in ("raw", "processed", "metadata"):
            (Path(tmp) / s).mkdir()
        ds, cal = setup(spec, scan, Path(tmp))
        depth = cal is not None and not isinstance(cal, str)
        if sparse:
            _make_sparse(ds)
        configs = {"none": VolumeConfig(migration="none", interpolation="linear_bounded" if sparse else "nearest_no_fill")}
        if depth and not sparse:
            configs["stolt_fk_3d"] = VolumeConfig(migration="stolt_fk_3d")
        for mig, cfg in configs.items():
            p, a = build(ds, cfg)
            arrays = {"env": a["response_envelope.npy"], "sup": a["support_class.npy"], "dist": a["nearest_distance.npy"]}
            np.savez(CACHE / f"{tag}__{mig}.npz", **arrays)
            meta = p.model_dump(mode="json")
            (CACHE / f"{tag}__{mig}.json").write_text(json.dumps(meta))
            out[mig] = (arrays, meta)
    finally:
        settings.data_root = old
    return out


def _make_sparse(ds):
    from database.grid_store import load_grids, open_array, save_grid
    g = load_grids(ds)[0]
    arr = np.array(open_array(g))
    missing = list(range(1, g.line_axis.n, 2))
    arr[:, missing, :] = 0
    save_grid(g.model_copy(update={"missing_lines": missing}), arr)


def regions_for(arrays, meta, overrides):
    from interpretation.volume_regions import propose
    from schemas.region import RegionConfig
    ax = {k: (meta[f"{k}_axis"]["origin"], meta[f"{k}_axis"]["step"]) for k in "xyz"}
    t = time.perf_counter()
    r = propose(arrays["env"], arrays["sup"], arrays["dist"], ax, RegionConfig(**{**FROZEN, **overrides}),
                z_unit=meta["z_axis"]["unit"], z_domain=meta["z_domain"])
    r["seconds"] = round(time.perf_counter() - t, 2)
    return r


def region_outputs(regs):
    return [Output(id=g.id, score=g.evidence_score, peak=(g.peak_location.x, g.peak_location.y, g.peak_location.z),
                   z_range=(g.bounds.z_min, g.bounds.z_max), centroid=(g.centroid.x, g.centroid.y, g.centroid.z),
                   extent=(g.physical_extent.x, g.physical_extent.y, g.physical_extent.z),
                   fwhm=(g.fwhm.x, g.fwhm.y, g.fwhm.z)) for g in regs]


def baseline_outputs(sid, meta):
    """Cached 2D detections of the Candidate V2 experiment, at their frozen operating points."""
    t0 = meta["calibration_provenance"]["time_zero"]["correction_ns"]
    v = meta["calibration_provenance"]["velocity"]["value_m_per_ns"]
    dep = lambda t: v * (t - t0) / 2.0          # noqa: E731
    out = {}
    for arm, key, op in (("A_production", "z", 3.0), ("B_envelope", "z", 10.0), ("C_v2_prev", "final_score", 0.768)):
        name = {"A_production": "production", "B_envelope": "envelope", "C_v2_prev": "v2_prev"}[arm]
        p = V2CAL_CACHE / f"{name}__{sid}.json"
        if not p.exists():
            continue
        dets = [d for d in json.loads(p.read_text()) if d[key] >= op]
        out[arm] = [Output(id=f"{arm}-{n}", score=float(d[key]), peak=(d["x"] / 1000.0, d["y"] / 1000.0, dep(d["t_ns"])),
                           z_range=(dep(d["t_ns"]), dep(d["t_ns"]))) for n, d in enumerate(dets)]
    out.update(_v2cal_outputs(sid, dep))
    return out


def _v2cal_outputs(sid, dep):
    """Candidate V2 calibrated (research-only), its FROZEN operating point, from cached proposals."""
    hits = glob.glob(str(V2CAL_CACHE / f"props__line_W41_h2.5_*__{sid}.pkl"))
    if not hits:
        return {}
    import importlib.util
    import subprocess
    src = subprocess.run(["git", "show", "origin/research/candidate-v2-calibrated:benchmark/candidate_v2_calibrated.py"],
                         capture_output=True, text=True).stdout
    if not src:
        return {}
    tmp = Path(tempfile.mkdtemp()) / "v2cal_module.py"
    tmp.write_text(src.replace("from benchmark.candidate_v2 import", "from v2prev_module import"))
    prev = subprocess.run(["git", "show", "origin/research/candidate-v2-calibrated:benchmark/candidate_v2.py"],
                          capture_output=True, text=True).stdout
    (tmp.parent / "v2prev_module.py").write_text(prev)
    import sys
    sys.path.insert(0, str(tmp.parent))
    spec = importlib.util.spec_from_file_location("v2cal_module", tmp)
    m = importlib.util.module_from_spec(spec)
    sys.modules["v2cal_module"] = m
    spec.loader.exec_module(m)
    res = pickle.loads(Path(hits[0]).read_bytes())
    dets = [d for d in m.select(res, m.V2CalParams(normalisation="line", background_window_traces=41, horizon_ratio=2.5,
                                                   proposal_threshold=4.0, min_lateral_extent_mm=15.0))
            if d["final_score"] >= 0.65]
    return {"C_v2_calibrated": [Output(id=f"v2cal-{n}", score=d["final_score"],
                                       peak=(d["x"] / 1000.0, d["y"] / 1000.0, dep(d["t_ns"])),
                                       z_range=(dep(d["t_ns"]), dep(d["t_ns"]))) for n, d in enumerate(dets)]}


def run_scan(spec, scan, gt_rows, with_baselines=True, variants=VARIANTS):
    sid = f"{spec}_3D_Dataset_{scan}"
    targets, structures = targets_from_csv(gt_rows, spec)
    vols = volumes_for(spec, scan)
    res = {"specimen": spec, "scan": scan, "targets": len(targets), "volumes": {}}
    for mig, (arrays, meta) in vols.items():
        depth = meta["z_domain"] == "depth"
        vres = {"z_domain": meta["z_domain"], "variants": {}}
        for vname, ov in variants.items():
            if mig == "none" and vname != "frozen":
                continue
            r = regions_for(arrays, meta, ov)
            entry = {"n_regions": len(r["regions"]), "rejected": r["rejected"], "merges": len(r["merges"]),
                     "seconds": r["seconds"],
                     "low_support": sum(g.status.value == "low_support" for g in r["regions"])}
            if depth and targets is not None:
                entry["score"] = score(region_outputs(r["regions"]), targets, structures)
            vres["variants"][vname] = entry
            if vname == "frozen":
                vres["regions"] = [{k: v for k, v in g.model_dump(mode="json").items() if k != "mask_b64"}
                                   for g in r["regions"]]
        res["volumes"][mig] = vres
    if with_baselines and "stolt_fk_3d" in vols:
        meta = vols["stolt_fk_3d"][1]
        res["baselines"] = {arm: {"n_outputs": len(outs), "score": score(outs, targets, structures)}
                            for arm, outs in baseline_outputs(sid, meta).items()}
    return res


def sparse_experiment(gt_rows):
    """Pk266 1.5 Rot00 with every second line removed: interpolation handling."""
    spec, scan = "Pk266", "1_5_GHz_Rot00"
    targets, structures = targets_from_csv(gt_rows, spec)
    arrays, meta = volumes_for(spec, scan, sparse=True)["none"]
    out = {}
    for vname, ov in (("frozen", {}), ("no_support_filtering", {"min_supported_fraction": 0.0,
                                                                "refuse_interpolation_only": False})):
        r = regions_for(arrays, meta, ov)
        regs = r["regions"]
        out[vname] = {"n_regions": len(regs), "rejected": r["rejected"],
                      "low_support": sum(g.status.value == "low_support" for g in regs),
                      "median_interpolated_fraction": float(np.median([g.support.interpolated_voxel_fraction for g in regs])) if regs else None,
                      "score": score(region_outputs(regs), targets, structures)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["dev", "eval"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    gt_rows = list(csv.DictReader(open("evidence/bam/specimen_ground_truth.csv", encoding="utf-8")))
    scans = DEV if args.phase == "dev" else EVAL
    out = {"phase": args.phase, "protocol": __doc__, "frozen_overrides": FROZEN, "scans": []}
    for spec, scan in scans:
        t = time.time()
        r = run_scan(spec, scan, gt_rows)
        out["scans"].append(r)
        print(spec, scan, f"{time.time() - t:.0f}s", flush=True)
    if args.phase == "eval":
        out["sparse_line_experiment"] = sparse_experiment(gt_rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
