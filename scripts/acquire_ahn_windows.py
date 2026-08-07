"""
Acquire the AHN surface window for each 4TU GPR site.

ONE MECHANISM FOR ALL SITES. Site 01 was first acquired by hand; this script
reproduces that acquisition and the other twelve identically, so every window
on disk comes from the same code path and the same provenance rules.

WHAT IT DOES NOT DO. It does not decide that AHN and a GPR line are related
because both are Dutch. For each site it MEASURES the GPR extent from real
SEG-Y trace headers, transforms it into EPSG:28992, and asks the official
PDOK tile index which tiles actually cover it. A site whose index lookup
returns nothing is reported and skipped, never approximated.

It also asserts nothing vertical. The windows carry elevations whose datum
the GeoTIFF does not declare; see docs/vertical-reference-site01.md and
fusion/vertical_reference.py for why that stays undeclared.

MINIMUM BYTES. The tiles are Cloud Optimized GeoTIFFs, so only the blocks
overlapping each window are transferred, against source tiles of 300-475 MB
each. Three sites (01, 02, 010) straddle a tile boundary at the buffer
distance, so the window is assembled from every covering tile; the same path
runs for single-tile sites too, so there is one code path rather than two.

    python -m scripts.acquire_ahn_windows            # report only
    python -m scripts.acquire_ahn_windows --apply
    python -m scripts.acquire_ahn_windows --apply --sites 03 04
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)

GPR_ROOT = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted")
OUT_DIR = Path("datasets/raw/pdok_ahn/dtm_05m")
INDEX_URL = ("https://service.pdok.nl/rws/actueel-hoogtebestand-nederland/atom/"
             "downloads/dtm_05m/kaartbladindex.json")
ATOM_FEED = "https://service.pdok.nl/rws/ahn/atom/dtm_05m.xml"
PRODUCT_PAGE = "https://www.pdok.nl/introductie/-/article/actueel-hoogtebestand-nederland-ahn"

#: Metres of AHN kept around the measured GPR extent. Enough context for a
#: surface/subsurface comparison without pulling a whole tile.
BUFFER_M = 50.0

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128.0.0.0"


def _nmea(value: float) -> float:
    """NMEA ddmm.mmmm -> decimal degrees (the 4TU vendor coordinate encoding)."""
    degrees = int(abs(value) // 100)
    out = degrees + (abs(value) - 100 * degrees) / 60.0
    return -out if value < 0 else out


def gpr_extents() -> dict[str, dict]:
    """
    Measured WGS84 extent of every 4TU site, from the SEG-Y trace headers.

    Read directly rather than through SEGYConverter: this needs two floats per
    trace, and building millions of records to obtain them would take hours.
    The header layout is the one the converter validated across all 759 files.
    """
    sites: dict[str, list] = defaultdict(list)
    for path in sorted(GPR_ROOT.glob("*/**/*.sgy")):
        site = path.relative_to(GPR_ROOT).parts[0]
        raw = path.read_bytes()
        n_samples = struct.unpack_from("<h", raw, 3200 + 20)[0]
        record = 240 + n_samples * 2
        body = len(raw) - 3600
        if record <= 0 or body % record:
            logger.warning(f"{path.name}: unexpected geometry; skipped")
            continue
        for i in range(body // record):
            head = raw[3600 + i * record: 3600 + i * record + 240]
            x = struct.unpack_from("<f", head, 72)[0]
            y = struct.unpack_from("<f", head, 76)[0]
            if not (math.isfinite(x) and math.isfinite(y)) or x == 0 or y == 0:
                continue
            sites[site].append((_nmea(y), _nmea(x)))
    return {s: {"points": p} for s, p in sites.items() if p}


def to_rd(points):
    from rasterio.warp import transform
    xs, ys = transform("EPSG:4326", "EPSG:28992",
                       [p[1] for p in points], [p[0] for p in points])
    return min(xs), max(xs), min(ys), max(ys)


def load_index(cache: Path) -> list[tuple[dict, tuple]]:
    """The official tile index, cached locally after the first fetch."""
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(INDEX_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            cache.write_bytes(r.read())
        logger.info(f"downloaded tile index -> {cache}")
    data = json.loads(cache.read_text())

    def bounds(geom):
        xs, ys = [], []

        def walk(c):
            if isinstance(c[0], (int, float)):
                xs.append(c[0])
                ys.append(c[1])
            else:
                for k in c:
                    walk(k)
        walk(geom["coordinates"])
        return min(xs), max(xs), min(ys), max(ys)

    return [(f["properties"], bounds(f["geometry"])) for f in data["features"]]


def covering_tiles(index, window) -> list[dict]:
    wx0, wx1, wy0, wy1 = window
    return [p for p, b in index
            if not (b[1] < wx0 or b[0] > wx1 or b[3] < wy0 or b[2] > wy1)]


def acquire(site: str, window, tiles, out_path: Path) -> dict:
    """
    Reads the window out of every covering tile and pastes them into one grid.

    Deliberately explicit rather than `rasterio.merge.merge`: merge cannot
    represent AHN's nodata (float max) in float32, warns, falls back, and
    silently emits an all-zero raster. All AHN tiles share the same 0.5 m grid
    aligned to RD New, so the destination offsets are exact integers and a
    direct paste is both simpler and verifiable.
    """
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.windows import from_bounds

    wx0, wx1, wy0, wy1 = window
    handles = [rasterio.open(f"/vsicurl/{t['url']}") for t in tiles]
    try:
        crs, res = handles[0].crs, handles[0].res
        nodata = handles[0].nodata
        for h in handles[1:]:
            if h.crs != crs:
                raise ValueError(
                    f"site {site}: covering tiles disagree on CRS ({crs} vs {h.crs}); "
                    f"refusing to mosaic across reference systems")
            if h.res != res:
                raise ValueError(
                    f"site {site}: covering tiles disagree on resolution "
                    f"({res} vs {h.res}); refusing to mosaic across grids")
        rx, ry = res
        # Snap the destination to the shared grid so every paste is integral.
        left = math.floor(wx0 / rx) * rx
        top = math.ceil(wy1 / ry) * ry
        width = int(math.ceil((wx1 - left) / rx))
        height = int(math.ceil((top - wy0) / ry))
        dest = np.full((height, width), nodata, dtype="float32")
        transform_ = from_origin(left, top, rx, ry)

        for h in handles:
            b = h.bounds
            ix0, ix1 = max(left, b.left), min(left + width * rx, b.right)
            iy0, iy1 = max(top - height * ry, b.bottom), min(top, b.top)
            if ix0 >= ix1 or iy0 >= iy1:
                continue
            win = from_bounds(ix0, iy0, ix1, iy1, h.transform).round_offsets().round_lengths()
            chunk = h.read(1, window=win)
            col = int(round((ix0 - left) / rx))
            row = int(round((top - iy1) / ry))
            dest[row:row + chunk.shape[0], col:col + chunk.shape[1]] = chunk
        profile = handles[0].profile.copy()
    finally:
        for h in handles:
            h.close()
    data = dest[np.newaxis, :, :]
    profile.update(height=data.shape[1], width=data.shape[2], transform=transform_,
                   driver="GTiff", tiled=True, compress="deflate", count=1,
                   nodata=nodata)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(data[0], 1)

    with rasterio.open(out_path) as ds:
        band = ds.read(1, masked=True)
        return {
            "crs": str(ds.crs), "epsg": ds.crs.to_epsg(),
            "width": ds.width, "height": ds.height, "res": list(ds.res),
            "bounds_rd": list(ds.bounds), "dtype": ds.dtypes[0], "nodata": nodata,
            "valid_cells": int(band.count()), "total_cells": int(band.size),
            "elevation_min": float(band.min()) if band.count() else None,
            "elevation_max": float(band.max()) if band.count() else None,
        }


def provenance(site, gpr_rd, window, tiles, stats, out_path) -> dict:
    return {
        "repository": "PDOK (Publieke Dienstverlening Op de Kaart) / Rijkswaterstaat",
        "product": "Actueel Hoogtebestand Nederland (AHN) - Digital Terrain Model (DTM) 0,5m",
        "product_variant": "Kaartbladen - EPSG:28992 - Cloud Optimized GeoTIFF (COG)",
        "surface_type": ("terrain/ground (maaiveld): only points classified as ground, "
                         "resampled by Squared IDW; trees, buildings, bridges and water "
                         "excluded. No further processing."),
        "official_source": PRODUCT_PAGE,
        "atom_feed": ATOM_FEED,
        "tile_index": INDEX_URL,
        "license": "CC0-1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/deed.nl",
        "license_source": "<rights> element of the PDOK ATOM feed dtm_05m.xml",
        "crs": {
            "code": f"EPSG:{stats['epsg']}", "name": "Amersfoort / RD New",
            "provenance": "declared_by_source",
            "declared_in": ["the COG file", "the ATOM feed <category>", "the tile index"],
            "inferred": False,
        },
        "vertical_metadata": {
            "vertical_crs_in_file": None,
            "band_units_in_file": None,
            "documented_datum": "NAP (Normaal Amsterdams Peil)",
            "documented_datum_source": "PDOK product documentation, NOT the GeoTIFF",
            "acquisition_epoch": "NOT STATED in the feed, the tile index or the file",
            "note": ("the raster declares no vertical CRS, band unit or band description. "
                     "Elevations are therefore carried without a declared datum; see "
                     "docs/vertical-reference-site01.md. No relationship to GPR depth is "
                     "asserted here."),
        },
        "resolution_m": stats["res"][0],
        "band_dtype": stats["dtype"], "nodata": stats["nodata"],
        "raster_shape": [stats["width"], stats["height"]],
        "spatial_extent_rd_epsg28992": {"x": [stats["bounds_rd"][0], stats["bounds_rd"][2]],
                                        "y": [stats["bounds_rd"][1], stats["bounds_rd"][3]]},
        "elevation_range_m": [stats["elevation_min"], stats["elevation_max"]],
        "elevation_datum": "UNDECLARED",
        "valid_cells": stats["valid_cells"], "total_cells": stats["total_cells"],
        "source_tiles": [{"kaartblad": t["kaartbladNr"], "url": t["url"],
                          "full_tile_bytes": int(t["length"])} for t in tiles],
        "retrieval_method": ("windowed read of Cloud Optimized GeoTIFFs over HTTP via GDAL "
                             "/vsicurl (range requests), mosaicked across covering tiles. "
                             "The full tiles were never downloaded."),
        "subset_rationale": (
            f"the measured extent of 4TU GPR site {site} plus a {BUFFER_M:.0f} m buffer. "
            f"Compatibility was established from declared CRS and measured extent, not from "
            f"both datasets being Dutch: the GPR extent was computed from real SEG-Y trace "
            f"headers, transformed to EPSG:28992, and matched against the official tile index."),
        "matched_gpr_site": {
            "dataset": "4tu-nl-utility", "site": site,
            "gpr_extent_rd_epsg28992": {"x": [gpr_rd[0], gpr_rd[1]],
                                        "y": [gpr_rd[2], gpr_rd[3]]},
            "window_rd": {"x": [window[0], window[1]], "y": [window[2], window[3]]},
        },
        "local_file": out_path.name,
        "local_bytes": out_path.stat().st_size,
        "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest(),
        "acquired_utc": datetime.now(timezone.utc).isoformat(),
        "acquired_by": "scripts/acquire_ahn_windows.py",
        "unknowns": [
            "the vertical datum of these elevations is not declared by the file",
            "the AHN acquisition epoch is not published with the product, so terrain change "
            "between the AHN flight and the GPR survey cannot be assessed",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="download (default: report only)")
    parser.add_argument("--sites", nargs="*", help="restrict to these site ids")
    parser.add_argument("--index-cache", default="datasets/metadata/ahn_kaartbladindex.json")
    args = parser.parse_args()

    index = load_index(Path(args.index_cache))
    extents = gpr_extents()
    wanted = sorted(extents) if not args.sites else [s for s in sorted(extents)
                                                     if s in set(args.sites)]
    mode = "ACQUIRING" if args.apply else "DRY RUN (pass --apply to download)"
    print(f"\nAHN window acquisition -- {mode}")
    print(f"  sites with measured GPR positions: {len(extents)}")

    total = 0
    for site in wanted:
        rd = to_rd(extents[site]["points"])
        window = (rd[0] - BUFFER_M, rd[1] + BUFFER_M, rd[2] - BUFFER_M, rd[3] + BUFFER_M)
        tiles = covering_tiles(index, window)
        out = OUT_DIR / f"AHN_DTM_05m_site{site}.tif"
        names = ",".join(t["kaartbladNr"] for t in tiles) or "NONE"
        if not tiles:
            print(f"  {site:<4} NO COVERING TILE -- skipped (extent RD "
                  f"X {rd[0]:.0f}..{rd[1]:.0f} Y {rd[2]:.0f}..{rd[3]:.0f})")
            continue
        if not args.apply:
            print(f"  {site:<4} would acquire {out.name:<28} from {names}")
            continue
        stats = acquire(site, window, tiles, out)
        rec = provenance(site, rd, window, tiles, stats, out)
        (OUT_DIR / f"PROVENANCE_site{site}.json").write_text(
            json.dumps(rec, indent=2, ensure_ascii=False))
        total += rec["local_bytes"]
        print(f"  {site:<4} {out.name:<28} {rec['local_bytes']:>9,} B  "
              f"{stats['width']}x{stats['height']}  EPSG:{stats['epsg']}  "
              f"{stats['elevation_min']:.2f}..{stats['elevation_max']:.2f} m  [{names}]")
    if args.apply:
        print(f"\n  total downloaded: {total:,} bytes across {len(wanted)} site(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
