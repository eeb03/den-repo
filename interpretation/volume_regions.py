"""
Interpretation V1: target-independent 3D response regions in a reconstructed
volume.

OPERATES ON THE VOLUME. The evidence is the volume's `response_envelope`
field (by default), in 3D, with its support classes -- not a 2D detector run
line by line. X, Y and Z coherence enter through 3D connectivity and the
region measurements.

THE RULE (all thresholds are ratios, so multiplying the volume by a constant
changes nothing; nothing reads a target, a manifest or a drawing):

  1. background per depth (or time) sample k: median and MAD (x1.4826) of the
     field over every SUPPORTED voxel at that k. robust_z = (e - med_k) / mad_k.
     Attenuation with depth is absorbed by per-k statistics.
  2. local contrast: e / local lateral background, where the background is
     the median of 8x8-voxel block medians over a lateral window of
     `local_window_m` at the same k (robust to the response itself).
  3. seeds: robust_z >= seed_robust_z AND local contrast >= seed_local_contrast
     AND the voxel is MEASURED or RECONSTRUCTED. Interpolated voxels can grow
     a region but can never seed one.
  4. hysteresis growth: the connected (6-, 18- or 26-) components of
     robust_z >= grow_robust_z AND local contrast >= grow_local_contrast that
     contain at least one seed. A laterally continuous layer (direct wave,
     back wall, flat interface) fills its own lateral window, has contrast ~1,
     and so neither forms a region nor bridges two responses.
  5. optional morphology: one 3x3x3 binary closing before labelling (off by
     default; recorded).
  6. size: components with fewer than `min_voxels` voxels are dropped.
  7. stacked-lobe merging (conservative): two components merge only when one
     sits directly above the other -- lateral footprints overlapping by at
     least `merge_min_footprint_overlap` of the smaller, a vertical gap of at
     most one pulse length (`merge_max_gap_m` / `_ns`), and peaks within
     three voxels laterally. Laterally separate responses are never merged.
  8. support: a component with no measured/reconstructed voxel is refused;
     one with less than `min_supported_fraction` supported voxels is kept as
     LOW_SUPPORT and penalised.

The volume itself is never modified.
"""
from __future__ import annotations

import base64
import time
from typing import Optional

import numpy as np
from scipy import ndimage as ndi

from schemas.region import (
    Bounds, RegionConfig, RegionEvidence, RegionShape, RegionStatus, RegionSupport, ResponseRegion,
    ScoreComponents, Triple,
)

ALGORITHM = "volume_response_regions"
ALGORITHM_VERSION = "1.0"
THRESHOLD_METHOD = ("per-depth robust z (median/MAD over supported voxels) with hysteresis "
                    "(seed/grow) + local lateral contrast ratio at seeds; seeds only on "
                    "measured/reconstructed voxels")
BLOCK = 8
MEASURED, RECONSTRUCTED, INTERPOLATED, UNSUPPORTED = 3, 2, 1, 0
STRUCTURES = {6: ndi.generate_binary_structure(3, 1), 18: ndi.generate_binary_structure(3, 2),
              26: ndi.generate_binary_structure(3, 3)}


def robust_background(field: np.ndarray, support: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-k median and MAD over supported voxels; returns (robust_z, med_k, mad_k)."""
    nx, ny, nz = field.shape
    flat = field.reshape(-1, nz).astype(np.float64)
    ok = (support.reshape(-1, nz) >= INTERPOLATED) & np.isfinite(flat)
    masked = np.where(ok, flat, np.nan)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(masked, axis=0)
            mad = np.nanmedian(np.abs(masked - med[None, :]), axis=0) * 1.4826
    med = np.nan_to_num(med)
    mad = np.where(np.isfinite(mad) & (mad > 0), mad, np.inf)
    z = (field - med[None, None, :].astype(np.float32)) / mad[None, None, :].astype(np.float32)
    z = np.where(np.isfinite(field), z, -np.inf).astype(np.float32)
    return z, med, mad


def local_background(field: np.ndarray, window_vox: tuple[int, int]) -> np.ndarray:
    """Lateral local background per k: median of 8x8 block medians over the window."""
    import warnings
    nx, ny, nz = field.shape
    bx, by = int(np.ceil(nx / BLOCK)), int(np.ceil(ny / BLOCK))
    pad = np.full((bx * BLOCK, by * BLOCK, nz), np.nan, np.float32)
    pad[:nx, :ny] = field
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        blocks = np.nanmedian(pad.reshape(bx, BLOCK, by, BLOCK, nz), axis=(1, 3))
    blocks = np.where(np.isfinite(blocks), blocks, np.nanmedian(blocks) if np.isfinite(blocks).any() else 0.0)
    wx = max(1, int(round(window_vox[0] / BLOCK))) | 1
    wy = max(1, int(round(window_vox[1] / BLOCK))) | 1
    bg = ndi.median_filter(blocks, size=(wx, wy, 1), mode="nearest")
    return np.repeat(np.repeat(bg, BLOCK, axis=0), BLOCK, axis=1)[:nx, :ny].astype(np.float32)


def _fwhm(line: np.ndarray, i: int, step: float) -> float:
    v = np.nan_to_num(line)
    half = v[i] / 2.0
    lo = i
    while lo > 0 and v[lo - 1] >= half:
        lo -= 1
    hi = i
    while hi < v.size - 1 and v[hi + 1] >= half:
        hi += 1
    return float((hi - lo + 1) * step)


def propose(field: np.ndarray, support: np.ndarray, distance: np.ndarray, axes: dict,
            config: RegionConfig, *, z_unit: str, region_set_id: str = "preview",
            volume_id: str = "", dataset_id: str = "", coordinate_frame: str = "local_volume",
            z_domain: str = "depth", modality: str = "gpr", unit: str = "arbitrary units",
            measure: bool = True) -> dict:
    """
    The whole rule on in-memory arrays. `axes` = {"x": (origin, step), "y": ..., "z": ...}.
    Returns {"regions": [...ResponseRegion], "rejected": {...}, "merges": [...], "background": {...}}.
    """
    t0 = time.perf_counter()
    nx, ny, nz = field.shape
    if config.connectivity not in STRUCTURES:
        raise ValueError("connectivity must be 6, 18 or 26")
    (x0, dx), (y0, dy), (z0, dz) = axes["x"], axes["y"], axes["z"]
    rz, med, mad = robust_background(field, support)
    t_bg = time.perf_counter()
    win = (int(round(config.local_window_m / dx)), int(round(config.local_window_m / dy)))
    if config.use_local_contrast:
        lbg = local_background(field, win)
        eps = 1e-12 + 1e-9 * float(np.nanmax(np.abs(field[np.isfinite(field)]))) if np.isfinite(field).any() else 1e-12
        contrast = np.where(np.isfinite(field), field / (lbg + eps), 0.0).astype(np.float32)
    else:
        contrast = None
    t_lc = time.perf_counter()

    supported = support >= RECONSTRUCTED
    seeds = (rz >= config.seed_robust_z) & supported
    interp_seeds = (rz >= config.seed_robust_z) & (support == INTERPOLATED)
    if contrast is not None:
        seeds &= contrast >= config.seed_local_contrast
        interp_seeds &= contrast >= config.seed_local_contrast
    grow = rz >= config.grow_robust_z
    if contrast is not None:
        grow &= contrast >= config.grow_local_contrast
    if config.closing:
        grow = ndi.binary_closing(grow, structure=STRUCTURES[config.connectivity]) & np.isfinite(field)
    labels, n = ndi.label(grow, structure=STRUCTURES[config.connectivity])
    rejected = {"no_seed": 0, "tiny": 0, "interpolation_only": 0, "seeded_only_by_interpolation": 0}
    if n == 0:
        return {"regions": [], "rejected": rejected, "merges": [],
                "background": {"components_before_filtering": 0}}
    seeded = np.zeros(n + 1, bool)
    seeded[np.unique(labels[seeds])] = True
    seeded[0] = False
    interp_seeded = np.zeros(n + 1, bool)
    interp_seeded[np.unique(labels[interp_seeds])] = True
    interp_seeded[0] = False
    rejected["seeded_only_by_interpolation"] = int(np.sum(interp_seeded & ~seeded))
    rejected["no_seed"] = int(n - seeded[1:].sum() - rejected["seeded_only_by_interpolation"])
    sizes = np.bincount(labels.ravel(), minlength=n + 1)
    keep = seeded & (sizes >= config.min_voxels)
    rejected["tiny"] = int(np.sum(seeded & (sizes < config.min_voxels)))
    # interpolation-only components (all voxels interpolated) are refused
    sup_count = np.bincount(labels.ravel(), weights=supported.ravel().astype(np.float64), minlength=n + 1)
    if config.refuse_interpolation_only:
        io = keep & (sup_count == 0)
        rejected["interpolation_only"] = int(io.sum())
        keep &= ~io
    kept = np.flatnonzero(keep)
    objs = ndi.find_objects(labels)
    t_lab = time.perf_counter()

    # ---- conservative stacked-lobe merging --------------------------------------
    parent = {int(l): int(l) for l in kept}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    info = {}
    for l in kept:
        sl = objs[l - 1]
        sub = labels[sl] == l
        f = np.where(sub, np.nan_to_num(field[sl]), -np.inf)
        a, b, c = np.unravel_index(np.argmax(f), f.shape)
        info[int(l)] = {"sl": sl, "peak": (sl[0].start + a, sl[1].start + b, sl[2].start + c)}
    merges = []
    gap_lim = config.merge_max_gap_m if z_unit == "m" else config.merge_max_gap_ns
    if config.merge_stacked_lobes and len(kept) > 1:
        ks = sorted(info)
        for ai, a in enumerate(ks):
            sa = info[a]["sl"]
            for b in ks[ai + 1:]:
                sb = info[b]["sl"]
                ox = min(sa[0].stop, sb[0].stop) - max(sa[0].start, sb[0].start)
                oy = min(sa[1].stop, sb[1].stop) - max(sa[1].start, sb[1].start)
                if ox <= 0 or oy <= 0:
                    continue
                area_a = (sa[0].stop - sa[0].start) * (sa[1].stop - sa[1].start)
                area_b = (sb[0].stop - sb[0].start) * (sb[1].stop - sb[1].start)
                if ox * oy < config.merge_min_footprint_overlap * min(area_a, area_b):
                    continue
                gap = max(sa[2].start, sb[2].start) - min(sa[2].stop, sb[2].stop)
                if gap * dz > gap_lim:
                    continue
                pa, pb = info[a]["peak"], info[b]["peak"]
                if abs(pa[0] - pb[0]) > 3 or abs(pa[1] - pb[1]) > 3:
                    continue
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra
                    merges.append({"kept": int(ra), "merged": int(rb), "vertical_gap": round(float(max(gap, 0) * dz), 5),
                                   "footprint_overlap": round(float(ox * oy / min(area_a, area_b)), 3)})
    groups: dict[int, list[int]] = {}
    for l in kept:
        groups.setdefault(find(int(l)), []).append(int(l))
    t_merge = time.perf_counter()

    regions = []
    if measure:
        for root, members in groups.items():
            regions.append(_measure(field, support, distance, labels, members, info, rz, contrast,
                                    axes, config, z_unit, region_set_id, volume_id, dataset_id,
                                    coordinate_frame, z_domain, modality, unit))
        regions.sort(key=lambda r: -r.evidence_score)
        for n_, r in enumerate(regions):
            r.id = f"{region_set_id}-r{n_ + 1:04d}"
    t_meas = time.perf_counter()
    return {"regions": regions, "rejected": rejected, "merges": merges,
            "candidate_count": len(groups),
            "background": {"components_before_filtering": int(n), "median_per_k_range": [float(np.min(med)), float(np.max(med))],
                           "local_window_voxels": list(win)},
            "timings": {"background_s": round(t_bg - t0, 3), "local_contrast_s": round(t_lc - t_bg, 3),
                        "labelling_s": round(t_lab - t_lc, 3), "merging_s": round(t_merge - t_lab, 3),
                        "measurement_s": round(t_meas - t_merge, 3)}}


def _measure(field, support, distance, labels, members, info, rz, contrast, axes, config, z_unit,
             set_id, volume_id, dataset_id, frame, z_domain, modality, unit) -> ResponseRegion:
    (x0, dx), (y0, dy), (z0, dz) = axes["x"], axes["y"], axes["z"]
    sls = [info[m]["sl"] for m in members]
    sl = tuple(slice(min(s[a].start for s in sls), max(s[a].stop for s in sls)) for a in range(3))
    mask = np.isin(labels[sl], members)
    ii, jj, kk = np.nonzero(mask)
    gi, gj, gk = ii + sl[0].start, jj + sl[1].start, kk + sl[2].start
    vals = np.nan_to_num(field[gi, gj, gk]).astype(np.float64)
    w = np.maximum(vals, 0) + 1e-12
    xs, ys, zs = x0 + gi * dx, y0 + gj * dy, z0 + gk * dz
    p = int(np.argmax(vals))
    pi_, pj_, pk_ = int(gi[p]), int(gj[p]), int(gk[p])
    sup = support[gi, gj, gk]
    nvox = int(mask.sum())
    frac = {c: float(np.mean(sup == v)) for c, v in (("m", MEASURED), ("r", RECONSTRUCTED),
                                                       ("i", INTERPOLATED), ("u", UNSUPPORTED))}
    dists = distance[gi, gj]
    dists = dists[np.isfinite(dists)]
    supported_frac = frac["m"] + frac["r"]
    status = RegionStatus.PROPOSED if supported_frac >= config.min_supported_fraction else RegionStatus.LOW_SUPPORT
    # PCA in physical units (z in its own unit; azimuth / dip only when z is metres)
    C = np.cov(np.vstack([xs, ys, zs]), aweights=w) if nvox > 1 else np.zeros((3, 3))
    ev, evec = np.linalg.eigh(np.atleast_2d(C))
    order = np.argsort(ev)[::-1]
    ev, evec = np.clip(ev[order], 0, None), evec[:, order]
    ax0 = evec[:, 0]
    az = dip = None
    if z_unit == "m":
        az = float(np.degrees(np.arctan2(ax0[1], ax0[0])) % 180.0)
        dip = float(np.degrees(np.arcsin(min(1.0, abs(ax0[2])))))
    bbox_vox = mask.size
    lines = int(np.unique(gj).size)
    traces = int(np.unique(gi).size)
    peak_z = float(rz[pi_, pj_, pk_])
    peak_c = float(contrast[pi_, pj_, pk_]) if contrast is not None else float("nan")
    touches = (sl[0].start == 0 or sl[0].stop == field.shape[0] or sl[1].start == 0 or sl[1].stop == field.shape[1])
    comps = ScoreComponents(
        response_strength=float(1 - np.exp(-max(peak_z, 0) / 20.0)),
        local_contrast=float(1 - 1 / max(peak_c, 1.0)) if np.isfinite(peak_c) else 0.0,
        persistence_3d=float(min(1.0, lines / 5) * min(1.0, traces / 5)),
        support_quality=float(supported_frac),
        compactness=float(nvox / bbox_vox),
        interpolation_penalty=float(frac["i"]),
        boundary_penalty=1.0 if touches else 0.0)
    score = float(np.mean([comps.response_strength, comps.local_contrast, comps.persistence_3d,
                           comps.support_quality]) - 0.25 * (comps.interpolation_penalty + comps.boundary_penalty))
    flags = []
    if status is RegionStatus.LOW_SUPPORT:
        flags.append("low_support: fewer than %.0f%% of voxels measured/reconstructed" % (100 * config.min_supported_fraction))
    if support[pi_, pj_, pk_] == INTERPOLATED:
        flags.append("peak_in_interpolated_voxel")
    if touches:
        flags.append("touches_lateral_boundary: extent may be truncated")
    if len(members) > 1:
        flags.append(f"merged_{len(members)}_stacked_lobes")
    return ResponseRegion(
        id="", region_set_id=set_id, volume_id=volume_id, dataset_id=dataset_id,
        coordinate_frame=frame, z_domain=z_domain, z_unit=z_unit, status=status, voxel_count=nvox,
        centroid=Triple(x=float(np.average(xs, weights=w)), y=float(np.average(ys, weights=w)),
                        z=float(np.average(zs, weights=w))),
        peak_location=Triple(x=x0 + pi_ * dx, y=y0 + pj_ * dy, z=z0 + pk_ * dz),
        peak_index=(pi_, pj_, pk_),
        bounds=Bounds(x_min=x0 + sl[0].start * dx, x_max=x0 + (sl[0].stop - 1) * dx,
                      y_min=y0 + sl[1].start * dy, y_max=y0 + (sl[1].stop - 1) * dy,
                      z_min=z0 + sl[2].start * dz, z_max=z0 + (sl[2].stop - 1) * dz),
        index_bounds=(sl[0].start, sl[0].stop - 1, sl[1].start, sl[1].stop - 1, sl[2].start, sl[2].stop - 1),
        physical_extent=Triple(x=(sl[0].stop - sl[0].start) * dx, y=(sl[1].stop - sl[1].start) * dy,
                               z=(sl[2].stop - sl[2].start) * dz),
        fwhm=Triple(x=_fwhm(field[:, pj_, pk_], pi_, dx), y=_fwhm(field[pi_, :, pk_], pj_, dy),
                    z=_fwhm(field[pi_, pj_, :], pk_, dz)),
        lines_spanned=lines,
        support=RegionSupport(
            measured_voxel_fraction=frac["m"], reconstructed_voxel_fraction=frac["r"],
            interpolated_voxel_fraction=frac["i"], unsupported_voxel_fraction=frac["u"],
            nearest_measurement_distance_m=({"min": float(dists.min()), "median": float(np.median(dists)),
                                             "max": float(dists.max())} if dists.size else {}),
            peak_support_class={3: "MEASURED", 2: "RECONSTRUCTED", 1: "INTERPOLATED", 0: "UNSUPPORTED"}[int(support[pi_, pj_, pk_])]),
        shape=RegionShape(pca_eigenvalues=[float(v) for v in ev], pca_axes=[[float(c) for c in evec[:, i]] for i in range(3)],
                          elongation=float(np.sqrt(ev[0] / max(ev[1], 1e-18))),
                          flatness=float(np.sqrt(ev[1] / max(ev[2], 1e-18))),
                          compactness=float(nvox / bbox_vox), azimuth_deg=az, dip_deg=dip),
        evidence=[RegionEvidence(modality=modality, property_name=config.field, unit=unit,
                                 method=THRESHOLD_METHOD, peak_value=float(vals[p]), peak_robust_z=peak_z,
                                 peak_local_contrast=peak_c, integrated_response=float(vals.sum()),
                                 mean_response=float(vals.mean()))],
        score_components=comps, evidence_score=score, merged_from=sorted(members) if len(members) > 1 else [],
        flags=flags, mask_b64=base64.b64encode(np.packbits(mask.ravel())).decode())


def unpack_mask(region: ResponseRegion) -> np.ndarray:
    i0, i1, j0, j1, k0, k1 = region.index_bounds
    shape = (i1 - i0 + 1, j1 - j0 + 1, k1 - k0 + 1)
    bits = np.unpackbits(np.frombuffer(base64.b64decode(region.mask_b64), np.uint8))[: int(np.prod(shape))]
    return bits.reshape(shape).astype(bool)


def eligibility(product, staleness: dict, config: RegionConfig) -> list[str]:
    """Reasons a volume may NOT be interpreted (empty = eligible)."""
    reasons = []
    if staleness.get("stale"):
        reasons.append("the volume is stale (" + "; ".join(staleness.get("reasons") or []) + "); regenerate it first")
    if not any(f.property_name == config.field for f in product.fields):
        reasons.append(f"the volume has no field {config.field!r}")
    total = sum(product.support_summary.values()) or 1
    unsup = product.support_summary.get("UNSUPPORTED", 0) / total
    interp = product.support_summary.get("INTERPOLATED", 0) / total
    if unsup > config.max_volume_unsupported_fraction:
        reasons.append(f"{unsup:.0%} of the volume is unsupported (limit {config.max_volume_unsupported_fraction:.0%})")
    if interp > config.max_volume_interpolated_fraction:
        reasons.append(f"{interp:.0%} of the volume is interpolated (limit {config.max_volume_interpolated_fraction:.0%})")
    return reasons
