"""
Cross-sensor overlay API.

Serves a viewer the information it needs to draw several sensors together
WITHOUT having reprojected anything: each layer arrives in its own CRS, with
its own provenance and its own unknowns, plus a clearly-labelled derived
extent so the client can place it on a map.

The composition endpoint states how the layers relate -- co-registered,
disjoint, or not relatable at all -- and never upgrades that judgement beyond
what the CRS declarations and extents support.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from database.frames_store import load_frames, synthesize_frames_from_records
from database.records_store import load_records
from schemas.overlays import build_layer, compose
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

#: Positions are constant per trace, so an extent does not need every record.
#: Sampling keeps a 7-million-record line from being walked to find four numbers.
_EXTENT_SAMPLE = 20_000


class CompositionRequest(BaseModel):
    datasets: list[str] = Field(..., min_length=1)
    frame_ids: Optional[list[str]] = None
    #: Optional pair for the vertical question, which horizontal overlap
    #: cannot answer.
    subsurface_frame_id: Optional[str] = None
    surface_frame_id: Optional[str] = None


def _frames_and_records(dataset_id: str):
    records = load_records(dataset_id)
    if not records:
        raise HTTPException(404, f"dataset {dataset_id!r} has no records")
    frames = load_frames(dataset_id) or synthesize_frames_from_records(records)
    by_frame: dict[str, list] = {}
    for r in records:
        by_frame.setdefault(r.frame_id, []).append(r)
    return frames, by_frame


@router.get("/vocabulary")
def vocabulary():
    """The relationships a client must be able to render, and what each means."""
    return {
        "spatial_relationships": [
            {"value": "co_registered",
             "meaning": "every layer is placeable and their extents overlap; "
                        "they describe the same ground",
             "safe_to_draw_together": True},
            {"value": "disjoint",
             "meaning": "every layer is placeable but the extents do not meet; "
                        "drawing them on one map is fine, expecting alignment is not",
             "safe_to_draw_together": True},
            {"value": "not_relatable",
             "meaning": "at least one layer cannot be placed on Earth (odometry, a "
                        "local grid, or a projected layer with no declared CRS); this "
                        "needs a declaration or a tie, not more processing",
             "safe_to_draw_together": False},
        ],
        "rules": [
            "each layer keeps its NATIVE CRS; nothing is flattened server-side",
            "a wgs84 extent is a RENDER HINT and is always marked derived",
            "an unplaceable layer must be rendered as unplaced, never at a default "
            "coordinate",
            "horizontal agreement says nothing about depth; the vertical relationship "
            "is reported separately and is usually registration_required",
        ],
    }


@router.get("/{dataset_id}/layers")
def dataset_layers(dataset_id: str, frame_id: Optional[str] = Query(None)):
    """Every survey frame in a dataset, described as an overlay layer."""
    frames, by_frame = _frames_and_records(dataset_id)
    if frame_id:
        frames = [f for f in frames if f.frame_id == frame_id]
        if not frames:
            raise HTTPException(404, f"no frame {frame_id!r} in {dataset_id!r}")
    layers = [build_layer(f, by_frame.get(f.frame_id, [])[:_EXTENT_SAMPLE])
              for f in frames]
    return {
        "dataset_id": dataset_id,
        "layer_count": len(layers),
        "layers": [l.model_dump(mode="json") for l in layers],
        "note": ("extents are computed from a sample of positions; positions are "
                 "constant per trace so the extent is exact for the sampled traces"),
    }


@router.post("/compose")
def compose_layers(body: CompositionRequest):
    """
    Describes how layers from several datasets relate.

    Nothing is reprojected into a shared frame: the answer is a STATEMENT
    about the layers, and each layer is returned in its own coordinates.
    """
    layers, frames_by_id = [], {}
    for ds in body.datasets:
        frames, by_frame = _frames_and_records(ds)
        for f in frames:
            if body.frame_ids and f.frame_id not in body.frame_ids:
                continue
            frames_by_id[f.frame_id] = f
            layers.append(build_layer(f, by_frame.get(f.frame_id, [])[:_EXTENT_SAMPLE]))
    if not layers:
        raise HTTPException(404, "no frames matched the request")

    sub = frames_by_id.get(body.subsurface_frame_id) if body.subsurface_frame_id else None
    sur = frames_by_id.get(body.surface_frame_id) if body.surface_frame_id else None
    if body.subsurface_frame_id and sub is None:
        raise HTTPException(404, f"no frame {body.subsurface_frame_id!r}")
    if body.surface_frame_id and sur is None:
        raise HTTPException(404, f"no frame {body.surface_frame_id!r}")

    comp = compose(layers, subsurface_frame=sub, surface_frame=sur)
    logger.info(f"overlays: composed {len(layers)} layer(s) -> "
                f"{comp.spatial_relationship.value}")
    return comp.model_dump(mode="json")
