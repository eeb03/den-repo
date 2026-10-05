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
#:
#: RESOLVED here means SCOREABLE: Subterra has independent ground truth and a
#: declared coordinate frame sufficient to COMPUTE the metric. It says nothing
#: about how well any Subterra method performs -- that is `CAPABILITY_STATUS`
#: below, which a gate change never edits.
LOCALIZATION_SCORING_STATUS = RESOLVED
#: DEPRECATED alias of LOCALIZATION_SCORING_STATUS, kept for existing callers.
#: It is a SCORING gate (BLOCKED/RESOLVED), never a capability status. New
#: code and artifacts must use `localization_scoring_status` / `bam_status_report()`.
LOCALIZATION_STATUS = LOCALIZATION_SCORING_STATUS
LOCALIZATION_BLOCKED_REASON = ""

#: Depth scoring against the published geometry: SCOREABLE, under the same
#: meaning. Every depth score must carry a `DepthProvenance`.
DEPTH_SCORING_STATUS = RESOLVED

#: The benchmark reference frame is the appendix construction drawings, by
#: explicit decision. The paper's prose describes a contradictory origin. That
#: disagreement is RECORDED, not scientifically resolved: the radar data fit the
#: drawings' orientation better (back-wall step residual 3-10x lower, research
#: scripts/bam_quantitative_validation.py), which supports the CHOICE of frame
#: but is not independent evidence about what the authors intended.
REFERENCE_FRAME_SOURCE = (
    "appendix construction drawings: Grohmann et al. 2026, Data in Brief 68:113103, "
    "Appendices A (Pk050), B (Pk266), C (Pk401); origin = circled cross at the THICK end "
    "(the 570 mm step), X along the 2000 mm length toward the thin end, Y across the width, "
    "Z down from the scanned top surface; all dimensions in mm")
REFERENCE_FRAME_CONFLICT = (
    "paper prose (section 4.3) says the origin 'is located at the thin side of the stepped "
    "specimens (at the side with the smallest concrete thickness)', contradicting all three "
    "appendix drawings, which place it at the thick end. Not resolved by author statement; "
    "the drawings are adopted as the benchmark frame.")
REFERENCE_FRAME_SUPPORT = (
    "consistency check, not proof of intent: on every 1.5 GHz scan the back-wall step fit "
    "t = t0 + 2d/v has a residual 3-10x lower in the drawing orientation than mirrored "
    "(evidence/bam/results/quantitative_validation.json, orientation_fit_rms_ns)")

LOCALIZATION_RESOLVED_BY = (
    "frame, units, file-to-grid mapping and object coordinates from the appendix drawings "
    "and the paper's formatting workflow; see REFERENCE_FRAME_SOURCE and the resolutions on "
    "OPEN_QUESTIONS. SCOREABLE ONLY; see CAPABILITY_STATUS.")

#: Where a depth's time zero and velocity came from. A depth score must name one,
#: and scores of different provenance are never combined into one headline.
DEPTH_PROVENANCES = (
    "published_calibration",        # paper Table 4 (back wall, 1.5 GHz Rot00 only)
    "known_thickness_backwall",     # Subterra's fit to the fabricated step thicknesses
    "method_c",                     # direct-wave onset consensus (preprocessing.time_zero)
    "estimated_or_inferred",        # anything else, e.g. hyperbola fitting on the targets
)

#: Measured capability status on BAM (docs/research/bam_quantitative_validation.md
#: section 11). Independent of the gates above: opening a gate never promotes these.
VALIDATED = "VALIDATED"
PARTIALLY_VALIDATED = "PARTIALLY_VALIDATED"
EXPERIMENTAL = "EXPERIMENTAL"
FAILED = "FAILED"

#: Two vocabularies, never shared in one field:
#:   scoring / evidence status   -- can the metric be COMPUTED against independent truth?
#:   capability / performance    -- how well does a Subterra method do on it?
SCORING_STATUSES = (BLOCKED, RESOLVED)
CAPABILITY_STATUSES = (VALIDATED, PARTIALLY_VALIDATED, EXPERIMENTAL, FAILED, BLOCKED)
SCORING_STATUS_MEANING = (
    "RESOLVED = sufficient independent ground truth and coordinate information to COMPUTE "
    "this metric. It is not a performance claim; see capability_status.")
CAPABILITY_STATUS_MEANING = (
    "measured performance of Subterra methods on this benchmark "
    "(VALIDATED / PARTIALLY_VALIDATED / EXPERIMENTAL / FAILED / BLOCKED)")
CAPABILITY_STATUS: dict[str, str] = {
    "dzt_ingestion": VALIDATED,
    "amplitude_preservation": VALIDATED,
    "backwall_time_zero_velocity_calibration": PARTIALLY_VALIDATED,
    "duct_depth_at_known_position_backwall_calibrated": PARTIALLY_VALIDATED,
    "foam_block_depth": EXPERIMENTAL,
    "method_c_depth_chain_time_zero": FAILED,
    "current_detector_localisation": FAILED,
    "current_detector_detection": FAILED,
    "lateral_localisation": FAILED,
    "candidate_generation": FAILED,
    "false_positive_rejection": FAILED,
    "experimental_envelope_detector": EXPERIMENTAL,
    "candidate_generation_v2": EXPERIMENTAL,
}
CAPABILITY_EVIDENCE: dict[str, str] = {
    "duct_depth_at_known_position_backwall_calibrated": (
        "depth at an INDEPENDENTLY KNOWN object position using time zero and velocity "
        "calibrated from the known-thickness back wall: mean +7.1 mm, RMS 7.7 mm, P95 11 mm "
        "(16 measurements of 4 ducts). Not a detection result."),
    "method_c_depth_chain_time_zero": (
        "duct depth bias with no t0 correction about +72 mm, with Method C about +43 mm, with "
        "back-wall calibration about +7 mm; unstable across Y on Pk266 1.5 GHz and at its "
        "quiet-window floor at 2.6 GHz"),
    "candidate_generation": (
        "the ring z-score stays at about 1.7-2.0 at the duct crowns, below the 3.0 threshold, "
        "while firing on the direct wave, gain-amplified late-time noise and step edges; "
        "X-only matching previously credited coincidences at the wrong depth"),
    "experimental_envelope_detector": (
        "background-removed envelope (scripts/bam_candidate_experiment.py): held-out "
        "depth-gated recall 0.75-0.82 but 15-43 false candidates per line; evidence for the "
        "next engineering direction, not a production replacement"),
}

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
    #: When RESOLVED: the evidence that made the prerequisite scoreable.
    resolution: str = ""


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
        status=RESOLVED,
        resolution=(
            "Resolved by adopting the appendix construction drawings as the benchmark frame "
            "(REFERENCE_FRAME_SOURCE): each drawing marks the origin, and the paper states "
            "A-scan X000 / B-scan Y000 lie at that origin. The paper prose contradicts the "
            "drawings about which end it is (REFERENCE_FRAME_CONFLICT); that conflict is "
            "recorded, not resolved. Orientation consistency: REFERENCE_FRAME_SUPPORT."),
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
        status=RESOLVED,
        resolution=(
            "Appendix B dimensions each duct depth from the scanned top surface to the duct "
            "CENTRE (274.5 / 214.6 / 151.4 / 94.4 mm); Appendix C does the same for the Pk401 "
            "cuboid mid-lines. Depth is scored to the centre. The reflecting crown is centre "
            "minus 33.5 mm (outer radius) or 30 mm (inner): a documented 3.5 mm reference "
            "uncertainty. The 2023 article's 'cover' (centre - 30) stays recorded, non-blocking."),
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
        status=RESOLVED,
        resolution=(
            "Publisher declaration: every appendix drawing states 'All geometric data in "
            "millimeters [mm]' and the paper gives the X/Y vectors in mm on a 5 x 5 mm grid "
            "(Table 3). Time in ns is corroborated by the DZT header (15 ns, 512 samples)."),
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
        status=RESOLVED,
        resolution=(
            "Publisher statement (paper, Data formatting workflow): drop the first redundant "
            "A-scan; 181 x 841 x 512; reverse every second line from No. 0; offset correction; "
            "crop; 2.5 -> 5 mm. Reproduced by Subterra: 400/400 probed grid traces equal a "
            "Subterra-decoded DZT A-scan exactly on samples 2-511 (grid row y = DZT line y+10). "
            "evidence/bam/results/amplitude_preservation.json"),
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
    if LOCALIZATION_SCORING_STATUS != RESOLVED:
        unresolved = ", ".join(q.id for q in OPEN_QUESTIONS if q.status != RESOLVED)
        raise LocalizationBlocked(
            f"{what} is {LOCALIZATION_SCORING_STATUS}: {LOCALIZATION_BLOCKED_REASON}. "
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


def bam_status_report() -> dict:
    """
    The one shape reports, artifacts and the UI should consume: scoring gates and
    measured capability side by side, each with its meaning, so RESOLVED can never
    be read as "the platform performs this".
    """
    assert set(CAPABILITY_STATUS.values()) <= set(CAPABILITY_STATUSES)
    return {
        "localization_scoring_status": LOCALIZATION_SCORING_STATUS,
        "localization_scoring_reason": LOCALIZATION_BLOCKED_REASON or LOCALIZATION_RESOLVED_BY,
        "depth_scoring_status": DEPTH_SCORING_STATUS,
        "detection_scoring_status": DETECTION_STATUS,
        "scoring_status_meaning": SCORING_STATUS_MEANING,
        "capability_status": dict(CAPABILITY_STATUS),
        "capability_status_meaning": CAPABILITY_STATUS_MEANING,
        "reference_frame_source": REFERENCE_FRAME_SOURCE,
        "reference_frame_conflict": REFERENCE_FRAME_CONFLICT,
    }
