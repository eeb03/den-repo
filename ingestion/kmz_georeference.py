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
from dataclasses import dataclass
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


@dataclass
class DirectionVerification:
    """
    Result of checking a KMZ track's ordering against an independent
    per-trace position source.

    Scoped deliberately: `applies_to` names the ONE acquisition line this
    was measured on. A favourable result here says nothing about any other
    dataset -- different acquisition software may well write its KMZ in the
    opposite order -- so nothing in this module generalises it.
    """
    verified: bool
    applies_to: str
    method: str
    residual_as_recorded_m: float
    residual_reversed_m: float
    n_traces: int

    @property
    def improvement_ratio(self) -> float:
        """How much better the as-recorded ordering fits. >1 favours as-recorded."""
        if self.residual_as_recorded_m == 0:
            return float("inf")
        return self.residual_reversed_m / self.residual_as_recorded_m

    def as_dict(self) -> dict:
        return {
            "verified": self.verified, "applies_to": self.applies_to,
            "method": self.method, "n_traces": self.n_traces,
            "residual_as_recorded_m": round(self.residual_as_recorded_m, 4),
            "residual_reversed_m": round(self.residual_reversed_m, 4),
            "improvement_ratio": round(self.improvement_ratio, 3),
        }


def verify_kmz_direction(
    reference_lonlat: list[tuple[float, float]],
    path_coords: list[tuple[float, float]],
    applies_to: str,
    min_improvement_ratio: float = 2.0,
) -> DirectionVerification:
    """
    Checks a KMZ track's ordering against an INDEPENDENT per-trace position
    source (`reference_lonlat`, one (lon, lat) per trace, in trace order --
    e.g. reprojected SEG-Y header coordinates).

    Replaces the hardcoded `kmz_direction_verified=False`: direction is now
    something measured when a second source exists, rather than an
    assumption that could never be falsified. Resamples the KMZ path both
    as-recorded and reversed, and reports the mean residual for each.

    Verified only when as-recorded fits at least `min_improvement_ratio`
    times better -- a marginal difference means the two orderings are not
    distinguishable and the honest answer stays "unverified".
    """
    from fusion.sensor_fusion import haversine_m

    n = len(reference_lonlat)
    if n < 2 or len(path_coords) < 2:
        return DirectionVerification(
            verified=False, applies_to=applies_to,
            method="insufficient points to compare", n_traces=n,
            residual_as_recorded_m=float("nan"), residual_reversed_m=float("nan"),
        )

    def mean_residual(ordered):
        resampled = resample_path_by_arc_length(ordered, n)
        return float(np.mean([
            haversine_m(reference_lonlat[i][1], reference_lonlat[i][0],
                        resampled[i][1], resampled[i][0])
            for i in range(n)
        ]))

    forward = mean_residual(path_coords)
    reverse = mean_residual(path_coords[::-1])
    verified = reverse > forward * min_improvement_ratio

    return DirectionVerification(
        verified=verified, applies_to=applies_to,
        method=(
            "mean haversine residual between per-trace reference positions and the "
            f"arc-length-resampled KMZ path, both orderings; verified when as-recorded "
            f"fits >{min_improvement_ratio}x better"
        ),
        residual_as_recorded_m=forward, residual_reversed_m=reverse, n_traces=n,
    )


def records_needing_kmz_fallback(records: list) -> bool:
    """
    True when the KMZ path should supply positions for these records.

    SEG-Y header positions are authoritative where usable (see this module's
    docstring). KMZ is the fallback for the case the headers cannot cover:
    no position at all, or a projected position with no declared CRS, which
    cannot be turned into the latitude/longitude the schema still requires.

    A record whose header already gives a GEOGRAPHIC position needs nothing
    from the KMZ and must not be overwritten by it.
    """
    if not records:
        return False

    def header_supplied_a_geographic_view(r) -> bool:
        pos = getattr(r, "position", None)
        if pos is not None and pos.kind == "geographic":
            return True
        # A projected header position becomes usable once a CRS is declared:
        # latitude/longitude are then DERIVED from it and must not be replaced.
        return (r.metadata.get("position_source") == "segy_header"
                and r.latitude is not None and r.longitude is not None)

    return not any(header_supplied_a_geographic_view(r) for r in records)


def georeference_records_by_trace(
    records: list,
    path_coords: list[tuple[float, float]],
    direction: "DirectionVerification | None" = None,
) -> int:
    """
    Assigns real (lat, lon) to `records` from a KMZ acquisition-track
    polyline, per TRACE rather than per record.

    SEGYConverter emits one record per (trace, depth) SAMPLE -- many
    records share the same trace_index (see converters/segy_converter.py)
    -- so the path is resampled to the number of DISTINCT traces (not
    len(records)) and broadcast across every sample belonging to a trace.
    Resampling to len(records) directly would treat vertically-stacked
    depth samples as if they were separate lateral positions.

    DIRECTION. trace_index is assumed to increase in the SAME direction the
    KMZ placemark's coordinate list is ordered (trace 0 <-> the path's first
    point). If the KMZ were recorded in the opposite direction, every
    trace's position would be silently mirrored end-to-end while still
    passing aggregate checks like total line length.

    Pass `direction` (from `verify_kmz_direction`) when an independent
    per-trace position source exists, and that measured result is recorded
    per record. Without it the assumption remains unverified and is tagged
    as such -- the previous behaviour, which is still correct whenever
    nothing is available to check against.

    Mutates `records` in place (sets latitude/longitude,
    metadata["georeferenced_from_kmz"]=True, metadata["position_source"]
    ="kmz_fallback") and returns the number of distinct traces that were
    georeferenced. Records without a metadata["trace_index"] are treated as
    their own single-sample trace (index = their position in the list), so
    this also works for converters that emit one record per trace.

    Sets `record.position` to a GeographicPosition as well as the legacy
    latitude/longitude, because a KMZ track IS a real geographic position
    and `position` is the platform's single source of spatial truth. The
    file's own header coordinates are not lost: SEGYConverter keeps them in
    metadata["segy_x"]/["segy_y"]. This fallback only runs when the headers
    could not yield a geographic position in the first place -- see
    `records_needing_kmz_fallback`.
    """
    if not records:
        return 0

    trace_indices = [r.metadata.get("trace_index", i) for i, r in enumerate(records)]
    unique_traces = sorted(set(trace_indices))
    resampled = resample_path_by_arc_length(path_coords, len(unique_traces))
    coord_by_trace = dict(zip(unique_traces, resampled))

    from schemas.spatial import GeographicPosition

    for r, t_idx in zip(records, trace_indices):
        lon, lat = coord_by_trace[t_idx]
        r.latitude = float(lat)
        r.longitude = float(lon)
        r.position = GeographicPosition(lat=float(lat), lon=float(lon))
        r.metadata["georeferenced_from_kmz"] = True
        r.metadata["position_source"] = "kmz_fallback"
        r.metadata["kmz_direction_verified"] = bool(direction.verified) if direction else False
        if direction is not None:
            r.metadata["kmz_direction_verification"] = direction.as_dict()

    return len(unique_traces)
