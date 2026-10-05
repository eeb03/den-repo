"""
Does Volume V1's migration FOCUS the known BAM objects? A reconstruction
evaluation, not a detector evaluation.

    python -m scripts.bam_volume_focusing --out evidence/bam/results/volume_v1_focusing.json

For each scan whose back-wall calibration is scientifically sufficient, the
product path is run end to end in a temporary data root: register the grid,
declare the known-geometry calibration and the antenna offset through
`api.spatial` (exactly what a user does in the UI), build two volumes --
migration none and Stolt F-K 3D, everything else identical -- and measure the
response_envelope around each drawn object.

THE DRAWINGS ARE USED ONLY HERE, TO EVALUATE. The reconstruction never sees
them (tests/test_volume.py::test_reconstruction_never_reads_ground_truth). The
calibration uses the back wall only (drawn objects only EXCLUDED from its
windows -- the existing rule).

METRICS (per object; ducts per central-band line, cuboids once in 3D):
  peak offset      envelope peak position minus the drawn position:
                   dx (longitudinal), dy (transverse; cuboids only -- a duct
                   runs along y), dz against the drawn TOP
  lateral FWHM     width of the envelope through the peak along x (and y for
                   cuboids) -- the apparent spatial spread (PSF-like)
  depth FWHM       width along z through the peak
  concentration    share of envelope energy in a search window that lies
                   within the drawn object (dilated by 20 mm)
Fixed before any result was computed: search window +/-150 mm laterally,
z from top - 60 mm to top + 150 mm; central band y in [0.15, 0.65] m; FWHM at
half the peak on the contiguous run through the peak.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import numpy as np

BAND = (0.15, 0.65)
WIN_LAT, Z_ABOVE, Z_BELOW, DILATE = 0.150, 0.060, 0.150, 0.020
SCANS = [("Pk266", "1_5_GHz_Rot00"), ("Pk266", "2_6_GHz_Rot00"), ("Pk266", "1_5_GHz_Rot90"),
         ("Pk266", "2_6_GHz_Rot90"), ("Pk401", "1_5_GHz_Rot00"), ("Pk401", "1_5_GHz_Rot90")]


class _DB:
    def add(self, _x):
        pass

    def commit(self):
        pass


def fwhm(profile: np.ndarray, i: int, step: float) -> float:
    half = profile[i] / 2.0
    lo = i
    while lo > 0 and profile[lo - 1] >= half:
        lo -= 1
    hi = i
    while hi < profile.size - 1 and profile[hi + 1] >= half:
        hi += 1
    return (hi - lo + 1) * step


def idx(ax, v):
    return int(np.clip(round((v - ax["origin"]) / ax["step"]), 0, ax["n"] - 1))


def setup(specimen, scan, root):
    import api.spatial as sp
    from database.grid_store import load_grids
    from ingestion.bam_grid import register_bam_scan
    from schemas.spatial_reference import DeclarationKind as K
    from scripts.register_bam_volume_dataset import calibration_lines

    src = Path("datasets/raw/bam_concrete").resolve()
    ds = register_bam_scan(_DB(), None, specimen, scan, root=src)
    fid = load_grids(ds)[0].frame_id
    lines = calibration_lines(specimen, scan, src)
    if not lines:
        return ds, None
    pts = []
    for ln in lines:
        d, t, srcname, ev, rid = [x.strip() for x in ln.split(",")]
        pts.append({"depth_m": float(d), "time_ns": float(t), "depth_source": srcname,
                    "depth_evidence": ev, "reflector_id": rid})
    try:
        v = sp.validate_declaration(K.DEPTH_CALIBRATION, {"points": pts, "pick_convention": "peak",
                                                          "pick_precision_ns": 0.1})
    except Exception as exc:  # noqa: BLE001 -- a refused calibration is a result
        return ds, f"calibration refused: {exc}"
    sp.apply_declaration(ds, K.DEPTH_CALIBRATION, v, "BAM drawings", frame_id=fid, declaration_id="cal")
    v = sp.validate_declaration(K.ANTENNA_OFFSET, {"offset_m": 0.0, "measured_from": "depth_axis_origin",
                                                   "evidence": "acquisition_documentation",
                                                   "supplied_by": "BAM: ground-coupled antenna on the surface"})
    sp.apply_declaration(ds, K.ANTENNA_OFFSET, v, "BAM", frame_id=fid, declaration_id="off")
    return ds, v


def duct_metrics(env, ax, obj):
    xs, ys, zs = (ax[k]["origin"] + np.arange(ax[k]["n"]) * ax[k]["step"] for k in "xyz")
    xd, zt, zc, r = obj["x_m"], obj["z_top_m"], obj["z_centre_m"], obj["radius_m"]
    i0, i1 = idx(ax["x"], xd - WIN_LAT), idx(ax["x"], xd + WIN_LAT) + 1
    k0, k1 = idx(ax["z"], zt - Z_ABOVE), idx(ax["z"], zt + Z_BELOW) + 1
    rows = []
    for j in range(idx(ax["y"], BAND[0]), idx(ax["y"], BAND[1]) + 1):
        w = np.nan_to_num(env[i0:i1, j, k0:k1])
        a, c = np.unravel_index(np.argmax(w), w.shape)
        i, k = i0 + a, k0 + c
        e2 = w ** 2
        inside = ((np.abs(xs[i0:i1] - xd) <= r + DILATE)[:, None]
                  & ((zs[k0:k1] >= zt - DILATE) & (zs[k0:k1] <= zc + r + DILATE))[None, :])
        rows.append({"dx_mm": (xs[i] - xd) * 1000, "dz_top_mm": (zs[k] - zt) * 1000,
                     "fwhm_x_mm": fwhm(env[:, j, k], i, ax["x"]["step"]) * 1000,
                     "fwhm_z_mm": fwhm(env[i, j, :], k, ax["z"]["step"]) * 1000,
                     "concentration": float(e2[inside].sum() / max(e2.sum(), 1e-12))})
    keys = rows[0].keys()
    return {k: {"median": round(float(np.median([r[k] for r in rows])), 3),
                "p25": round(float(np.percentile([r[k] for r in rows], 25)), 3),
                "p75": round(float(np.percentile([r[k] for r in rows], 75)), 3)} for k in keys} | {"n_lines": len(rows)}


def box_metrics(env, ax, obj):
    xs, ys, zs = (ax[k]["origin"] + np.arange(ax[k]["n"]) * ax[k]["step"] for k in "xyz")
    xc = sum(obj["x_range_m"]) / 2
    yc = sum(obj["y_range_m"]) / 2
    zt = obj["z_range_m"][0]
    i0, i1 = idx(ax["x"], xc - WIN_LAT), idx(ax["x"], xc + WIN_LAT) + 1
    j0, j1 = idx(ax["y"], yc - WIN_LAT), idx(ax["y"], yc + WIN_LAT) + 1
    k0, k1 = idx(ax["z"], zt - Z_ABOVE), idx(ax["z"], zt + Z_BELOW) + 1
    w = np.nan_to_num(env[i0:i1, j0:j1, k0:k1])
    a, b, c = np.unravel_index(np.argmax(w), w.shape)
    i, j, k = i0 + a, j0 + b, k0 + c
    e2 = w ** 2
    inx = (xs[i0:i1] >= obj["x_range_m"][0] - DILATE) & (xs[i0:i1] <= obj["x_range_m"][1] + DILATE)
    iny = (ys[j0:j1] >= obj["y_range_m"][0] - DILATE) & (ys[j0:j1] <= obj["y_range_m"][1] + DILATE)
    inz = (zs[k0:k1] >= obj["z_range_m"][0] - DILATE) & (zs[k0:k1] <= obj["z_range_m"][1] + DILATE)
    inside = inx[:, None, None] & iny[None, :, None] & inz[None, None, :]
    return {"dx_mm": round((xs[i] - xc) * 1000, 1), "dy_mm": round((ys[j] - yc) * 1000, 1),
            "dz_top_mm": round((zs[k] - zt) * 1000, 1),
            "fwhm_x_mm": round(fwhm(env[:, j, k], i, ax["x"]["step"]) * 1000, 1),
            "fwhm_y_mm": round(fwhm(env[i, :, k], j, ax["y"]["step"]) * 1000, 1),
            "fwhm_z_mm": round(fwhm(env[i, j, :], k, ax["z"]["step"]) * 1000, 1),
            "concentration": round(float(e2[inside].sum() / max(e2.sum(), 1e-12)), 3)}


def run_scan(specimen, scan):
    import api.volumes as svc
    from configs.settings import settings
    from reconstruction.volume import build
    from schemas.volume import VolumeConfig

    with tempfile.TemporaryDirectory() as tmp:
        old = settings.data_root
        settings.data_root = Path(tmp)
        try:
            for s in ("raw", "processed", "metadata"):
                (Path(tmp) / s).mkdir()
            ds, cal = setup(specimen, scan, Path(tmp))
            if cal is None or isinstance(cal, str):
                return {"specimen": specimen, "scan": scan, "status": "no sufficient calibration",
                        "detail": cal}
            out = {"specimen": specimen, "scan": scan, "status": "ok", "volumes": {}}
            gt_objs = None
            for mig in ("none", "stolt_fk_3d"):
                t0 = time.perf_counter()
                prod, arrays = build(ds, VolumeConfig(migration=mig))
                env = arrays["response_envelope.npy"]
                ax = {k: getattr(prod, f"{k}_axis").model_dump() for k in "xyz"}
                if gt_objs is None:
                    gt_objs = svc.ground_truth(prod, {"benchmark": {"benchmark_id": "bam-concrete-gpr",
                                                                    "specimen_id": specimen}})["objects"]
                    out["calibration"] = {k: prod.calibration_provenance["velocity"][k] for k in ("value_m_per_ns", "basis")} | {
                        "t0_ns": prod.calibration_provenance["time_zero"]["correction_ns"]}
                objs = {}
                for o in gt_objs:
                    if o["kind"] == "duct":
                        objs[o["id"]] = duct_metrics(env, ax, o)
                    elif o["kind"] == "box":
                        objs[o["id"]] = box_metrics(env, ax, o)
                out["volumes"][mig] = {"objects": objs, "performance": prod.performance,
                                       "shape": list(prod.shape), "build_s": round(time.perf_counter() - t0, 2)}
                del arrays, env
            return out
        finally:
            settings.data_root = old


def summarise(res):
    """Per object: is the migrated response more concentrated / better located?"""
    rows = []
    for r in res:
        if r.get("status") != "ok":
            continue
        a, b = r["volumes"]["none"]["objects"], r["volumes"]["stolt_fk_3d"]["objects"]
        for oid in a:
            get = (lambda d, k: d[k]["median"] if isinstance(d[k], dict) else d[k])
            row = {"scan": f"{r['specimen']} {r['scan']}", "object": oid}
            for k in ("fwhm_x_mm", "fwhm_z_mm", "concentration", "dx_mm", "dz_top_mm"):
                row[k] = (get(a[oid], k), get(b[oid], k))
            if "fwhm_y_mm" in a[oid]:
                row["fwhm_y_mm"] = (a[oid]["fwhm_y_mm"], b[oid]["fwhm_y_mm"])
                row["dy_mm"] = (a[oid]["dy_mm"], b[oid]["dy_mm"])
            rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    res = []
    for spec, scan in SCANS:
        t = time.time()
        r = run_scan(spec, scan)
        res.append(r)
        print(spec, scan, r.get("status"), f"{time.time() - t:.0f}s", flush=True)
    out = {"method": __doc__, "results": res, "summary": summarise(res)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, default=float))
    for row in out["summary"]:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
