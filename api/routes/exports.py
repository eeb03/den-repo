"""
Export API.

Every response carries the payload AND a report naming what was written, what
was skipped and why. A format that cannot honestly represent the data refuses
with a reason rather than emitting a placeholder.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from database.objects_store import load_objects
from exports.exporters import EXPORT_FORMATS, ExportRefused, export_objects
from utils.logger import get_logger
from auth.dependencies import require_dataset_access, require_owned_dataset

logger = get_logger(__name__)
router = APIRouter()


@router.get("/formats")
def formats():
    return {
        "formats": [
            {"value": "json", "requires": "identifiers only",
             "carries_full_provenance": True},
            {"value": "csv", "requires": "identifiers only",
             "carries_full_provenance": True,
             "note": "positions appear in their own kind, with the kind named"},
            {"value": "geojson", "requires": "a geographic position per feature",
             "carries_full_provenance": False,
             "note": "RFC 7946 mandates WGS84; unplaceable features are skipped with "
                     "their reason, never given a null geometry"},
            {"value": "czml", "requires": "a geographic position per feature",
             "carries_full_provenance": False,
             "note": "height is OMITTED (clamp-to-ground) because no dataset has an "
                     "established vertical relationship; 0 would mean sea level"},
            {"value": "3d_tiles", "requires": "an absolute elevation per feature",
             "carries_full_provenance": False,
             "note": "REFUSED for every dataset currently held"},
        ],
        "rule": "nothing is silently dropped: every export reports what it skipped",
    }


@router.get("/{dataset_id}/objects")
def export_dataset_objects(dataset_id: str,
                           fmt: str = Query("json", alias="format"),
    _dataset=Depends(require_dataset_access)):
    if fmt not in EXPORT_FORMATS:
        raise HTTPException(400, f"unknown format {fmt!r}; options: {list(EXPORT_FORMATS)}")
    objects = load_objects(dataset_id)
    if not objects:
        raise HTTPException(404, f"dataset {dataset_id!r} has no resolved objects")
    try:
        payload, report = export_objects(objects, fmt)
    except ExportRefused as e:
        # 409: the request is well-formed, but the data cannot support it.
        raise HTTPException(409, str(e))
    if fmt == "csv":
        return PlainTextResponse(payload, media_type="text/csv", headers={
            "X-Subterra-Written": str(report["written"]),
            "X-Subterra-Skipped": str(len(report["skipped"]))})
    logger.info(f"exports: {dataset_id} as {fmt} -> {report['written']} written, "
                f"{len(report['skipped'])} skipped")
    return {"format": fmt, "payload": payload, "report": report}
