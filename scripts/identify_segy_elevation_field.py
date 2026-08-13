"""
Which SEG-Y elevation field holds the author's WGS84 ellipsoidal GNSS height?

    python -m scripts.identify_segy_elevation_field --out artifacts/4tu/elevation_field.json

THE QUESTION. Dr. ter Huurne states that the GNSS-derived elevations in the
exported 4TU SEG-Y files are ellipsoidal heights (WGS84) rather than NAP. The
files carry TWO populated per-trace elevation fields differing by ~42-45 m, and
the author names neither. This asks whether the data can settle it without
another question.

THE TEST. Both candidate fields are compared against AHN -- the Dutch national
terrain model, an INDEPENDENT measurement of the ground surface in NAP. The two
hypotheses make predictions ~44 m apart, so a half-metre-accurate reference is
far more than enough to separate them:

  If bytes 45-48 are the ellipsoidal height, bytes 41-44 are an orthometric
  height and should agree with AHN to within the acquisition's own accuracy.

  If bytes 41-44 are the ellipsoidal height, then the NAP height of the ground
  there is ~44 m LOWER than bytes 41-44 reads -- for the Enschede sites that
  means roughly -15 m, which AHN would flatly contradict.

NO CIRCULARITY. Everything is decoded here from the SEG-Y bytes directly:
`struct.unpack` on the trace headers, not `SubterraRecord.elevation`, which is
one of the candidates under test and could not serve as its own referee. AHN is
a separate national dataset acquired from PDOK with recorded provenance, and it
is not derived from these files.

WHAT THIS CANNOT ESTABLISH. Identifying the surface-elevation field says nothing
about where the GPR depth axis begins. The author is explicit that no time-zero
correction and no air-gap removal were applied, so the ground surface does not
correspond to depth zero. Time-zero offset, propagation velocity and physical
reflector depth remain exactly as blocked as before.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
from collections import defaultdict
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform

CORPUS = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted")
AHN_DIR = Path("datasets/raw/pdok_ahn/dtm_05m")
ACTIVITY_DIR = re.compile(r"/(\d+\.\d+)/")

#: SEG-Y trace-header byte offsets (0-based), per the SEG-Y rev1 layout.
RECEIVER_GROUP_ELEVATION = 40      # bytes 41-44
SOURCE_SURFACE_ELEVATION = 44      # bytes 45-48
SOURCE_X = 72                      # bytes 73-76
SOURCE_Y = 76                      # bytes 77-80
ELEVATION_SCALAR = 68              # bytes 69-70
COORDINATE_SCALAR = 70             # bytes 71-72

#: AHN's own nodata sentinel, and a sanity bound on Dutch terrain. A cell
#: outside this range is a fill value, not a measurement.
NL_TERRAIN_RANGE = (-20.0, 400.0)


def nmea_to_degrees(value: float) -> float:
    """
    IEEE float in NMEA ddmm.mmmm -> decimal degrees.

    The 4TU files store coordinates as IEEE float32 where the SEG-Y standard
    specifies scaled integers; Subterra already handles this under the
    `ieee_nmea` encoding. Decoded here independently rather than reused.
    """
    degrees = int(value // 100)
    return degrees + (value - degrees * 100) / 60.0


def read_trace_headers(path: Path) -> dict | None:
    """
    Decode every trace header in one file, from the bytes.

    Returns None when the file is not the expected little-endian, format-3
    (int16 sample) layout, rather than guessing at a reinterpretation.
    """
    raw = path.read_bytes()
    if len(raw) < 3600 + 240:
        return None

    n_samples = struct.unpack("<h", raw[3220:3222])[0]
    format_code = struct.unpack("<h", raw[3224:3226])[0]
    if n_samples <= 0 or format_code != 3:
        return None

    trace_length = 240 + n_samples * 2
    n_traces = (len(raw) - 3600) // trace_length
    if n_traces < 1:
        return None

    receiver, source, lat, lon = [], [], [], []
    elevation_scalars, coordinate_scalars = set(), set()

    for t in range(n_traces):
        head = raw[3600 + t * trace_length: 3600 + t * trace_length + 240]
        elevation_scalars.add(struct.unpack("<h", head[ELEVATION_SCALAR:ELEVATION_SCALAR + 2])[0])
        coordinate_scalars.add(struct.unpack("<h", head[COORDINATE_SCALAR:COORDINATE_SCALAR + 2])[0])
        receiver.append(struct.unpack("<f", head[RECEIVER_GROUP_ELEVATION:RECEIVER_GROUP_ELEVATION + 4])[0])
        source.append(struct.unpack("<f", head[SOURCE_SURFACE_ELEVATION:SOURCE_SURFACE_ELEVATION + 4])[0])
        lon.append(struct.unpack("<f", head[SOURCE_X:SOURCE_X + 4])[0])
        lat.append(struct.unpack("<f", head[SOURCE_Y:SOURCE_Y + 4])[0])

    return {
        "n_traces": n_traces,
        "n_samples": n_samples,
        "format_code": format_code,
        "receiver_group_elevation": np.array(receiver, dtype=float),
        "source_surface_elevation": np.array(source, dtype=float),
        "latitude": np.array([nmea_to_degrees(v) for v in lat], dtype=float),
        "longitude": np.array([nmea_to_degrees(v) for v in lon], dtype=float),
        "elevation_scalars": sorted(elevation_scalars),
        "coordinate_scalars": sorted(coordinate_scalars),
    }


def site_of(activity: str) -> str:
    """Activity 01.9 belongs to site 01; 010.11 to site 010."""
    return activity.split(".")[0]


def sample_ahn(site: str, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """
    AHN terrain height at each trace, in NAP metres.

    Returns NaN where a trace falls outside the window or on a nodata cell --
    never a substituted value.
    """
    window = AHN_DIR / f"AHN_DTM_05m_site{site}.tif"
    if not window.exists():
        return np.full(len(lat), np.nan)

    with rasterio.open(window) as ds:
        xs, ys = transform("EPSG:4326", ds.crs.to_string(), lon.tolist(), lat.tolist())
        out = np.full(len(lat), np.nan)
        for i, value in enumerate(ds.sample(list(zip(xs, ys)), indexes=1)):
            v = float(value[0])
            if ds.nodata is not None and v == ds.nodata:
                continue
            if NL_TERRAIN_RANGE[0] <= v <= NL_TERRAIN_RANGE[1]:
                out[i] = v
    return out


def statistics(residual: np.ndarray) -> dict:
    finite = residual[np.isfinite(residual)]
    if not len(finite):
        return {"n": 0}
    return {
        "n": int(len(finite)),
        "mean": float(np.mean(finite)),
        "median": float(np.median(finite)),
        "sd": float(np.std(finite)),
        "rmse": float(np.sqrt(np.mean(finite ** 2))),
        "mae": float(np.mean(np.abs(finite))),
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "p05": float(np.percentile(finite, 5)),
        "p50": float(np.percentile(finite, 50)),
        "p95": float(np.percentile(finite, 95)),
    }


#: Published NL geoid separation, for comparison with what is measured here.
#: Recorded with provenance because it is an EXTERNAL claim, not a Subterra
#: measurement, and the whole point of this script is to keep those apart.
PUBLISHED_GEOID_SEPARATION = {
    "claim": ("in the Netherlands the geoid separation has values between 41 m "
              "in Groningen (north) and 47 m in Limburg (south)"),
    "worked_example": ("Amsterdam Dam square: 2.68 m NAP corresponds to 45.6 m "
                       "ellipsoidal, i.e. a separation of 42.92 m"),
    "source": "bertt.wordpress.com, 'Vertical Coordinate Reprojection: From Geoid to Ellipsoid' (2023-08-24)",
    "retrieved": "2026-08-13",
    "corroborating": ("EPSG:7001 ETRS89-to-NAP height, accuracy 0.01 m, extent "
                      "50.75-53.7N / 3.2-7.22E -- which contains every site here "
                      "(epsg.io/7001, retrieved 2026-08-13)"),
    "status": "EXTERNAL REFERENCE -- not verified by Subterra against a geoid grid",
}


def spatial_behaviour(per_activity: list[dict], centroids: dict[str, tuple]) -> dict:
    """
    Does the field difference behave like a geoid, or like an instrument offset?

    A geoid separation is a smooth, large-scale function of position. An antenna
    height, a fixed software constant or a source/receiver geometry term would
    be CONSTANT. Fitting a plane in (latitude, longitude) separates them: a high
    R^2 with a small residual means the offset is spatial, not instrumental.
    """
    by_site: dict[str, list[float]] = defaultdict(list)
    for a in per_activity:
        if a.get("matched_to_ahn"):
            by_site[a["site"]].append(a["source_minus_receiver_mean"])

    rows = [(s, centroids[s][0], centroids[s][1], float(np.mean(v)))
            for s, v in by_site.items() if s in centroids]
    if len(rows) < 4:
        return {"available": False, "reason": "too few sites with centroids"}

    rows.sort(key=lambda r: r[1])
    lat = np.array([r[1] for r in rows])
    lon = np.array([r[2] for r in rows])
    offset = np.array([r[3] for r in rows])

    design = np.column_stack([lat, lon, np.ones(len(lat))])
    coefficients, *_ = np.linalg.lstsq(design, offset, rcond=None)
    predicted = design @ coefficients
    residual = offset - predicted

    # A CONSTANT OFFSET HAS NO SPATIAL VARIATION TO EXPLAIN, so R^2 is undefined
    # rather than zero or NaN -- and a constant is exactly what an antenna height
    # or a fixed software convention would look like. Reported as `null` with the
    # verdict spelled out, so the absence of spatial structure is a finding and
    # not a division artefact.
    total_variance = float(np.var(offset))
    r_squared = (None if total_variance == 0.0
                 else float(1 - np.var(residual) / total_variance))

    return {
        "available": True,
        "n_sites": len(rows),
        "per_site": [{"site": r[0], "lat": r[1], "lon": r[2], "offset_m": r[3]}
                     for r in rows],
        "offset_range_m": [float(offset.min()), float(offset.max())],
        "offset_spread_m": float(offset.max() - offset.min()),
        "correlation_with_latitude": (
            None if total_variance == 0.0 else float(np.corrcoef(lat, offset)[0, 1])),
        "correlation_with_longitude": (
            None if total_variance == 0.0 else float(np.corrcoef(lon, offset)[0, 1])),
        "planar_fit": {"per_degree_latitude": float(coefficients[0]),
                       "per_degree_longitude": float(coefficients[1]),
                       "intercept": float(coefficients[2])},
        "residual_sd_about_plane_m": float(np.std(residual)),
        "r_squared": r_squared,
        "varies_spatially": total_variance > 0.0,
        "note_if_constant": ("a constant offset is what an antenna height or a "
                             "fixed software convention looks like, and is NOT "
                             "how a geoid separation behaves"),
        "published_reference": PUBLISHED_GEOID_SEPARATION,
    }


def site_centroids(by_activity: dict[str, list[Path]]) -> dict[str, tuple]:
    """One representative coordinate per site, from the SEG-Y headers."""
    out: dict[str, tuple] = {}
    for activity in sorted(by_activity):
        site = site_of(activity)
        if site in out:
            continue
        for path in by_activity[activity]:
            headers = read_trace_headers(path)
            if headers is not None:
                out[site] = (float(np.mean(headers["latitude"])),
                             float(np.mean(headers["longitude"])))
                break
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", type=Path, default=CORPUS)
    p.add_argument("--out", type=Path, default=Path("artifacts/4tu/elevation_field.json"))
    args = p.parse_args()

    by_activity: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(args.corpus.rglob("*.sgy")):
        match = ACTIVITY_DIR.search(str(path))
        if match:
            by_activity[match.group(1)].append(path)

    per_activity = []
    all_receiver, all_source, all_difference = [], [], []
    skipped = []

    for activity in sorted(by_activity):
        site = site_of(activity)
        recv_res, src_res, diffs = [], [], []
        traces = matched = 0

        for path in by_activity[activity]:
            headers = read_trace_headers(path)
            if headers is None:
                skipped.append({"file": str(path), "reason": "not little-endian format-3 SEG-Y"})
                continue
            traces += headers["n_traces"]

            receiver = headers["receiver_group_elevation"]
            source = headers["source_surface_elevation"]
            usable = np.isfinite(receiver) & np.isfinite(source) & (receiver != 0) & (source != 0)
            if not usable.any():
                continue

            ahn = sample_ahn(site, headers["latitude"][usable], headers["longitude"][usable])
            ok = np.isfinite(ahn)
            matched += int(ok.sum())
            if ok.any():
                recv_res.append(receiver[usable][ok] - ahn[ok])
                src_res.append(source[usable][ok] - ahn[ok])
            diffs.append(source[usable] - receiver[usable])

        if not recv_res:
            per_activity.append({"activity": activity, "site": site, "traces": traces,
                                 "matched_to_ahn": 0,
                                 "note": "no trace fell on a valid AHN cell"})
            continue

        recv_res = np.concatenate(recv_res)
        src_res = np.concatenate(src_res)
        diff = np.concatenate(diffs)
        all_receiver.append(recv_res)
        all_source.append(src_res)
        all_difference.append(diff)

        per_activity.append({
            "activity": activity, "site": site, "traces": traces,
            "matched_to_ahn": matched,
            "receiver_minus_ahn": statistics(recv_res),
            "source_minus_ahn": statistics(src_res),
            "source_minus_receiver_mean": float(np.mean(diff)),
            "source_minus_receiver_sd": float(np.std(diff)),
        })

    report = {
        "question": ("which SEG-Y trace-header field holds the WGS84 ellipsoidal "
                     "GNSS elevation Dr. ter Huurne describes"),
        "independent_reference": {
            "product": "Actueel Hoogtebestand Nederland (AHN), DTM 0.5 m",
            "source": "PDOK (Dutch national geodata portal)",
            "horizontal_crs": "EPSG:28992 (declared in the file)",
            "vertical_datum": "NAP -- orthometric. Documented by PDOK, NOT declared in the GeoTIFF",
            "quantity": "ground-classified terrain surface height",
            "why_it_is_independent": ("a separate national dataset, not derived from "
                                      "the 4TU SEG-Y files"),
            "local_provenance": str(AHN_DIR / "PROVENANCE_site<NN>.json"),
        },
        "decoding": {
            "source": "struct.unpack on the raw trace headers in this script",
            "not_used": ("SubterraRecord.elevation -- it is derived from one of the "
                         "candidate fields and cannot referee between them"),
            "receiver_group_elevation_bytes": "41-44",
            "source_surface_elevation_bytes": "45-48",
            "coordinates": "bytes 73-76 / 77-80 as IEEE float32 in NMEA ddmm.mmmm",
        },
        "activities_examined": len(per_activity),
        "activities_matched": sum(1 for a in per_activity if a.get("matched_to_ahn")),
        "skipped_files": skipped[:20],
        "overall": {
            "receiver_minus_ahn": statistics(np.concatenate(all_receiver)) if all_receiver else {"n": 0},
            "source_minus_ahn": statistics(np.concatenate(all_source)) if all_source else {"n": 0},
            "source_minus_receiver": statistics(np.concatenate(all_difference)) if all_difference else {"n": 0},
        },
        "spatial_behaviour_of_the_difference": spatial_behaviour(
            per_activity, site_centroids(by_activity)),
        "per_activity": per_activity,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")

    o = report["overall"]
    print(f"activities examined {report['activities_examined']}, "
          f"matched to AHN {report['activities_matched']}")
    for name in ("receiver_minus_ahn", "source_minus_ahn"):
        s = o[name]
        if s["n"]:
            print(f"  {name:<22} n={s['n']:>7}  mean={s['mean']:>9.3f}  median={s['median']:>9.3f}  "
                  f"sd={s['sd']:>7.3f}  rmse={s['rmse']:>9.3f}")
    d = o["source_minus_receiver"]
    if d["n"]:
        print(f"  {'source-receiver':<22} n={d['n']:>7}  mean={d['mean']:>9.3f}  "
              f"min={d['min']:.3f}  max={d['max']:.3f}")
    sb = report["spatial_behaviour_of_the_difference"]
    if sb.get("available"):
        print(f"  difference across {sb['n_sites']} sites: "
              f"{sb['offset_range_m'][0]:.3f}-{sb['offset_range_m'][1]:.3f} m")
        print(f"    correlation with latitude {sb['correlation_with_latitude']:+.3f}, "
              f"planar R^2 {sb['r_squared']:.3f}, "
              f"residual sd {sb['residual_sd_about_plane_m']:.3f} m")
    print(f"  -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
