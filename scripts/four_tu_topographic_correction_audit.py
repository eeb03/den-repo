"""
Does 4TU's own held evidence justify a PER-TRACE topographic/air-gap
correction, on top of the single per-line time-zero correction
`preprocessing.time_zero` already resolves -- or is the antenna's height
above ground stable enough along a real line that a single constant
correction is already the honest, sufficient answer?

THIS IS A RESEARCH AUDIT, NOT A PRODUCT FEATURE. Same discipline as the
BAM velocity audits: reads real files already on disk (a 4TU SEG-Y line
via the existing `SEGYConverter`, an AHN DTM tile already fetched and
matched to that GPR site by `scripts/acquire_ahn_windows.py`, see
`datasets/raw/pdok_ahn/dtm_05m/PROVENANCE_site*.json`), touches no live
dataset, no provenance schema, writes only a JSON artifact under
`artifacts/4tu/`. Reproduce with:

    python -m scripts.four_tu_topographic_correction_audit --out artifacts/4tu/topographic_correction_audit.json

WHY THIS QUESTION, AND WHY NOW. The roadmap's own dependency chain names
topographic correction as the step after velocity estimation, gated on
"reliable elevation exists ... needs its own physical/geometric
justification, not visual alignment." 4TU is the one held dataset with
BOTH a per-trace acquisition elevation (`coordinate_encoding="ieee_nmea"`)
and a matched, real DEM (AHN DTM 0.5m) already fetched for several sites
-- so it is the one place this question can be asked from real evidence
rather than assumed either way.

THE PHYSICAL QUESTION THIS AUDIT ANSWERS, PRECISELY. `record.elevation`
(the antenna's own GNSS elevation) varies along a real line -- but that
alone does not mean the AIR-GAP (antenna height above the actual ground)
varies: a terrain-following acquisition would show antenna elevation
tracking real ground relief while height-above-ground stays constant, in
which case a single time-zero correction is already correct and a
per-trace refinement would be manufacturing precision the acquisition
never held. Only comparing antenna elevation against the GROUND's OWN
elevation (from the DEM, at the same points) can tell the two apart. This
audit computes `height_above_ground = antenna_elevation - dem_ground_elevation`
per trace and reports its VARIATION (not its absolute value -- see the
next paragraph) along the line.

WHY THE ABSOLUTE VALUE IS NOT TRUSTED, BUT THE VARIATION IS. Both
elevation sources carry an UNDECLARED vertical datum (see
`docs/4tu-elevation-field-identification.md` and this DEM tile's own
`PROVENANCE_site*.json`: "elevation_datum": "UNDECLARED"). A constant
datum offset between them would bias `height_above_ground`'s ABSOLUTE
value by an unknown amount -- but it cancels exactly out of a
DIFFERENTIAL correction: `deviation_i = height_above_ground_i -
median(height_above_ground)` is a relative quantity, unaffected by
whatever constant the two datums disagree by. This audit never reports
or acts on the absolute height-above-ground value; only `deviation_i`,
converted to a two-way air-time correction via the vacuum/air speed of
light (`ingestion.four_tu_velocity.C_M_PER_NS`, reused rather than
redefined), is used.

WHAT "MATERIAL" MEANS HERE. A trace's own topographic deviation is
reported as material only if the resulting time correction exceeds the
line's own sample interval -- below that, the acquisition's own temporal
resolution cannot distinguish the correction from no correction at all,
and applying one would be fabricating a precision the data does not
support. This mirrors `preprocessing.time_zero`'s own refusal to report a
numeric result finer than what the evidence can defend.

WHAT THIS AUDIT DOES NOT DO. It does not touch DEFAULT_GPR_VELOCITY_M_PER_NS,
does not change any live dataset, does not resolve 4TU's absolute depth
(still blocked on validated velocity and the author's own confirmed
absence of an air-gap correction) and does not assert the DEM's vertical
datum matches the antenna's -- it explicitly relies on that datum
DIFFERENCE being irrelevant to a differential correction, not on knowing
what it is.
"""
from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from converters.segy_converter import SEGYConverter
from ingestion.four_tu_velocity import C_M_PER_NS
from preprocessing.dem_alignment import sample_dem_bilinear
from preprocessing.time_zero import metadata_instrument_time_zero
from schemas.subterra_record import SensorType
from schemas.survey_frame import SurveyFrame

REPO_ROOT = Path(__file__).resolve().parent.parent
DEM_ROOT = REPO_ROOT / "datasets" / "raw" / "pdok_ahn" / "dtm_05m"


class AuditError(RuntimeError):
    """Raised when the audit cannot proceed at all (missing file, no overlap)."""


@dataclass
class TracePoint:
    trace_index: int
    lat: float
    lon: float
    antenna_elevation_m: float
    two_way_time_ns: float  # sample 0's raw time, i.e. this trace's own axis origin


def load_line(segy_path: Path) -> tuple[list[TracePoint], Optional[SurveyFrame], float]:
    """
    One representative point per trace (lat/lon/antenna elevation), the
    real `SurveyFrame` `SEGYConverter` itself built (for Method A time-zero
    -- `metadata_instrument_time_zero` reads the frame's OWN
    `time_axis_origin_offset` assumption, which only the converter's
    actual returned frame carries; a synthesized frame would not),
    and the sample interval.
    """
    result = SEGYConverter().load(str(segy_path), dataset_id="4tu-topo-audit-not-persisted",
                                  sensor_type=SensorType.GPR, coordinate_encoding="ieee_nmea")
    records = result.records
    by_trace: dict = {}
    for r in records:
        ti = r.metadata.get("trace_index")
        if ti is not None and ti not in by_trace:
            by_trace[ti] = r
    points = []
    for ti in sorted(by_trace):
        r = by_trace[ti]
        if r.latitude is None or r.longitude is None or r.elevation is None:
            continue
        points.append(TracePoint(ti, r.latitude, r.longitude, r.elevation,
                                 r.metadata.get("two_way_time_ns", 0.0)))

    frame = result.frames[0] if result.frames else None

    intervals = []
    times_by_trace: dict = {}
    for r in records:
        ti = r.metadata.get("trace_index")
        times_by_trace.setdefault(ti, []).append(r.metadata.get("two_way_time_ns"))
    for times in list(times_by_trace.values())[:5]:
        times = sorted(t for t in times if t is not None)
        if len(times) >= 2:
            intervals.append(times[1] - times[0])
    sample_interval_ns = statistics.median(intervals) if intervals else 0.0

    return points, frame, sample_interval_ns


def height_above_ground(points: list[TracePoint], dem_path: Path) -> dict:
    """
    `dem_ground_elevation_m` per trace, via the exact reprojection +
    bilinear sampling `converters.segy_converter._to_wgs84` /
    `preprocessing.dem_alignment.sample_dem_bilinear` already use elsewhere
    in this codebase -- reused, not reimplemented.
    """
    import numpy as np
    import rasterio
    from rasterio.warp import transform as rio_transform

    lats = [p.lat for p in points]
    lons = [p.lon for p in points]

    with rasterio.open(dem_path) as ds:
        band = ds.read(1).astype(float)
        # Same masking `preprocessing.dem_alignment.align_records_with_dem` already
        # applies -- without it, a nodata sentinel (3.4e38 for this AHN product)
        # blends into a real neighbour via bilinear interpolation and produces a
        # physically absurd value instead of a clean exclusion.
        if ds.nodata is not None:
            band[band == ds.nodata] = np.nan
        transform = ds.transform
        eastings, northings = rio_transform("EPSG:4326", ds.crs, lons, lats)
        ground = sample_dem_bilinear(band, transform, northings, eastings)
        dem_crs = str(ds.crs)

    valid = ~np.isnan(ground)
    n_valid = int(valid.sum())
    if n_valid == 0:
        return {"n_valid": 0, "reason": "no trace fell within the DEM tile's coverage"}

    antenna = np.array([p.antenna_elevation_m for p in points])
    hag = antenna - ground
    hag_valid = hag[valid]
    median_hag = float(np.median(hag_valid))
    deviation = hag - median_hag  # relative to the LINE's own reference, datum-offset cancels

    return {
        "n_valid": n_valid, "n_total": len(points), "dem_crs": dem_crs,
        "height_above_ground_m": {
            "median": median_hag, "std": float(np.std(hag_valid)),
            "min": float(np.min(hag_valid)), "max": float(np.max(hag_valid)),
            "range": float(np.max(hag_valid) - np.min(hag_valid)),
        },
        "per_trace_deviation_m": {
            int(points[i].trace_index): float(deviation[i]) for i in range(len(points))
            if valid[i]
        },
    }


def classify_material(deviation_m: dict, sample_interval_ns: float) -> dict:
    """
    Converts each trace's deviation into a two-way air-time correction
    (`Delta t = 2 * deviation / C_M_PER_NS`, air/vacuum speed of light --
    NOT the ground velocity, since this deviation is an AIR path, not a
    subsurface one) and reports whether the resulting correction is
    resolvable at all against the line's own sample interval.
    """
    if not deviation_m:
        return {"material": False, "reason": "no valid deviation data"}
    corrections_ns = {tid: 2 * dev / C_M_PER_NS for tid, dev in deviation_m.items()}
    vals = list(corrections_ns.values())
    max_abs = max(abs(v) for v in vals)
    material = max_abs > sample_interval_ns
    return {
        "per_trace_correction_ns": corrections_ns,
        "max_abs_correction_ns": max_abs,
        "sample_interval_ns": sample_interval_ns,
        "material": material,
        "reason": (
            f"max |correction| {max_abs:.4f} ns "
            f"{'exceeds' if material else 'does not exceed'} the line's own sample interval "
            f"({sample_interval_ns:.4f} ns) -- {'resolvable' if material else 'NOT resolvable'} "
            f"against the acquisition's own temporal resolution"
        ),
    }


def run_audit(project: str, segy_relpath: str, dem_site: str) -> dict:
    generated = datetime.now(timezone.utc).isoformat()
    segy_path = REPO_ROOT / "datasets" / "raw" / "4tu" / "96303227-5886-41c9-8607-70fdd2cfe7c1" / \
        "extracted" / segy_relpath
    dem_path = DEM_ROOT / f"AHN_DTM_05m_{dem_site}.tif"
    if not segy_path.exists():
        raise AuditError(f"SEG-Y file not found: {segy_path}")
    if not dem_path.exists():
        raise AuditError(f"DEM tile not found: {dem_path}")

    points, frame, sample_interval_ns = load_line(segy_path)
    if len(points) < 3:
        raise AuditError(f"fewer than 3 traces carry lat/lon/elevation: {len(points)}")

    base_t0 = metadata_instrument_time_zero(frame) if frame is not None else None
    hag = height_above_ground(points, dem_path)
    topo = classify_material(hag.get("per_trace_deviation_m", {}), sample_interval_ns)

    return {
        "audit": "4tu-topographic-correction",
        "generated_utc": generated,
        "source": {"project": project, "segy_path": str(segy_relpath), "dem_tile": dem_path.name},
        "n_traces": len(points),
        "sample_interval_ns": sample_interval_ns,
        "base_time_zero": base_t0.model_dump(mode="json") if base_t0 is not None else None,
        "height_above_ground": {k: v for k, v in hag.items() if k != "per_trace_deviation_m"},
        "topographic_correction": {k: v for k, v in topo.items() if k != "per_trace_correction_ns"},
        "product_implication": (
            "Not a live product change. This audit does not apply any correction to a live "
            "dataset; it only reports whether the evidence would justify one."
        ),
    }


#: Real 4TU lines with a matched, already-fetched AHN tile -- run together
#: by default so a reader sees more than one line's answer.
DEFAULT_LINES = (
    ("01", "01/01/01.1/Radargrams/Path8.sgy", "site01"),
    ("01", "01/01/01.5/Radargrams/Path1.sgy", "site01"),
    ("06", "06/06/06.1/Radargrams/Path1.sgy", "site06"),
    ("012", "012/012/012.8/Radargrams/Path1.sgy", "site012"),
)


def run_audit_all_lines(lines: list) -> dict:
    per_line = {}
    for project, segy_relpath, dem_site in lines:
        key = f"{project}:{Path(segy_relpath).name}"
        try:
            per_line[key] = run_audit(project, segy_relpath, dem_site)
        except AuditError as exc:
            per_line[key] = {"error": str(exc)}

    materials = [r["topographic_correction"]["material"] for r in per_line.values()
                if "topographic_correction" in r]
    return {
        "audit": "4tu-topographic-correction-all-lines",
        "per_line": per_line,
        "any_line_material": any(materials),
        "all_lines_material": all(materials) if materials else False,
        "n_lines_checked": len(materials),
        "n_lines_material": sum(materials),
        "note": (
            "Each line is a separate acquisition; results are not pooled or averaged. "
            "A line classifying 'material' here means real, resolvable, evidence-based "
            "topographic variation exists for THAT line -- not that 4TU depth is unblocked "
            "(velocity remains unvalidated and the author-confirmed absence of an air-gap "
            "correction is a separate, larger open question)."
        ),
    }


def _print_summary(result: dict) -> None:
    src = result["source"]
    print(f"4TU {src['project']} / {src['segy_path']}")
    print(f"  {result['n_traces']} traces, sample interval {result['sample_interval_ns']:.4f} ns")
    bt0 = result["base_time_zero"]
    if bt0:
        print(f"  base time-zero: status={bt0['status']} correction_ns={bt0['correction_ns']}")
    hag = result["height_above_ground"]
    if hag.get("n_valid"):
        h = hag["height_above_ground_m"]
        print(f"  height above ground: n_valid={hag['n_valid']}/{hag['n_total']}, "
             f"range={h['range']:.4f} m, std={h['std']:.4f} m")
    else:
        print(f"  height above ground: {hag.get('reason')}")
    topo = result["topographic_correction"]
    print(f"  topographic correction: max_abs={topo.get('max_abs_correction_ns')} ns, "
         f"material={topo.get('material')}")
    print(f"    {topo.get('reason')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=None, help="run exactly one line")
    parser.add_argument("--segy-relpath", default=None)
    parser.add_argument("--dem-site", default=None)
    parser.add_argument("--out", type=Path,
                       default=REPO_ROOT / "artifacts" / "4tu" / "topographic_correction_audit.json")
    args = parser.parse_args()

    if args.segy_relpath is not None:
        try:
            result = run_audit(args.project or "unknown", args.segy_relpath, args.dem_site)
        except AuditError as exc:
            print(f"AUDIT FAILED: {exc}")
            return 1
        _print_summary(result)
    else:
        result = run_audit_all_lines(list(DEFAULT_LINES))
        for key, r in result["per_line"].items():
            if "error" in r:
                print(f"{key}: AUDIT FAILED ({r['error']})")
            else:
                _print_summary(r)
            print()
        print(f"Lines checked: {result['n_lines_checked']}, material: {result['n_lines_material']}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
