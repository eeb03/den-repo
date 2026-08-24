"""
Whether a subsurface depth axis can be tied to a surface elevation model.

WHY THIS EXISTS. Producing an absolute Z for a GPR sample requires three
things, and a 3D product will silently invent any of them that is missing:

    1. an elevation for the ACQUISITION SURFACE at that trace,
    2. a declared vertical datum shared by that elevation and the surface
       model it is compared against,
    3. a known offset from the depth axis ORIGIN to the ground -- which since
       stage 12 may be DECLARED (`VerticalAxis.origin_offset`) rather than only
       implied by an axis whose origin already is the ground.

Subterra holds datasets where (1) exists, (2) is undeclared everywhere, and
(3) is unknown. This module reports that state instead of papering over it,
so `absolute elevation`, `measured GPR depth`, `surface elevation` and
`unknown relationship` stay four different things downstream.

IT DELIBERATELY COMPUTES NO Z. There is no function here that returns an
absolute elevation, because for every dataset currently held the honest
answer is that one cannot be computed. When a caller declares the missing
pieces, `assess` will say so and the computation can be added then --
against a declaration, not a guess.

WHAT THE SITE-01 MEASUREMENT SHOWED. The 4TU SEG-Y trace headers carry a
per-trace elevation that agrees with the AHN ground surface to
-0.70 +/- 0.41 m. That is close enough to look tempting and is exactly why
this module exists: the residual's mean varies from +0.43 m to -1.33 m
BETWEEN the nine activities of the same site, while staying tight
(sd 0.04-0.28 m) WITHIN each one. A fixed antenna height would be constant.
Something varies per activity -- terrain change on an active construction
site, a different pole setup, GNSS vertical error, a different geoid model --
and nothing in the data distinguishes them. Declaring a datum on that basis
would be inventing provenance.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from schemas.spatial import (
    AxisKind, CRSProvenance, VerticalRelationshipKind,
)

#: Axis kinds that describe a distance below something, as opposed to a time
#: axis or an elevation above a datum.
_DEPTH_KINDS = {AxisKind.DEPTH_M}
_TIME_KINDS = {AxisKind.TWO_WAY_TIME_NS, AxisKind.TWO_WAY_TIME_MS,
               AxisKind.TWO_WAY_TIME_S}


@dataclass
class VerticalRelationship:
    """
    The assessed relationship, with everything that is missing named.

    `missing` is the actionable part: each entry is a specific declaration or
    measurement that would move the assessment forward, phrased so a caller
    knows what to go and find.
    """
    kind: VerticalRelationshipKind
    subsurface_frame_id: str | None
    surface_frame_id: str | None
    reasons: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def absolute_elevation_available(self) -> bool:
        """The single question a 3D consumer needs answered before drawing Z."""
        return self.kind == VerticalRelationshipKind.ABSOLUTE_ELEVATION

    def describe(self) -> str:
        out = [f"vertical relationship: {self.kind.value}"]
        out += [f"  - {r}" for r in self.reasons]
        if self.missing:
            out.append("  missing:")
            out += [f"    * {m}" for m in self.missing]
        return "\n".join(out)


def _datum(frame):
    axis = getattr(frame, "vertical_axis", None)
    return getattr(axis, "vertical_datum", None) if axis else None


def _acquisition_elevation_datum(frame):
    aed = getattr(frame, "acquisition_elevation_datum", None)
    return getattr(aed, "datum", None) if aed else None


def _declared(datum) -> bool:
    return bool(datum and datum.code and datum.provenance != CRSProvenance.NONE)


def _usable_vertical_datum(frame):
    """
    The datum this frame's ELEVATION VALUE is actually expressed in for this
    comparison, and which declaration supplied it: `"vertical_axis"` or
    `"acquisition_elevation"`. `(None, None)` if neither is declared.

    The vertical AXIS datum is authoritative when declared -- unchanged from
    before this function existed. It is a FALLBACK ONLY: a declared axis
    datum is never replaced by a different acquisition-elevation one, and an
    undeclared axis is never silently promoted by a matching acquisition
    elevation into something nobody asserted it to be.

    WHY THE FALLBACK IS SOUND, NOT A SHORTCUT: `compute_absolute_elevation`
    (schemas/scene.py) uses `record.elevation` directly as the surface term.
    For the 4TU GPR lines this exists for, that value is read straight from
    the SEG-Y header's per-trace acquisition elevation at ingest
    (converters/segy_converter.py) -- so when the axis itself declares no
    datum, the acquisition-elevation datum IS the datum of the number this
    module's caller is about to use, not a stand-in for it.

    THE CAVEAT THIS DOES NOT CLOSE: `preprocessing.dem_alignment` can later
    overwrite `record.elevation` with a DEM-sampled value for some or all of
    a frame's records. That value's datum is the SURFACE frame's, not this
    one's acquisition-elevation declaration -- and nothing here can see that,
    because `assess` classifies one frame pairing, never a record. A caller
    that lets DEM alignment run against a dataset resolved through THIS
    route must re-verify the datum question at the record level; this
    function only answers it at the frame level, as it always has.

    NOT THE SAME QUESTION `schemas.spatial_reference` asks. That module's
    own vertical-reference dimension deliberately does NOT let an
    acquisition-elevation datum resolve it (tests/test_vertical_datum_scope.py)
    because that dimension asks what the DEPTH AXIS is referenced to, and an
    elevation datum answers nothing about that. This function asks a
    narrower, different question: what datum is the ELEVATION NUMBER actually
    in. The two modules are allowed to disagree.
    """
    axis_datum = _datum(frame)
    if _declared(axis_datum):
        return axis_datum, "vertical_axis"
    aed = _acquisition_elevation_datum(frame)
    if _declared(aed):
        return aed, "acquisition_elevation"
    return None, None


def assess(subsurface_frame, surface_frame) -> VerticalRelationship:
    """
    Classifies how `subsurface_frame`'s depth axis relates to
    `surface_frame`'s elevations.

    Nothing here inspects coordinate VALUES. Agreement between two numbers is
    not evidence that they share a datum -- that is precisely the inference
    this module exists to refuse.
    """
    sub_id = getattr(subsurface_frame, "frame_id", None)
    sur_id = getattr(surface_frame, "frame_id", None)
    reasons: list[str] = []
    missing: list[str] = []

    sub_axis = getattr(subsurface_frame, "vertical_axis", None)
    sur_axis = getattr(surface_frame, "vertical_axis", None)
    sub_kind = getattr(sub_axis, "kind", None)
    sur_kind = getattr(sur_axis, "kind", None)

    if sur_kind != AxisKind.ELEVATION_M:
        return VerticalRelationship(
            VerticalRelationshipKind.UNRELATED, sub_id, sur_id,
            reasons=[f"the surface frame's vertical axis is {sur_kind}, not an elevation, "
                     f"so it cannot anchor anything"],
            missing=["a surface model whose vertical axis is an elevation"],
        )

    # Does a depth axis exist at all?
    has_depth = sub_kind in _DEPTH_KINDS or (
        sub_kind in _TIME_KINDS and getattr(sub_axis, "conversion", None) is not None)
    if sub_kind in _TIME_KINDS and getattr(sub_axis, "conversion", None) is None:
        reasons.append(
            "the subsurface frame carries a MEASURED time axis and no depth: no velocity "
            "was supplied, so there is nothing yet to place vertically")
        missing.append("a caller-supplied velocity, to derive depth from the time axis")
    elif sub_kind in _TIME_KINDS:
        reasons.append(
            "the subsurface depth is DERIVED from a measured time axis using a "
            "caller-supplied velocity; it is an assumption about the subsurface, not a "
            "measurement of it")

    sub_datum, sub_datum_route = _usable_vertical_datum(subsurface_frame)
    sur_datum, sur_datum_route = _usable_vertical_datum(surface_frame)
    if sub_datum is None:
        reasons.append(
            "the subsurface frame declares no vertical datum, on its vertical axis or "
            "its acquisition elevation")
        missing.append(
            "a declared vertical datum for the acquisition elevations (the source states "
            "none, so this must be supplied by whoever knows it)")
    if sur_datum is None:
        reasons.append(
            "the surface frame declares no vertical datum, on its vertical axis or its "
            "acquisition elevation")
        missing.append(
            "a declared vertical datum for the surface model (AHN's NAP is documented by "
            "PDOK but is absent from the GeoTIFF, so it must be supplied explicitly)")

    if sub_datum is not None and sur_datum is not None and sub_datum.code != sur_datum.code:
        reasons.append(
            f"the two declared datums differ: {sub_datum.code!r} vs {sur_datum.code!r}")
        missing.append(
            f"a transformation between {sub_datum.code} and {sur_datum.code}, which "
            f"Subterra does not perform")

    # Is the depth axis origin tied to the ground?
    #
    # TWO WAYS TO SATISFY THIS, and they are different claims. Either the axis
    # says its own zero IS the ground -- some formats do -- or somebody has
    # declared how far apart they are. Until this stage only the first existed,
    # and it was decided by SEARCHING A FREE-TEXT FIELD for the words "ground
    # surface": a string match standing in for a physical relationship, which
    # no declaration could ever satisfy.
    origin = (getattr(sub_axis, "origin", "") or "").lower()
    origin_is_ground = "ground surface" in origin or "maaiveld" in origin
    offset = getattr(sub_axis, "origin_offset", None)

    # A phase-centre or housing height is a real measurement that does not
    # answer this question: it relates the ANTENNA to the ground, not the axis
    # ZERO to the ground, and time zero is set by the electronics rather than by
    # where the case sits. Recorded, and reported as insufficient.
    offset_relates_axis = bool(offset is not None and offset.relates_the_depth_axis)

    if offset is not None and not offset_relates_axis:
        reasons.append(
            f"an offset of {offset.offset_m} m is declared, but it is measured from the "
            f"{offset.measured_from.value!r}, not from the depth-axis origin; the axis "
            f"zero is instrument time zero and nobody has related the two")
        missing.append(
            "the offset from the DEPTH-AXIS ORIGIN to the ground, or a stated "
            "relationship between the declared reference point and the axis zero")
    elif offset_relates_axis:
        reasons.append(
            f"the depth-axis origin is declared to sit {offset.offset_m} m "
            f"{'above' if offset.offset_m >= 0 else 'below'} the ground "
            f"({offset.evidence.value}, asserted by {offset.supplied_by!r}); this is a "
            f"declaration and nothing has verified it")
    elif not origin_is_ground:
        reasons.append(
            f"the subsurface depth axis origin is {getattr(sub_axis, 'origin', None)!r}, "
            f"not the ground surface, so depth 0 is not where the surface model is")
        missing.append(
            "the offset from the depth-axis origin to the ground (for an air-launched "
            "antenna this is an air path that the constant ground velocity does not model)")

    #: True when the axis zero can be placed against the ground at all, by
    #: either route. Everything below reads this rather than the string match.
    origin_is_placeable = origin_is_ground or offset_relates_axis

    if not has_depth:
        kind = VerticalRelationshipKind.REGISTRATION_REQUIRED if missing \
            else VerticalRelationshipKind.UNRELATED
        return VerticalRelationship(kind, sub_id, sur_id, reasons, missing)

    if not missing:
        if sub_datum_route == "vertical_axis" and sur_datum_route == "vertical_axis":
            datum_note = "both vertical datums are declared and equal"
        else:
            def _named(route, side):
                return (f"the {side} frame's acquisition elevation (its vertical axis "
                        f"declares none)" if route == "acquisition_elevation"
                        else f"the {side} frame's vertical axis")
            datum_note = (
                f"the declared vertical datums agree ({sub_datum.code!r}), from "
                f"{_named(sub_datum_route, 'subsurface')} and "
                f"{_named(sur_datum_route, 'surface')} respectively; a datum taken from "
                "an acquisition elevation describes that stored number only, and stops "
                "being valid for a record whose elevation is later replaced by a DEM "
                "lookup")
        return VerticalRelationship(
            VerticalRelationshipKind.ABSOLUTE_ELEVATION, sub_id, sur_id,
            reasons=reasons + [
                datum_note + ", and the depth axis origin "
                + ("is the ground surface" if origin_is_ground
                   else "has a declared offset to the ground")],
        )

    # A depth below the acquisition surface IS known; only its placement on
    # Earth is not. That is a materially different state from having nothing.
    kind = (VerticalRelationshipKind.RELATIVE_DEPTH_ONLY
            if origin_is_placeable else VerticalRelationshipKind.REGISTRATION_REQUIRED)
    return VerticalRelationship(kind, sub_id, sur_id, reasons, missing)
