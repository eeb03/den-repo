"""
Exporting Subterra data, without any format being allowed to lie.

EVERY FORMAT DECLARES WHAT IT REQUIRES, and refuses what it cannot honestly
represent:

    csv / json    identifiers only. Always possible, and the only formats that
                  carry the full provenance record.
    geojson       RFC 7946 mandates WGS84, so a projected feature is
                  TRANSFORMED and the transform is recorded per feature. A
                  feature with no geographic position is NOT exported -- it is
                  listed in `skipped` with its reason, because a GeoJSON
                  feature with a null geometry silently becomes a feature at
                  no particular place.
    czml          positions plus optional time. Cesium wants a height; ours is
                  not known, so `height` is omitted and the document says why
                  rather than sending 0, which Cesium would draw at sea level.
    3d_tiles      REFUSED for every dataset currently held. It needs an
                  absolute elevation per feature, and no dataset has an
                  established vertical relationship -- see
                  docs/vertical-reference-site01.md. Emitting Z=0 would
                  fabricate exactly the quantity that investigation showed is
                  missing.

NOTHING IS SILENTLY DROPPED. Every exporter returns (payload, report) where
the report names what was written, what was skipped, and why. A caller that
exports 100 objects and receives 40 features learns which 60 could not be
placed and for what reason.
"""
from __future__ import annotations

import csv as _csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from schemas.provenance import ProvenanceClass
from utils.logger import get_logger

logger = get_logger(__name__)

EXPORT_FORMATS = ("json", "csv", "geojson", "czml", "3d_tiles")


class ExportRefused(ValueError):
    """Raised when a format cannot honestly represent the data."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _geographic(position) -> Optional[tuple[float, float]]:
    return ((position.lat, position.lon)
            if getattr(position, "kind", None) == "geographic" else None)


def _feature_source(obj) -> dict:
    """The identity and provenance fields every format carries where it can."""
    return {
        "id": getattr(obj, "id", None),
        "dataset_id": getattr(obj, "dataset_id", None),
        "status": getattr(getattr(obj, "status", None), "value", None),
        "position_provenance": getattr(
            getattr(obj, "position_provenance", None), "value", None),
        "position_basis": getattr(obj, "position_basis", None),
        "member_count": len(getattr(obj, "members", []) or []),
        "acquisition_count": getattr(obj, "acquisition_count", None),
        "association_ids": getattr(obj, "association_ids", []),
        "attested_by": getattr(obj, "attested_by", []),
    }


def export_json(objects: Iterable, crs_note: str = "") -> tuple[dict, dict]:
    """Full fidelity. Nothing is dropped and nothing is transformed."""
    items = [o.model_dump(mode="json") for o in objects]
    return ({
        "format": "json", "generated_utc": _now(),
        "crs": "each object's position carries its own kind; nothing was transformed",
        "crs_note": crs_note,
        "count": len(items), "objects": items,
    }, {"written": len(items), "skipped": [], "transformed": 0})


def export_csv(objects: Iterable) -> tuple[str, dict]:
    """
    Flat rows. Positions appear in their OWN kind, with the kind named, so a
    reader never mistakes an easting for a longitude.
    """
    rows, skipped = [], []
    for o in objects:
        src = _feature_source(o)
        pos = o.position
        kind = getattr(pos, "kind", "none")
        row = {**src, "position_kind": kind,
               "lat": getattr(pos, "lat", None), "lon": getattr(pos, "lon", None),
               "easting": getattr(pos, "easting", None),
               "northing": getattr(pos, "northing", None),
               "along_track_m": getattr(pos, "along_track_m", None),
               "position_absent_reason": getattr(pos, "reason", None)}
        row["association_ids"] = ";".join(row.get("association_ids") or [])
        row["attested_by"] = ";".join(row.get("attested_by") or [])
        rows.append(row)
    if not rows:
        return "", {"written": 0, "skipped": [], "transformed": 0}
    buf = io.StringIO()
    writer = _csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue(), {"written": len(rows), "skipped": skipped, "transformed": 0}


def export_geojson(objects: Iterable) -> tuple[dict, dict]:
    """
    RFC 7946: coordinates are WGS84 longitude, latitude.

    An object with no geographic position is skipped WITH ITS REASON rather
    than exported with a null geometry, which would read as a feature at no
    particular place.
    """
    features, skipped = [], []
    for o in objects:
        geo = _geographic(o.position)
        if geo is None:
            skipped.append({
                "id": getattr(o, "id", None),
                "position_kind": getattr(o.position, "kind", "none"),
                "reason": (getattr(o.position, "reason", None)
                           or "the object has no geographic position, and GeoJSON "
                              "requires WGS84 coordinates")})
            continue
        lat, lon = geo
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {**_feature_source(o),
                           "coordinate_provenance": ProvenanceClass.DERIVED.value,
                           "coordinate_basis": o.position_basis},
        })
    doc = {
        "type": "FeatureCollection",
        "features": features,
        "crs_note": ("RFC 7946 mandates WGS84 (EPSG:4326); coordinates here are "
                     "derived from the objects' member observations"),
        "generated_utc": _now(),
        "skipped_count": len(skipped),
    }
    return doc, {"written": len(features), "skipped": skipped,
                 "transformed": len(features)}


def export_czml(objects: Iterable, name: str = "Subterra") -> tuple[list, dict]:
    """
    CZML for Cesium.

    `height` is deliberately omitted: no dataset has an established vertical
    relationship, and Cesium interprets a missing height as clamp-to-ground,
    which is honest, whereas 0 would place every object at sea level.
    """
    packets: list[dict[str, Any]] = [{
        "id": "document", "name": name, "version": "1.0",
        "description": ("Subterra export. Heights are OMITTED because no dataset has "
                        "an established vertical relationship; positions are "
                        "clamp-to-ground, not absolute elevations."),
    }]
    skipped = []
    for o in objects:
        geo = _geographic(o.position)
        if geo is None:
            skipped.append({"id": getattr(o, "id", None),
                            "reason": (getattr(o.position, "reason", None)
                                       or "no geographic position")})
            continue
        lat, lon = geo
        packets.append({
            "id": o.id,
            "name": f"{o.status.value}: {o.id}",
            "description": (f"status={o.status.value}; members={len(o.members)}; "
                            f"acquisitions={o.acquisition_count}; "
                            f"position {o.position_basis}"),
            "position": {"cartographicDegrees": [lon, lat, 0.0],
                         "heightReference": "CLAMP_TO_GROUND"},
            "point": {"pixelSize": 10},
            "properties": _feature_source(o),
        })
    return packets, {"written": len(packets) - 1, "skipped": skipped,
                     "transformed": len(packets) - 1}


def export_3d_tiles(objects: Iterable, vertical: Optional[dict] = None):
    """
    Refused unless a vertical relationship exists.

    3D Tiles places geometry in an earth-centred frame, which requires an
    absolute elevation per feature. Every dataset held reports
    `registration_required`, so there is no Z to place them at -- and 0 would
    be a fabrication, not a default.
    """
    if not (vertical or {}).get("absolute_elevation_available"):
        raise ExportRefused(
            "3D Tiles requires an absolute elevation for every feature, and no "
            "dataset currently held has an established vertical relationship: the GPR "
            "depth axis starts at instrument time-zero rather than the ground surface, "
            "and no source declares a vertical datum. Exporting at height 0 would "
            "fabricate the one quantity the vertical investigation established is "
            "missing. See docs/vertical-reference-site01.md. "
            "Supply a vertical registration and this export becomes possible."
        )
    raise ExportRefused(
        "a vertical relationship was supplied, but 3D Tiles tileset generation is not "
        "implemented; the refusal above is the only path exercised by real data today."
    )


def export_objects(objects: list, fmt: str, **kw):
    """Dispatch. Returns (payload, report)."""
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"unknown export format {fmt!r}; options: {list(EXPORT_FORMATS)}")
    if fmt == "json":
        return export_json(objects, **kw)
    if fmt == "csv":
        return export_csv(objects)
    if fmt == "geojson":
        return export_geojson(objects)
    if fmt == "czml":
        return export_czml(objects, **kw)
    return export_3d_tiles(objects, **kw)
