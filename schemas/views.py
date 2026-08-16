"""
Synchronized views: resolving one selection into every view that can show it.

THE PROBLEM THIS SOLVES HONESTLY. "Select an object in one view and highlight
it everywhere" assumes every view can locate every object. That is false here,
and the falsehood is not a gap to fill later -- it follows from what the data
declares:

    map          needs a geographic position
    radargram    needs a frame and a trace index
    depth_slice  needs a depth axis, which needs a caller-supplied velocity;
                 and a slice ACROSS frames additionally needs those frames to
                 share a vertical reference
    scene_3d     needs an absolute elevation -- X, Y and Z in one frame
    metadata     needs only the identifiers

`scene_3d` is unresolvable for every dataset currently held, because absolute
elevation needs a vertical registration that
`fusion.vertical_reference.assess` reports as `registration_required`
everywhere. A resolver that returned a Z anyway would be fabricating the one
number the whole vertical investigation established we do not have.

So `resolve` returns a `ViewResolution` per view, each either RESOLVED with
coordinates or UNAVAILABLE with the specific reason and what is missing. A
client renders the views it can and shows the reason for the ones it cannot.
Nothing is silently omitted, and nothing is placed at a default coordinate.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from schemas.spatial import NoPosition, Position


class ViewKind(str, Enum):
    MAP = "map"
    RADARGRAM = "radargram"
    DEPTH_SLICE = "depth_slice"
    SCENE_3D = "scene_3d"
    METADATA = "metadata"


class SelectionKind(str, Enum):
    """What a user can select. All are already first-class in the platform."""
    CANDIDATE = "candidate"
    OBJECT = "object"
    LABEL = "label"
    TRACE = "trace"          # one trace of one frame
    FRAME = "frame"          # a whole survey line


class Selection(BaseModel):
    """
    A view-independent selection identity.

    Deliberately built from identifiers the platform already has -- no new
    coordinate system, no synthetic selection id that would need its own
    lifecycle.
    """
    kind: SelectionKind
    dataset_id: str = Field(..., min_length=1)
    selection_id: str = Field(..., min_length=1)
    frame_id: Optional[str] = None
    source_file: Optional[str] = None
    trace_index: Optional[int] = None
    trace_range: Optional[tuple[int, int]] = None
    depth_range_m: Optional[tuple[float, float]] = None
    position: Position = Field(
        default_factory=lambda: NoPosition(reason="the selection carries no position"))


class ViewResolution(BaseModel):
    """Where one view should look, or why it cannot."""
    view: ViewKind
    resolved: bool
    #: Whatever that view needs, in that view's own terms.
    coordinates: dict[str, Any] = Field(default_factory=dict)
    reason: Optional[str] = None
    missing: list[str] = Field(default_factory=list)


class SelectionResolution(BaseModel):
    selection: Selection
    views: list[ViewResolution]

    @property
    def resolvable_views(self) -> list[str]:
        return [v.view.value for v in self.views if v.resolved]


def _map(sel: Selection) -> ViewResolution:
    kind = getattr(sel.position, "kind", "none")
    if kind == "geographic":
        return ViewResolution(
            view=ViewKind.MAP, resolved=True,
            coordinates={"lat": sel.position.lat, "lon": sel.position.lon})
    reason = getattr(sel.position, "reason", None) or (
        f"the selection's position is {kind}, which has no defined location on Earth")
    return ViewResolution(
        view=ViewKind.MAP, resolved=False, reason=reason,
        missing=["a geographic position, or a GeoTie that supplies one"])


def _radargram(sel: Selection, recorded_modalities: Optional[list[str]] = None) -> ViewResolution:
    # Composition gate, same definition the report, signal-chain route,
    # candidates API and trace_grid already share: a non-empty composition
    # without gpr means a radargram view does not apply to this dataset at
    # all -- "names no frame" / "needs a trace index" would misdescribe a
    # DEM/LiDAR selection as an incomplete GPR one, when it was never going
    # to have a frame_id or trace_index in the first place. An empty
    # composition falls through to the checks below unchanged.
    if recorded_modalities and "gpr" not in recorded_modalities:
        return ViewResolution(
            view=ViewKind.RADARGRAM, resolved=False,
            reason=(f"this dataset's recorded modality composition is "
                    f"{', '.join(recorded_modalities)}; a radargram view is a "
                    f"GPR-trace view and does not apply to it"),
            missing=["a GPR acquisition, or frames recording GPR traces"])
    if not sel.frame_id:
        return ViewResolution(
            view=ViewKind.RADARGRAM, resolved=False,
            reason="the selection names no frame, so there is no radargram to open",
            missing=["frame_id"])
    if sel.trace_index is None and sel.trace_range is None:
        return ViewResolution(
            view=ViewKind.RADARGRAM, resolved=False,
            reason=("the selection names a frame but no trace; a radargram highlight "
                    "needs a trace index, which is only meaningful within one "
                    "acquisition"),
            missing=["trace_index or trace_range"])
    coords: dict[str, Any] = {"frame_id": sel.frame_id,
                              "source_file": sel.source_file}
    if sel.trace_range is not None:
        coords["trace_range"] = list(sel.trace_range)
    if sel.trace_index is not None:
        coords["trace_index"] = sel.trace_index
    if sel.depth_range_m is not None:
        coords["depth_range_m"] = list(sel.depth_range_m)
    return ViewResolution(view=ViewKind.RADARGRAM, resolved=True, coordinates=coords)


def _depth_slice(sel: Selection, frame=None, cross_frame: bool = False) -> ViewResolution:
    from schemas.spatial import AxisKind

    if sel.depth_range_m is None:
        return ViewResolution(
            view=ViewKind.DEPTH_SLICE, resolved=False,
            reason=("the selection carries no depth; depth exists only when a "
                    "propagation velocity was supplied at ingest"),
            missing=["a caller-supplied velocity, so a depth axis exists"])
    if frame is not None:
        axis = getattr(frame, "vertical_axis", None)
        if axis is not None and axis.kind != AxisKind.DEPTH_M and not axis.conversion:
            return ViewResolution(
                view=ViewKind.DEPTH_SLICE, resolved=False,
                reason=("the frame carries a time axis and no depth conversion, so a "
                        "depth slice would be slicing time"),
                missing=["a caller-supplied velocity for this frame"])
    if cross_frame:
        return ViewResolution(
            view=ViewKind.DEPTH_SLICE, resolved=False,
            reason=("a depth slice spanning several frames needs them to share a "
                    "vertical reference, and no frame currently declares a vertical "
                    "datum"),
            missing=["a declared vertical datum on every participating frame"])
    return ViewResolution(
        view=ViewKind.DEPTH_SLICE, resolved=True,
        coordinates={"frame_id": sel.frame_id,
                     "depth_range_m": list(sel.depth_range_m),
                     "scope": "single_frame"})


def _scene_3d(sel: Selection, vertical=None) -> ViewResolution:
    """
    A 3D scene needs an absolute elevation. See docs/vertical-reference-site01.md:
    every dataset held reports `registration_required`, so this is unresolvable
    -- and returning a Z regardless would fabricate exactly the quantity that
    investigation established is missing.
    """
    missing = ["an established vertical relationship (absolute elevation)"]
    reason = ("a 3D scene needs an absolute elevation for the selection, and no "
              "dataset held has an established vertical relationship: the GPR depth "
              "axis starts at instrument time-zero, not the ground surface, and no "
              "source declares a vertical datum")
    if vertical is not None:
        if vertical.get("absolute_elevation_available"):
            return ViewResolution(
                view=ViewKind.SCENE_3D, resolved=True,
                coordinates={"frame_id": sel.frame_id,
                             "depth_range_m": list(sel.depth_range_m or []),
                             "note": "elevation available; see the vertical relationship"})
        missing = vertical.get("missing", missing)
        reason = ("the vertical relationship between this selection's frame and the "
                  "surface model is " + str(vertical.get("kind")))
    return ViewResolution(view=ViewKind.SCENE_3D, resolved=False,
                          reason=reason, missing=missing)


def _metadata(sel: Selection) -> ViewResolution:
    return ViewResolution(
        view=ViewKind.METADATA, resolved=True,
        coordinates={"kind": sel.kind.value, "dataset_id": sel.dataset_id,
                     "selection_id": sel.selection_id, "frame_id": sel.frame_id})


def resolve(selection: Selection, frame=None, vertical: Optional[dict] = None,
            cross_frame_slice: bool = False,
            recorded_modalities: Optional[list[str]] = None) -> SelectionResolution:
    """
    Resolves one selection into every view, answering per view.

    `frame` sharpens the depth-slice answer; `vertical` is the result of
    `fusion.vertical_reference.assess` when the caller has one.
    `recorded_modalities` (see `schemas.dataset_report.frame_modalities` /
    `identity.recorded_modalities`) only changes the radargram answer: a
    non-empty composition with no gpr in it says a radargram view does not
    apply, rather than reporting the selection itself as incomplete. All
    optional: without them the answers are the conservative ones, which are
    also the correct ones for every dataset currently held.
    """
    return SelectionResolution(selection=selection, views=[
        _map(selection),
        _radargram(selection, recorded_modalities=recorded_modalities),
        _depth_slice(selection, frame=frame, cross_frame=cross_frame_slice),
        _scene_3d(selection, vertical=vertical),
        _metadata(selection),
    ])
