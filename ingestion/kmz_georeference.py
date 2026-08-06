"""
KMZ-based SEG-Y georeferencing -- a FALLBACK for when trace headers carry
no usable position.

CORRECTION (measured 2026-08-06). This module previously stated that the
INGV/UNISA SEG-Y trace headers "carry the SAME static placeholder value on
every single trace in a file -- there is no real per-trace position in the
SEG-Y at all". That is FALSE, and the error mattered: it justified
discarding a real acquisition track.

Reprojecting SourceX/SourceY (UTM zone 33N) to WGS84 and comparing against
each line's own KMZ polyline gives:

    line            distinct hdr positions   hdr len / KMZ len   mean residual
    C1T_7,5_0001            67 / 72 traces        17.42 / 17.43 m       0.74 m
    C1T_7,5_0002            66 / 66 traces        17.89 / 17.89 m       1.22 m

Track lengths agree to ~0.02%, residuals are within GPS accuracy, and the
mean step (0.245 m and 0.275 m per trace) matches the survey's real trace
spacing. The headers ARE a genuine per-trace track, and a finer one than
the KMZ (22 KMZ points describing 72 traces).

Consequently SEG-Y header positions are AUTHORITATIVE where usable, and
this module is the fallback used when they are absent or cannot be turned
into a geographic position. See `verify_kmz_direction` for the direction
check the same comparison makes possible.

The KMZ path remains fully supported: each Placemark's <name> matches the
corresponding SEG-Y file's filename stem exactly (e.g. "C1T_7,5_0001" for
C1T_7,5_0001.SGY).

GPS point count along a line rarely matches trace count (GPS logs at a
coarser rate than GPR fires), so this resamples each KMZ path to exactly
n_traces points by ARC LENGTH (not by index), so trace positions are
evenly distributed along the actual physical path regardless of how
irregularly the raw GPS points were spaced.

Pure stdlib (zipfile + xml.etree) -- deliberately not adding geopandas/
fiona/GDAL as a dependency for what's fundamentally "read some XML and
interpolate a polyline."
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np

KML_NS = "{http://www.opengis.net/kml/2.2}"


def parse_kmz(path: str | Path) -> dict[str, list[tuple[float, float]]]:
    """
    Parses a .kmz file and returns {placemark_name: [(lon, lat), ...]} for
    every LineString placemark found, at any nesting depth (Document/
    Folder/etc). Placemarks without a LineString (e.g. point markers) are
    skipped.
    """
    with zipfile.ZipFile(path) as zf:
        kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
        if not kml_names:
            raise ValueError(f"No .kml file found inside {path}")
        kml_bytes = zf.read(kml_names[0])

    root = ET.fromstring(kml_bytes)
    results: dict[str, list[tuple[float, float]]] = {}

    for placemark in root.iter(f"{KML_NS}Placemark"):
        name_el = placemark.find(f"{KML_NS}name")
        coords_el = placemark.find(f".//{KML_NS}LineString/{KML_NS}coordinates")
        if name_el is None or coords_el is None or not coords_el.text:
            continue
        name = name_el.text.strip()
        coords = []
        for triplet in coords_el.text.strip().split():
            parts = triplet.split(",")
            if len(parts) < 2:
                continue
            lon, lat = float(parts[0]), float(parts[1])
            coords.append((lon, lat))
        if coords:
            results[name] = coords

    return results


def resample_path_by_arc_length(coords: list[tuple[float, float]], n: int) -> np.ndarray:
    """Resamples a polyline to exactly n evenly-spaced (by arc length, not index) points."""
    arr = np.array(coords, dtype=float)
    if len(arr) == 1:
        return np.tile(arr[0], (n, 1))

    deltas = np.diff(arr, axis=0)
    seg_lengths = np.sqrt((deltas**2).sum(axis=1))
    cum_lengths = np.concatenate([[0], np.cumsum(seg_lengths)])
    total_length = cum_lengths[-1]

    if total_length == 0:
        return np.tile(arr[0], (n, 1))

    targets = np.linspace(0, total_length, n)
    resampled = np.zeros((n, 2))
    for i, t in enumerate(targets):
        idx = min(np.searchsorted(cum_lengths, t, side="right") - 1, len(arr) - 2)
        idx = max(idx, 0)
        seg_len = seg_lengths[idx] if seg_lengths[idx] > 0 else 1e-9
        frac = (t - cum_lengths[idx]) / seg_len
        resampled[i] = arr[idx] + frac * (arr[idx + 1] - arr[idx])
    return resampled


def find_matching_kmz_files(extracted_dir: str | Path) -> list[Path]:
    """Finds every .kmz file in an extracted archive (any subdirectory), skipping macOS AppleDouble sidecars."""
    extracted_dir = Path(extracted_dir)
    return sorted(
        p for p in extracted_dir.rglob("*.kmz")
        if p.is_file() and not p.name.startswith("._") and "__MACOSX" not in p.parts
    )


def build_georeference_lookup(kmz_paths: list[Path]) -> dict[str, list[tuple[float, float]]]:
    """Merges placemarks from multiple KMZ files (e.g. one for ground_cart, one for UAV_drone) into one name->path lookup."""
    lookup: dict[str, list[tuple[float, float]]] = {}
    for kmz_path in kmz_paths:
        try:
            parsed = parse_kmz(kmz_path)
            lookup.update(parsed)
        except (ValueError, ET.ParseError, zipfile.BadZipFile):
            continue  # not every kmz necessarily has usable placemarks; skip rather than fail the whole ingest
    return lookup


def georeference_records_by_trace(records: list, path_coords: list[tuple[float, float]]) -> int:
    """
    Assigns real (lat, lon) to `records` from a KMZ acquisition-track
    polyline, per TRACE rather than per record.

    SEGYConverter emits one record per (trace, depth) SAMPLE -- many
    records share the same trace_index (see converters/segy_converter.py)
    -- so the path is resampled to the number of DISTINCT traces (not
    len(records)) and broadcast across every sample belonging to a trace.
    Resampling to len(records) directly would treat vertically-stacked
    depth samples as if they were separate lateral positions.

    UNVERIFIED DIRECTION ASSUMPTION: trace_index is assumed to increase in
    the SAME direction the KMZ placemark's coordinate list is ordered
    (i.e. trace 0 <-> the path's first point, the highest trace index <->
    its last point). Nothing here independently confirms this against a
    known start/end waypoint -- if the KMZ path were recorded in the
    opposite direction from SEG-Y trace acquisition, every trace's
    position would be silently mirrored end-to-end while still passing
    aggregate checks like total line length. Every georeferenced record is
    tagged metadata["kmz_direction_verified"]=False to make this
    assumption visible to downstream consumers rather than leaving it
    undocumented. This does NOT change the mapping itself -- doing so
    would require independent ground truth (e.g. a second known waypoint)
    that isn't available here.

    Mutates `records` in place (sets latitude/longitude and
    metadata["georeferenced_from_kmz"]=True) and returns the number of
    distinct traces that were georeferenced. Records without a
    metadata["trace_index"] are treated as their own single-sample trace
    (index = their position in the list), so this also works for
    converters that emit one record per trace.
    """
    if not records:
        return 0

    trace_indices = [r.metadata.get("trace_index", i) for i, r in enumerate(records)]
    unique_traces = sorted(set(trace_indices))
    resampled = resample_path_by_arc_length(path_coords, len(unique_traces))
    coord_by_trace = dict(zip(unique_traces, resampled))

    for r, t_idx in zip(records, trace_indices):
        lon, lat = coord_by_trace[t_idx]
        r.latitude = float(lat)
        r.longitude = float(lon)
        r.metadata["georeferenced_from_kmz"] = True
        r.metadata["kmz_direction_verified"] = False

    return len(unique_traces)
