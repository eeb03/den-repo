"""
Cross-sensor overlays: describing how layers relate, without flattening them.

WHY NOTHING IS FLATTENED. The obvious way to overlay GPR, DEM, LiDAR and
imagery is to reproject everything into one coordinate system at load time
and hand the client a single grid. That is exactly what this module refuses
to do, for the reason the rest of the platform refuses it: once a layer's
coordinates have been rewritten, its provenance is gone. A viewer can no
longer tell which numbers a sensor measured from which a transform produced,
and a layer whose CRS was never declared becomes indistinguishable from one
that declared it.

So an `OverlayLayer` keeps its NATIVE `SpatialRef`, and carries a derived
WGS84 extent as a clearly-labelled RENDER HINT alongside it -- computed
through the existing `ingestion/crs_transform`, never stored as if it were
the layer's own coordinates.

WHAT A COMPOSITION ASSERTS. Only what the evidence supports:

    co_registered     every layer has a declared or inferable CRS, and their
                      extents overlap. They can be drawn together.
    disjoint          every layer is placeable, but their extents do not meet.
                      Drawing them on one map is legitimate; expecting them to
                      align is not.
    not_relatable     at least one layer cannot be placed on Earth at all --
                      odometry, a local grid, or a projected layer whose CRS
                      nobody declared. NO amount of processing fixes this;
                      it needs a declaration or a tie.

`not_relatable` is the important one. It is the honest answer for a Hillside
plot or a Guangzhou line, and a viewer that renders it as "at 0, 0" or
silently omits it is the failure this vocabulary prevents.

VERTICAL IS SEPARATE, AND USUALLY UNKNOWN. Horizontal agreement says nothing
about depth. `vertical_relationship` defers to
`fusion.vertical_reference.assess`, which for every dataset held today
answers `registration_required`.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from schemas.provenance import ProvenanceClass, frame_provenance, summarise
from schemas.spatial import CRSKind, CRSProvenance, SpatialRef


class SpatialRelationship(str, Enum):
    CO_REGISTERED = "co_registered"
    DISJOINT = "disjoint"
    NOT_RELATABLE = "not_relatable"


class LayerExtent(BaseModel):
    """
    A layer's footprint, in its OWN coordinates plus an optional derived view.

    `native_*` are the layer's real numbers. `wgs84_*` exist only so a client
    can place the layer on a web map, and `wgs84_provenance` is always
    `derived` when present -- it is never the layer's own coordinates.
    """
    native_crs: Optional[str] = None
    native_kind: str
    native_min_x: Optional[float] = None
    native_max_x: Optional[float] = None
    native_min_y: Optional[float] = None
    native_max_y: Optional[float] = None

    wgs84_min_lat: Optional[float] = None
    wgs84_max_lat: Optional[float] = None
    wgs84_min_lon: Optional[float] = None
    wgs84_max_lon: Optional[float] = None
    wgs84_provenance: Optional[ProvenanceClass] = None
    wgs84_basis: Optional[str] = None

    n_positions_sampled: int = 0

    @property
    def is_placeable(self) -> bool:
        """Whether this layer can be put on a map at all."""
        return self.wgs84_min_lat is not None


class OverlayLayer(BaseModel):
    """
    One sensor's contribution to a composition.

    Carries its own reference, its own provenance summary, and its own list of
    unknowns. Nothing is normalised across layers; a client renders each on
    its own terms.
    """
    layer_id: str
    dataset_id: str
    frame_id: Optional[str] = None
    modality: str
    source_format: str
    spatial_ref: SpatialRef
    extent: LayerExtent
    provenance: list[dict] = Field(default_factory=list)
    provenance_summary: dict = Field(default_factory=dict)
    #: What this layer does not know, in the caller's language. Rendered as
    #: caveats rather than hidden.
    unknowns: list[str] = Field(default_factory=list)
    record_count: Optional[int] = None


class OverlayComposition(BaseModel):
    """Several layers, and an honest statement of how they relate."""
    layers: list[OverlayLayer]
    spatial_relationship: SpatialRelationship
    spatial_basis: str
    unplaceable_layers: list[str] = Field(default_factory=list)
    vertical_relationship: Optional[dict] = None
    #: Union of the placeable layers' derived WGS84 extents, or None. A render
    #: hint for setting the initial view -- not a coordinate system the layers
    #: were converted into.
    suggested_view: Optional[dict] = None
    notes: list[str] = Field(default_factory=list)


def _wgs84_extent(spatial_ref: SpatialRef, min_x, max_x, min_y, max_y):
    """
    Derives a WGS84 bounding box, or returns None when that is not possible.

    Uses the existing transform path, and refuses exactly where the rest of
    the platform refuses: a projected layer whose CRS nobody declared has no
    derivable extent, however plausible its numbers look.
    """
    from ingestion.crs_transform import CRSTransformError, is_transformable, to_wgs84

    if min_x is None:
        return None, None, "the layer has no positions to take an extent from"
    if spatial_ref.kind == CRSKind.GEOGRAPHIC:
        return ((min_y, max_y, min_x, max_x), ProvenanceClass.MEASURED,
                "the layer's own geographic coordinates; no transform applied")
    if spatial_ref.kind == CRSKind.PROJECTED:
        if not is_transformable(spatial_ref.code):
            return (None, None,
                    "projected coordinates whose frame declares no CRS: the extent "
                    "cannot be placed on Earth, and nothing is inferred from the "
                    "magnitude of the numbers")
        try:
            corners = to_wgs84(spatial_ref.code,
                               [min_x, max_x, min_x, max_x],
                               [min_y, min_y, max_y, max_y])
        except (CRSTransformError, Exception):
            return None, None, f"could not transform from {spatial_ref.code}"
        lats = [c[0] for c in corners]
        lons = [c[1] for c in corners]
        return ((min(lats), max(lats), min(lons), max(lons)), ProvenanceClass.DERIVED,
                f"derived by transforming the layer's extent from {spatial_ref.code} "
                f"to EPSG:4326; the layer's own coordinates are unchanged")
    return (None, None,
            f"a {spatial_ref.kind.value} reference has no defined relationship to the "
            f"Earth until someone supplies a tie")


def build_layer(frame, records, layer_id: Optional[str] = None) -> OverlayLayer:
    """
    Describes one frame as an overlay layer.

    Extent comes from the records' `Position`s -- the platform's single source
    of spatial truth -- not from a parallel coordinate store.
    """
    from schemas.spatial import PositionKind, effective_position

    ref = frame.spatial_ref
    xs, ys, n = [], [], 0
    for r in records:
        p = effective_position(r)
        kind = getattr(p, "kind", None)
        if kind == PositionKind.GEOGRAPHIC:
            xs.append(p.lon); ys.append(p.lat)
        elif kind == PositionKind.PROJECTED:
            xs.append(p.easting); ys.append(p.northing)
        elif kind == PositionKind.LOCAL_CARTESIAN:
            xs.append(p.x); ys.append(p.y)
        elif kind == PositionKind.ODOMETRY:
            xs.append(p.along_track_m); ys.append(p.cross_track_m)
        else:
            continue
        n += 1

    box = (min(xs), max(xs), min(ys), max(ys)) if xs else (None, None, None, None)
    wgs, wgs_prov, basis = _wgs84_extent(ref, *box)
    extent = LayerExtent(
        native_crs=ref.code, native_kind=ref.kind.value,
        native_min_x=box[0], native_max_x=box[1],
        native_min_y=box[2], native_max_y=box[3],
        wgs84_min_lat=wgs[0] if wgs else None,
        wgs84_max_lat=wgs[1] if wgs else None,
        wgs84_min_lon=wgs[2] if wgs else None,
        wgs84_max_lon=wgs[3] if wgs else None,
        wgs84_provenance=wgs_prov, wgs84_basis=basis,
        n_positions_sampled=n,
    )

    entries = frame_provenance(frame)
    unknowns = [e.basis for e in entries if e.provenance == ProvenanceClass.UNAVAILABLE]
    if not extent.is_placeable:
        unknowns.append(basis)

    return OverlayLayer(
        layer_id=layer_id or frame.frame_id,
        dataset_id=frame.dataset_id, frame_id=frame.frame_id,
        modality=frame.modality.value if hasattr(frame.modality, "value")
        else str(frame.modality),
        source_format=frame.source_format,
        spatial_ref=ref, extent=extent,
        provenance=[e.model_dump() for e in entries],
        provenance_summary=summarise(entries),
        unknowns=unknowns, record_count=len(records),
    )


def _boxes_overlap(a: LayerExtent, b: LayerExtent) -> bool:
    return not (a.wgs84_max_lat < b.wgs84_min_lat or b.wgs84_max_lat < a.wgs84_min_lat
                or a.wgs84_max_lon < b.wgs84_min_lon or b.wgs84_max_lon < a.wgs84_min_lon)


def compose(layers: list[OverlayLayer],
            subsurface_frame=None, surface_frame=None) -> OverlayComposition:
    """
    States how a set of layers relates -- and only what the evidence supports.

    A single layer is trivially co-registered with itself if placeable; the
    interesting cases are two or more.
    """
    unplaceable = [l.layer_id for l in layers if not l.extent.is_placeable]
    notes: list[str] = []

    if unplaceable:
        rel = SpatialRelationship.NOT_RELATABLE
        basis = (f"{len(unplaceable)} of {len(layers)} layer(s) cannot be placed on "
                 f"Earth: {', '.join(unplaceable)}. This needs a declared CRS or a "
                 f"GeoTie -- no amount of processing resolves it.")
        notes.append("layers that cannot be placed must not be drawn at a default "
                     "coordinate; render them as unplaced or omit them explicitly")
    else:
        placeable = [l for l in layers if l.extent.is_placeable]
        overlapping = all(
            _boxes_overlap(a.extent, b.extent)
            for i, a in enumerate(placeable) for b in placeable[i + 1:]
        ) if len(placeable) > 1 else True
        if overlapping:
            rel = SpatialRelationship.CO_REGISTERED
            basis = ("every layer has a usable reference and their extents overlap, so "
                     "they describe the same ground and can be drawn together")
        else:
            rel = SpatialRelationship.DISJOINT
            basis = ("every layer is placeable, but their extents do not meet; drawing "
                     "them on one map is fine, expecting them to align is not")

    derived = [l.layer_id for l in layers
               if l.extent.wgs84_provenance == ProvenanceClass.DERIVED]
    if derived:
        notes.append(f"the map position of {', '.join(derived)} is DERIVED by "
                     f"transforming from its native CRS; its own coordinates are "
                     f"unchanged and remain authoritative")

    view = None
    placeable = [l for l in layers if l.extent.is_placeable]
    if placeable:
        view = {
            "min_lat": min(l.extent.wgs84_min_lat for l in placeable),
            "max_lat": max(l.extent.wgs84_max_lat for l in placeable),
            "min_lon": min(l.extent.wgs84_min_lon for l in placeable),
            "max_lon": max(l.extent.wgs84_max_lon for l in placeable),
            "basis": ("union of the placeable layers' derived extents; a render hint "
                      "for the initial view, NOT a coordinate system the layers were "
                      "converted into"),
        }

    vertical = None
    if subsurface_frame is not None and surface_frame is not None:
        from fusion import vertical_reference as vr
        rel_v = vr.assess(subsurface_frame, surface_frame)
        vertical = {
            "kind": rel_v.kind.value,
            "absolute_elevation_available": rel_v.absolute_elevation_available,
            "reasons": rel_v.reasons, "missing": rel_v.missing,
        }
        if not rel_v.absolute_elevation_available:
            notes.append("horizontal agreement says nothing about depth: these layers "
                         "have no established vertical relationship, so subsurface "
                         "depths must not be drawn against surface elevations")

    return OverlayComposition(
        layers=layers, spatial_relationship=rel, spatial_basis=basis,
        unplaceable_layers=unplaceable, vertical_relationship=vertical,
        suggested_view=view, notes=notes,
    )
