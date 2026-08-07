"""
Evidence gates for the BAM benchmark.

This module exists so that a claim the evidence does not support cannot be
made by accident later. Detection scoring runs; anything that would require an
absolute coordinate origin raises.

The gate is data, not opinion: each entry names what is missing and what would
resolve it. Flipping one to RESOLVED is a deliberate edit that a test notices.
"""
from __future__ import annotations

from dataclasses import dataclass

BLOCKED = "BLOCKED"
RESOLVED = "RESOLVED"

#: Localisation scoring -- any metric expressed in absolute or physical
#: coordinates rather than in benchmark-local grid indices.
LOCALIZATION_STATUS = BLOCKED
LOCALIZATION_BLOCKED_REASON = "absolute origin is not verified"

#: Detection and false-alarm scoring do NOT depend on the absolute origin:
#: they ask whether a detection falls inside a target's grid-node footprint,
#: which is defined in the same grid the detections are indexed by.
DETECTION_STATUS = RESOLVED


@dataclass(frozen=True)
class OpenQuestion:
    id: str
    statement: str
    blocks: str
    resolution_route: str
    status: str = BLOCKED


#: The unresolved evidence questions, carried forward verbatim from the
#: acquisition assessment so they cannot be quietly dropped.
OPEN_QUESTIONS: tuple[OpenQuestion, ...] = (
    OpenQuestion(
        id="absolute-origin",
        statement=(
            "No file in either archive contains a drawing, an origin marker, or "
            "any statement of where scanner X=0 sits on the specimen. That the "
            "scanner origin is the same physical corner as the drawing origin "
            "the target X values are measured from is corroborated, not declared."
        ),
        blocks="localisation scoring in absolute or physical coordinates",
        resolution_route="BAM appendix drawings, or author contact",
    ),
    OpenQuestion(
        id="depth-reference-surface",
        statement=(
            "Published centre depth minus published concrete cover is exactly "
            "30.0 mm (the inner radius) for all four ducts, where a cover "
            "measured to the outer surface facing the antenna would give 33.5 mm. "
            "The two sources use different reference surfaces; which one Table 4 "
            "means is unsettled."
        ),
        blocks="absolute depth accuracy scoring",
        resolution_route="BAM Table 4 reference surface, via author contact",
    ),
    OpenQuestion(
        id="coordinate-units",
        statement=(
            "The coordinate .npy arrays carry no unit and no file in either "
            "archive declares one. Millimetres come from the Dataverse prose. "
            "(Nanoseconds are independently corroborated by the DZT header.)"
        ),
        blocks="any metric reported in physical units rather than grid nodes",
        resolution_route="a units declaration from the publisher",
    ),
    OpenQuestion(
        id="dzt-to-grid-mapping",
        statement=(
            "The DZT holds 152,222 traces; the coordinate-registered grid is "
            "401 x 161 = 64,561. No source documents how DZT traces map onto "
            "grid nodes, so the DZT is not used as the scoring amplitude source."
        ),
        blocks="scoring directly against the native DZT stream",
        resolution_route="an acquisition-order statement from the publisher",
    ),
)


# --------------------------------------------------------------------------
# 4TU real-world utility benchmark
#
# A different corpus with a different blocker. BAM is blocked on an unverified
# ORIGIN; 4TU is blocked on the absence of coordinates altogether -- the
# publisher removed them to protect utility locations. Activity-level scoring
# is available; anything that matches a candidate to a utility is not.
# --------------------------------------------------------------------------

OBJECT_LEVEL_STATUS = BLOCKED
OBJECT_LEVEL_BLOCKED_REASON = (
    "4TU publishes no trench coordinates, so no candidate can be matched to a utility"
)
ACTIVITY_LEVEL_STATUS = RESOLVED

FOURTU_OPEN_QUESTIONS: tuple["OpenQuestion", ...] = ()  # populated below


class LocalizationBlocked(RuntimeError):
    """Raised when something asks for a result the evidence cannot support."""


class ObjectLevelBlocked(RuntimeError):
    """Raised when a metric needs a candidate-to-target match that cannot exist."""


def require_localization_evidence(what: str = "localisation scoring") -> None:
    """
    Call before producing ANY absolute-coordinate result.

    Detection and false-alarm scoring must never call this -- they are
    independently executable, and a gate that blocked them would be wrong.
    """
    if LOCALIZATION_STATUS != RESOLVED:
        unresolved = ", ".join(q.id for q in OPEN_QUESTIONS if q.status != RESOLVED)
        raise LocalizationBlocked(
            f"{what} is {LOCALIZATION_STATUS}: {LOCALIZATION_BLOCKED_REASON}. "
            f"Unresolved: {unresolved}. "
            f"Detection and false-alarm scoring remain available and do not "
            f"depend on the absolute origin. See "
            f"docs/external-gpr-benchmark-acquisition.md section 9."
        )


FOURTU_OPEN_QUESTIONS = (
    OpenQuestion(
        id="trench-coordinates",
        statement=(
            "The publisher removed geospatial information from the ground truth "
            "to preserve utility-location confidentiality. No candidate can be "
            "matched to a particular utility."
        ),
        blocks="per-object precision/recall, IoU, detection distance, positional F1",
        resolution_route="author contact (University of Twente); a confidentiality decision, not an omission",
    ),
    OpenQuestion(
        id="trench-is-a-subset-of-the-survey",
        statement=(
            "'Amount of utilities' counts what the TRIAL TRENCH found. A trench "
            "is a small excavation inside a much larger surveyed area, so a "
            "utility under a survey line but outside the trench is absent from "
            "the truth and present in the ground."
        ),
        blocks="calling an unmatched detector response a false positive",
        resolution_route="trench extents, which are not published",
    ),
    OpenQuestion(
        id="attested-zero-population-is-small",
        statement=(
            "Only a handful of activities report a trench count of zero, which "
            "is too few to carry a stable rate."
        ),
        blocks="a false-alarm RATE on real-world ground",
        resolution_route="more zero-utility trenches, or another real-world corpus",
    ),
)


def require_object_level_evidence(what: str = "object-level scoring") -> None:
    """
    Call before any metric that matches a candidate to a specific utility.

    Activity-level scoring must never call this: counting candidates per
    activity needs no coordinates and is legitimately available.
    """
    if OBJECT_LEVEL_STATUS != RESOLVED:
        unresolved = ", ".join(q.id for q in FOURTU_OPEN_QUESTIONS if q.status != RESOLVED)
        raise ObjectLevelBlocked(
            f"{what} is {OBJECT_LEVEL_STATUS}: {OBJECT_LEVEL_BLOCKED_REASON}. "
            f"Unresolved: {unresolved}. "
            f"Activity-level scoring remains available. See "
            f"docs/4tu-utility-benchmark.md."
        )


FOURTU_SCOPE_STATEMENT = (
    "4TU results are activity-level only. No candidate is matched to a utility, "
    "and no positional or depth accuracy is measured. An unmatched detector "
    "response is not necessarily a false alarm, because the trial trench covers "
    "only part of the surveyed ground."
)


#: The sentence that must accompany any reported BAM number. Kept here, in
#: code, so a report cannot be written without it.
SCOPE_STATEMENT = (
    "BAM benchmark results measure performance on controlled concrete NDT "
    "specimens. They are not evidence of soil/utility-scale subsurface "
    "detection or localisation performance."
)
