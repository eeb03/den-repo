"""
Volume service: preview, build, read slices / voxels / a display-only 3D
texture, and the optional BAM ground-truth overlay.

Binary payloads travel as base64 little-endian arrays inside JSON (float32
with NaN preserved for empty voxels, uint8 for support). One slice of a BAM
volume is ~0.3 MB; the 3D texture is bounded by `max_dim` and labelled
DISPLAY-ONLY. The scientific volume never leaves the server whole.
"""
from __future__ import annotations

import base64
import csv
import re
from pathlib import Path
from typing import Optional

import numpy as np

from database.volumes_store import list_volumes, load_volume, open_array, save_volume
from reconstruction.volume import VolumeRefused, build, preview, staleness
from schemas.volume import SUPPORT_CLASS_MEANING, SupportClass, VolumeConfig, VolumeProduct, ZDomain

GROUND_TRUTH_CSV = Path("evidence/bam/specimen_ground_truth.csv")
GROUND_TRUTH_LABEL = "GROUND TRUTH — NOT INPUT TO RECONSTRUCTION"
ORIENTATIONS = ("xy", "xz", "yz")
FIELDS = ("radar_response", "response_envelope")


class VolumeNotFound(LookupError):
    pass


def _b64(a: np.ndarray, dtype) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype=np.dtype(dtype).newbyteorder("<")).tobytes()).decode()


def product_payload(p: VolumeProduct) -> dict:
    return {**p.model_dump(mode="json"), "staleness": staleness(p),
            "support_class_meaning": {c.name: SUPPORT_CLASS_MEANING[c] for c in SupportClass},
            "support_class_values": {c.name: int(c) for c in SupportClass}}


def get(dataset_id: str, volume_id: str) -> VolumeProduct:
    p = load_volume(dataset_id, volume_id)
    if p is None:
        raise VolumeNotFound(volume_id)
    return p


def do_preview(dataset_id: str, config: VolumeConfig) -> dict:
    return preview(dataset_id, config)


def create(dataset_id: str, config: VolumeConfig, created_by: Optional[str]) -> dict:
    product, arrays = build(dataset_id, config, created_by)
    save_volume(product, arrays)
    return product_payload(product)


def listing(dataset_id: str) -> list[dict]:
    out = []
    for p in list_volumes(dataset_id):
        out.append({"id": p.id, "created_at": p.created_at.isoformat(), "z_domain": p.z_domain.value,
                    "reconstruction_method": p.reconstruction_method, "shape": list(p.shape),
                    "coordinate_frame": p.coordinate_frame.kind.value, "staleness": staleness(p)})
    return out


def slice_(p: VolumeProduct, orientation: str, index: int, field: str = "radar_response",
           thickness: int = 1) -> dict:
    """
    One orthogonal slice. xy: fixed k (z); xz: fixed j (y); yz: fixed i (x).
    Values are returned row-major as (rows, cols) with rows = the vertical
    display axis: xy rows = y, cols = x; xz rows = z, cols = x; yz rows = z,
    cols = y. A thickness > 1 averages a centred slab (support = the weakest
    class in the slab), and says so.
    """
    if orientation not in ORIENTATIONS:
        raise ValueError(f"orientation must be one of {ORIENTATIONS}")
    if field not in FIELDS:
        raise ValueError(f"field must be one of {FIELDS}")
    nx, ny, nz = p.shape
    n = {"xy": nz, "xz": ny, "yz": nx}[orientation]
    if not 0 <= index < n:
        raise ValueError(f"index {index} outside 0..{n - 1}")
    thickness = max(1, min(int(thickness), 31))
    lo, hi = max(0, index - thickness // 2), min(n, index + thickness // 2 + 1)
    fpath = next(f.file for f in p.fields if f.property_name == field)
    arr = open_array(p, fpath)
    sup = open_array(p, p.support_file)
    dist = open_array(p, p.distance_file)
    cnt = open_array(p, p.count_file)
    if orientation == "xy":
        v = np.nanmean(np.asarray(arr[:, :, lo:hi]), axis=2).T if hi - lo > 1 else np.asarray(arr[:, :, index]).T
        s = np.asarray(sup[:, :, lo:hi]).min(axis=2).T
        d, c = np.asarray(dist).T, np.asarray(cnt).T
        axes = {"rows": "y", "cols": "x"}
    elif orientation == "xz":
        v = np.nanmean(np.asarray(arr[:, lo:hi, :]), axis=1).T if hi - lo > 1 else np.asarray(arr[:, index, :]).T
        s = np.asarray(sup[:, lo:hi, :]).min(axis=1).T
        d = np.broadcast_to(np.asarray(dist[:, index]), (nz, nx))
        c = np.broadcast_to(np.asarray(cnt[:, index]), (nz, nx))
        axes = {"rows": "z", "cols": "x"}
    else:
        v = np.nanmean(np.asarray(arr[lo:hi, :, :]), axis=0).T if hi - lo > 1 else np.asarray(arr[index, :, :]).T
        s = np.asarray(sup[lo:hi, :, :]).min(axis=0).T
        d = np.broadcast_to(np.asarray(dist[index, :]), (nz, ny))
        c = np.broadcast_to(np.asarray(cnt[index, :]), (nz, ny))
        axes = {"rows": "z", "cols": "y"}
    rows, cols = v.shape
    return {"volume_id": p.id, "orientation": orientation, "index": index, "field": field,
            "thickness_voxels": hi - lo, "slab": [lo, hi - 1], "rows": rows, "cols": cols, "axes": axes,
            "values_f32_b64": _b64(v, np.float32), "support_u8_b64": _b64(s, np.uint8),
            "max_distance_m": float(np.nanmax(d)) if np.isfinite(d).any() else None,
            "min_support_count": int(np.min(c)),
            "stats": next(f.stats for f in p.fields if f.property_name == field),
            "note": ("averaged over a centred slab of %d voxels" % (hi - lo)) if hi - lo > 1 else None}


def voxel(p: VolumeProduct, i: int, j: int, k: int) -> dict:
    nx, ny, nz = p.shape
    if not (0 <= i < nx and 0 <= j < ny and 0 <= k < nz):
        raise ValueError(f"voxel ({i}, {j}, {k}) outside the volume {p.shape}")
    vals = {}
    for f in p.fields:
        x = float(open_array(p, f.file)[i, j, k])
        vals[f.property_name] = None if not np.isfinite(x) else x
    cls = SupportClass(int(open_array(p, p.support_file)[i, j, k]))
    dist = float(open_array(p, p.distance_file)[i, j])
    return {
        "i": i, "j": j, "k": k,
        "x_m": p.x_axis.origin + i * p.x_axis.step, "y_m": p.y_axis.origin + j * p.y_axis.step,
        "z": p.z_axis.origin + k * p.z_axis.step, "z_unit": p.z_axis.unit, "z_domain": p.z_domain.value,
        "z_meaning": p.coordinate_frame.z_meaning, "values": vals,
        "support_class": cls.name, "support_meaning": SUPPORT_CLASS_MEANING[cls],
        "support_count": int(open_array(p, p.count_file)[i, j]),
        "support_count_meaning": "measured traces within one native spacing of this voxel's (x, y) column",
        "nearest_measurement_distance_m": None if not np.isfinite(dist) else dist,
        "interpolation_distance_m": (None if not np.isfinite(dist) or cls is not SupportClass.INTERPOLATED else dist),
        "reconstruction_method": p.reconstruction_method,
        "migration": p.migration.model_dump(mode="json"),
        "depth_calibration": {k: p.calibration_provenance.get(k) for k in
                              ("z_domain", "velocity", "time_zero", "calibration",
                               "depth_calibration_declaration_id", "used_for_depth")},
        "source_frames": p.frame_ids, "coordinate_frame": p.coordinate_frame.kind.value,
        "validation_status": p.validation_status,
    }


def render3d(p: VolumeProduct, field: str = "response_envelope", max_dim: int = 160) -> dict:
    """
    A DISPLAY-ONLY downsampled texture: block-max of |field| per block,
    scaled to 0-255 by the field's 99.9th percentile. The scientific volume is
    unchanged; the original shape and the block factors are returned.
    """
    if field not in FIELDS:
        raise ValueError(f"field must be one of {FIELDS}")
    max_dim = int(min(max(32, max_dim), 256))
    arr = open_array(p, next(f.file for f in p.fields if f.property_name == field))
    sup = open_array(p, p.support_file)
    f = [int(np.ceil(n / max_dim)) for n in p.shape]
    out_shape = [int(np.ceil(n / s)) for n, s in zip(p.shape, f)]
    a = np.abs(np.asarray(arr))
    a = np.where(np.isfinite(a), a, 0.0)
    pad = [(0, o * s - n) for n, s, o in zip(p.shape, f, out_shape)]
    a = np.pad(a, pad)
    a = a.reshape(out_shape[0], f[0], out_shape[1], f[1], out_shape[2], f[2]).max(axis=(1, 3, 5))
    s = np.pad(np.asarray(sup), pad).reshape(out_shape[0], f[0], out_shape[1], f[1], out_shape[2], f[2]).max(axis=(1, 3, 5))
    stats = next(x.stats for x in p.fields if x.property_name == field)
    scale = stats.get("abs_p99_9") or float(a.max() or 1.0)
    u8 = np.clip(a / scale * 255.0, 0, 255).astype(np.uint8)
    # texture order for WebGL Data3DTexture: x fastest, then y, then z
    return {"volume_id": p.id, "field": field, "display_only": True,
            "note": "DISPLAY-ONLY: block-max downsample of |%s|, scaled by its 99.9th percentile; "
                    "the scientific volume is unchanged" % field,
            "original_shape": list(p.shape), "shape": out_shape, "block_factors": f,
            "scale": scale, "data_u8_b64": _b64(np.transpose(u8, (2, 1, 0)), np.uint8),
            "support_u8_b64": _b64(np.transpose(s, (2, 1, 0)), np.uint8)}


# ---------------------------------------------------------------------------
# ground truth overlay (BAM only)
# ---------------------------------------------------------------------------
def ground_truth(p: VolumeProduct, dataset_meta: dict) -> dict:
    bench = (dataset_meta or {}).get("benchmark") or {}
    spec = bench.get("specimen_id")
    base = {"label": GROUND_TRUTH_LABEL, "available": False, "objects": []}
    if bench.get("benchmark_id") != "bam-concrete-gpr" or not spec:
        return {**base, "reason": "no independent construction ground truth is linked to this dataset"}
    if p.z_domain is not ZDomain.DEPTH:
        return {**base, "reason": "the drawings give depths; this volume's z is two-way time, and "
                                  "converting would need a depth model this volume does not have"}
    rows = [r for r in csv.DictReader(GROUND_TRUTH_CSV.open(encoding="utf-8")) if r["specimen_id"] == spec]
    mm = 1e-3
    objs = []
    for r in rows:
        t = r["object_type"]
        if t == "tendon_duct":
            objs.append({"id": r["object_id"], "kind": "duct", "role": r["role"],
                         "axis": "y", "x_m": float(r["x_mm"]) * mm, "z_centre_m": float(r["z_centre_mm"]) * mm,
                         "z_top_m": float(r["z_top_mm"]) * mm, "radius_m": 33.5 * mm,
                         "y_range_m": [0.0, 0.8]})
        elif t == "void_analogue_cuboid":
            y0, y1 = [float(v) for v in re.findall(r"[\d.]+", r["y_extent_mm"])[:2]]
            zt = float(r["z_top_mm"])
            objs.append({"id": r["object_id"], "kind": "box", "role": r["role"],
                         "x_range_m": [(float(r["x_mm"]) - 60) * mm, (float(r["x_mm"]) + 60) * mm],
                         "y_range_m": [y0 * mm, y1 * mm], "z_range_m": [zt * mm, (zt + 60) * mm],
                         "material": r["material"]})
        elif t == "grouted_borehole":
            objs.append({"id": r["object_id"], "kind": "surface_marker", "role": r["role"],
                         "x_m": float(r["x_mm"]) * mm, "y_m": float(r["y_mm"]) * mm,
                         "note": "drilled from the top surface; depth not dimensioned"})
        elif t == "step_back_wall":
            th = [float(v) for v in re.findall(r"(\d+\.\d)", r["dimensions_mm"])[:4]]
            for k, z in enumerate(th):
                objs.append({"id": f"{r['object_id']}-step{k}", "kind": "plane", "role": r["role"],
                             "x_range_m": [k * 0.5, (k + 1) * 0.5], "y_range_m": [0.0, 0.8], "z_m": z * mm})
    return {**base, "available": True, "specimen_id": spec,
            "source": "evidence/bam/specimen_ground_truth.csv (Grohmann et al. 2026 drawings)",
            "frame_note": "specimen grid metres; identical to this local volume's x/y; depth below the top surface",
            "specimen_bounds_m": {"x": [0.0, 2.0], "y": [0.0, 0.8]}, "objects": objs}
