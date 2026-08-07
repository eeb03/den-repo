"""
Whether a subsurface depth axis can be tied to a surface elevation model.

WHY THIS EXISTS. Producing an absolute Z for a GPR sample requires three
things, and a 3D product will silently invent any of them that is missing:

    1. an elevation for the ACQUISITION SURFACE at that trace,
    2. a declared vertical datum shared by that elevation and the surface
       model it is compared against,
    3. a known offset from the depth axis ORIGIN to the ground.

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


def _declared(datum) -> bool:
    return bool(datum and datum.code and datum.provenance != CRSProvenance.NONE)


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

    sub_datum, sur_datum = _datum(subsurface_frame), _datum(surface_frame)
    if not _declared(sub_datum):
        reasons.append("the subsurface frame declares no vertical datum")
        missing.append(
            "a declared vertical datum for the acquisition elevations (the source states "
            "none, so this must be supplied by whoever knows it)")
    if not _declared(sur_datum):
        reasons.append("the surface frame declares no vertical datum")
        missing.append(
            "a declared vertical datum for the surface model (AHN's NAP is documented by "
            "PDOK but is absent from the GeoTIFF, so it must be supplied explicitly)")

    if _declared(sub_datum) and _declared(sur_datum) and sub_datum.code != sur_datum.code:
        reasons.append(
            f"the two declared datums differ: {sub_datum.code!r} vs {sur_datum.code!r}")
        missing.append(
            f"a transformation between {sub_datum.code} and {sur_datum.code}, which "
            f"Subterra does not perform")

    # Is the depth axis origin tied to the ground?
    origin = (getattr(sub_axis, "origin", "") or "").lower()
    origin_is_ground = "ground surface" in origin or "maaiveld" in origin
    if not origin_is_ground:
        reasons.append(
            f"the subsurface depth axis origin is {getattr(sub_axis, 'origin', None)!r}, "
            f"not the ground surface, so depth 0 is not where the surface model is")
        missing.append(
            "the offset from the depth-axis origin to the ground (for an air-launched "
            "antenna this is an air path that the constant ground velocity does not model)")

    if not has_depth:
        kind = VerticalRelationshipKind.REGISTRATION_REQUIRED if missing \
            else VerticalRelationshipKind.UNRELATED
        return VerticalRelationship(kind, sub_id, sur_id, reasons, missing)

    if not missing:
        return VerticalRelationship(
            VerticalRelationshipKind.ABSOLUTE_ELEVATION, sub_id, sur_id,
            reasons=reasons + ["both vertical datums are declared and equal, and the depth "
                               "axis origin is the ground surface"],
        )

    # A depth below the acquisition surface IS known; only its placement on
    # Earth is not. That is a materially different state from having nothing.
    kind = (VerticalRelationshipKind.RELATIVE_DEPTH_ONLY
            if origin_is_ground else VerticalRelationshipKind.REGISTRATION_REQUIRED)
    return VerticalRelationship(kind, sub_id, sur_id, reasons, missing)
