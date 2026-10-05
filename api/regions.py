"""
Region service: preview, create, staleness, slice overlays, reviews, and a
label-free export manifest for a future training corpus.

Nothing here runs when the viewer merely opens: generation is an explicit
POST after a preview.
"""
from __future__ import annotations

import base64
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from database.regions_store import (
    append_review, list_region_sets, load_region_set, load_reviews, review_history, save_region_set,
)
from database.volumes_store import load_volume, open_array
from interpretation.volume_regions import (
    ALGORITHM, ALGORITHM_VERSION, THRESHOLD_METHOD, eligibility, propose, unpack_mask,
)
from reconstruction.volume import staleness as volume_staleness
from schemas.region import RegionConfig, RegionReview, RegionReviewStatus, RegionSet


class RegionError(ValueError):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class NotFound(LookupError):
    pass


def _volume(dataset_id, volume_id):
    p = load_volume(dataset_id, volume_id)
    if p is None:
        raise NotFound("volume")
    return p


def _inputs(product, config: RegionConfig):
    field = np.asarray(open_array(product, next(f.file for f in product.fields if f.property_name == config.field)))
    support = np.asarray(open_array(product, product.support_file))
    dist2 = np.asarray(open_array(product, product.distance_file))
    axes = {k: (getattr(product, f"{k}_axis").origin, getattr(product, f"{k}_axis").step) for k in "xyz"}
    unit = next(f.unit for f in product.fields if f.property_name == config.field)
    return field, support, dist2, axes, unit


def preview(dataset_id: str, volume_id: str, config: RegionConfig) -> dict:
    product = _volume(dataset_id, volume_id)
    st = volume_staleness(product)
    reasons = eligibility(product, st, config)
    out = {"possible": not reasons, "refusals": reasons, "algorithm": f"{ALGORITHM} {ALGORITHM_VERSION}",
           "threshold_method": THRESHOLD_METHOD, "config": config.model_dump(),
           "volume": {"id": product.id, "z_domain": product.z_domain.value, "z_unit": product.z_axis.unit,
                      "migration": product.migration.method, "shape": list(product.shape),
                      "support_summary": product.support_summary},
           "notes": []}
    if product.migration.method == "none":
        out["notes"].append("this volume is not migrated; a migrated depth volume is preferred "
                            "(hyperbola tails are not focused)")
    if product.z_domain.value != "depth":
        out["notes"].append("time-domain volume: regions will be measured in ns along z, never in metres")
    if reasons:
        return out
    t = time.perf_counter()
    field, support, dist2, axes, unit = _inputs(product, config)
    res = propose(field, support, dist2, axes, config, z_unit=product.z_axis.unit, measure=False)
    out["estimated_region_count"] = res["candidate_count"]
    out["rejected"] = res["rejected"]
    out["merges"] = len(res["merges"])
    out["preview_seconds"] = round(time.perf_counter() - t, 2)
    return out


def create(dataset_id: str, volume_id: str, config: RegionConfig, created_by: Optional[str]) -> RegionSet:
    product = _volume(dataset_id, volume_id)
    st = volume_staleness(product)
    reasons = eligibility(product, st, config)
    if reasons:
        raise RegionError(reasons)
    t = time.perf_counter()
    field, support, dist2, axes, unit = _inputs(product, config)
    set_id = "rs" + uuid.uuid4().hex[:10]
    res = propose(field, support, dist2, axes, config, z_unit=product.z_axis.unit, region_set_id=set_id,
                  volume_id=product.id, dataset_id=dataset_id,
                  coordinate_frame=product.coordinate_frame.kind.value, z_domain=product.z_domain.value,
                  modality=product.modality, unit=unit)
    rs = RegionSet(
        id=set_id, volume_id=product.id, dataset_id=dataset_id, algorithm=ALGORITHM,
        algorithm_version=ALGORITHM_VERSION, threshold_method=THRESHOLD_METHOD, config=config,
        source_volume_fingerprint=product.source_fingerprint, source_volume_components=product.input_components,
        z_domain=product.z_domain.value, z_unit=product.z_axis.unit, migrated=product.migration.method != "none",
        created_at=datetime.now(timezone.utc), created_by=created_by, regions=res["regions"],
        rejected=res["rejected"], merges=res["merges"], background=res["background"],
        performance={**res["timings"], "total_s": round(time.perf_counter() - t, 3)})
    save_region_set(rs)
    return rs


def staleness(rs: RegionSet) -> dict:
    product = load_volume(rs.dataset_id, rs.volume_id)
    if product is None:
        return {"stale": True, "reasons": ["the source volume no longer exists"], "action": "regenerate from a current volume"}
    reasons = []
    if product.source_fingerprint != rs.source_volume_fingerprint:
        reasons.append("the source volume's fingerprint changed")
    vs = volume_staleness(product)
    if vs.get("stale"):
        reasons += [f"source volume: {r}" for r in vs.get("reasons", [])]
    if rs.algorithm_version != ALGORITHM_VERSION:
        reasons.append(f"the region algorithm changed ({rs.algorithm_version} -> {ALGORITHM_VERSION})")
    return {"stale": bool(reasons), "reasons": reasons,
            "action": "regenerate the volume and/or the region set explicitly (not done automatically)" if reasons else None}


def current_reviews(dataset_id: str, volume_id: str) -> dict[str, RegionReview]:
    cur: dict[str, RegionReview] = {}
    for r in load_reviews(dataset_id, volume_id):
        cur[r.region_id] = r
    return cur


def set_payload(rs: RegionSet, include_masks: bool = False) -> dict:
    d = rs.model_dump(mode="json")
    reviews = current_reviews(rs.dataset_id, rs.volume_id)
    for r in d["regions"]:
        if not include_masks:
            r.pop("mask_b64", None)
        rv = reviews.get(r["id"])
        r["review"] = rv.model_dump(mode="json") if rv else {"status": "unreviewed"}
    d["staleness"] = staleness(rs)
    return d


def get_set(dataset_id, volume_id, set_id) -> RegionSet:
    rs = load_region_set(dataset_id, volume_id, set_id)
    if rs is None:
        raise NotFound("region set")
    return rs


def get_region(rs: RegionSet, region_id: str):
    r = next((x for x in rs.regions if x.id == region_id), None)
    if r is None:
        raise NotFound("region")
    return r


def region_payload(rs: RegionSet, region_id: str) -> dict:
    r = get_region(rs, region_id).model_dump(mode="json")
    r.pop("mask_b64", None)
    r["review_history"] = [x.model_dump(mode="json") for x in review_history(rs.dataset_id, rs.volume_id, region_id)]
    r["review"] = r["review_history"][-1] if r["review_history"] else {"status": "unreviewed"}
    r["generation"] = {"algorithm": rs.algorithm, "version": rs.algorithm_version,
                       "threshold_method": rs.threshold_method, "config": rs.config.model_dump(),
                       "source_volume_fingerprint": rs.source_volume_fingerprint, "created_at": rs.created_at.isoformat(),
                       "migrated_volume": rs.migrated}
    return r


def review(rs: RegionSet, region_id: str, status: str, reviewer_id: str, notes: Optional[str]) -> RegionReview:
    region = get_region(rs, region_id)
    try:
        st = RegionReviewStatus(status)
    except ValueError:
        raise RegionError([f"status must be one of {[s.value for s in RegionReviewStatus if s.value != 'unreviewed']}"])
    if st is RegionReviewStatus.UNREVIEWED:
        raise RegionError(["a review records a judgement; 'unreviewed' is not one"])
    snap = {k: v for k, v in region.model_dump(mode="json").items() if k not in ("mask_b64",)}
    return append_review(RegionReview(region_id=region_id, region_set_id=rs.id, volume_id=rs.volume_id,
                                      dataset_id=rs.dataset_id, status=st, reviewer_id=reviewer_id, notes=notes,
                                      region_snapshot={k: snap[k] for k in ("evidence_score", "centroid", "bounds",
                                                                            "voxel_count", "support", "status")}))


def slice_labels(rs: RegionSet, product, orientation: str, index: int) -> dict:
    """uint16 per pixel: 0 = no region, n = the n-th region of the set (1-based, `order`)."""
    nx, ny, nz = product.shape
    shape = {"xy": (ny, nx), "xz": (nz, nx), "yz": (nz, ny)}.get(orientation)
    if shape is None:
        raise RegionError(["orientation must be xy, xz or yz"])
    out = np.zeros(shape, np.uint16)
    order = []
    for n, r in enumerate(rs.regions, start=1):
        i0, i1, j0, j1, k0, k1 = r.index_bounds
        lo, hi = {"xy": (k0, k1), "xz": (j0, j1), "yz": (i0, i1)}[orientation]
        if not lo <= index <= hi:
            continue
        m = unpack_mask(r)
        if orientation == "xy":
            out[j0:j1 + 1, i0:i1 + 1][m[:, :, index - k0].T] = n
        elif orientation == "xz":
            out[k0:k1 + 1, i0:i1 + 1][m[:, index - j0, :].T] = n
        else:
            out[k0:k1 + 1, j0:j1 + 1][m[index - i0, :, :].T] = n
    for n, r in enumerate(rs.regions, start=1):
        order.append(r.id)
    return {"orientation": orientation, "index": index, "rows": shape[0], "cols": shape[1],
            "labels_u16_b64": base64.b64encode(out.astype("<u2").tobytes()).decode(), "order": order}


def export_manifest(rs: RegionSet, product) -> dict:
    """
    A label-free manifest a future training corpus can be built from: where
    each region's crop lives, what it was measured with, and the OPERATOR
    review (evidence grade C) as the only judgement -- nothing is inferred.
    """
    reviews = current_reviews(rs.dataset_id, rs.volume_id)
    items = []
    for r in rs.regions:
        i0, i1, j0, j1, k0, k1 = r.index_bounds
        pad = 8
        items.append({
            "region_id": r.id, "volume_id": rs.volume_id, "dataset_id": rs.dataset_id,
            "crop_index_bounds": [max(0, i0 - pad), min(product.shape[0] - 1, i1 + pad),
                                  max(0, j0 - pad), min(product.shape[1] - 1, j1 + pad),
                                  max(0, k0 - pad), min(product.shape[2] - 1, k1 + pad)],
            "region_mask": {"index_bounds": list(r.index_bounds), "packbits_b64": r.mask_b64},
            "fields": [f.file for f in product.fields], "support_field": product.support_file,
            "voxel_spacing": list(product.voxel_spacing), "z_domain": rs.z_domain, "z_unit": rs.z_unit,
            "orientation": {"azimuth_deg": r.shape.azimuth_deg, "dip_deg": r.shape.dip_deg},
            "modality": product.modality, "migration": product.migration.method,
            "calibration": {k: product.calibration_provenance.get(k) for k in ("velocity", "time_zero")},
            "operator_review": (reviews[r.id].status.value if r.id in reviews else "unreviewed"),
            "label_policy": "no label beyond the operator review (grade C); no class is inferred"})
    return {"region_set_id": rs.id, "items": items, "count": len(items)}
