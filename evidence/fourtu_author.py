"""
Dr. ter Huurne's response about the 4TU dataset, recorded as received.

WHY THIS IS A MODULE AND NOT A NOTE IN A DOCSTRING. Several readiness questions
in this platform have been blocked for stages on evidence only a dataset author
could supply, and `benchmark.gates` records each with a `resolution_route`. This
is the first time one of those routes actually produced an answer. Storing the
answer as data -- attributed, quotable, and separated from what Subterra inferred
from it -- is what lets a later reader check whether a state change was justified
by what the author said or by what somebody wanted the author to have said.

THE ATTRIBUTION IS THE POINT. `AUTHORITY` names Dr. ter Huurne. Nothing here is a
Subterra measurement, a verified Subterra observation, a computed correction or a
ground-truth label, and `verified_by_subterra` is False on every claim because
Subterra has checked none of them against an independent source.

WHAT THE AUTHOR DID NOT SAY IS RECORDED AS CAREFULLY AS WHAT THEY DID. The
response establishes that a time-zero/air-gap offset EXISTS and gives no
magnitude for it. An implementation that read "the ground surface does not
necessarily correspond to depth zero" as licence to pick a number would be
inventing the one quantity the author explicitly did not provide.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

AUTHORITY = "Dr. ter Huurne"
AUTHORITY_ROLE = "author of the 4TU dataset and its accompanying paper"
CHANNEL = "direct written response to a Subterra enquiry"
#: No date is recorded because the response as received carries none. Inventing
#: one would fabricate provenance for the provenance.
RECEIVED_AT = None

#: The response, quoted rather than paraphrased, so a reader can judge the
#: claims below against the words they were drawn from.
RESPONSE_VERBATIM = """\
Thank you for your interest in our paper and dataset.

Regarding your question on the vertical reference: the GNSS-derived elevation \
values in the exported SEG-Y files are stored as ellipsoidal heights (WGS84) \
rather than NAP heights. Within RadarMap (the software I used), these can be \
transformed to RD/NAP coordinates and elevations.

Regarding the additional questions:

The RTK measurements were acquired using a GNSS rover with a constant antenna \
height. This antenna-height offset was already accounted for during acquisition.
The published SEG-Y files contain the original acquisition data. No time-zero \
correction or air-gap removal was applied, so the ground surface does not \
necessarily correspond to depth zero and an air-path contribution remains \
present in the data."""


class EvidenceKind(str, Enum):
    """
    Where a statement came from. No statement may move between these silently.

    `DERIVED_BY_SUBTERRA` is listed alongside the others precisely so that
    Subterra's own inferences sit in the same table as the author's assertions
    and are visibly not the same thing.
    """
    AUTHOR_STATED = "author_stated"
    MEASURED_IN_FILE = "measured_in_file"
    DERIVED_BY_SUBTERRA = "derived_by_subterra"
    USER_DECLARED = "user_declared"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AuthorClaim:
    """One thing the author said, and what it does and does not settle."""
    id: str
    claim: str
    kind: EvidenceKind = EvidenceKind.AUTHOR_STATED
    authority: str = AUTHORITY
    channel: str = CHANNEL
    #: Subterra has verified none of these against an independent source.
    verified_by_subterra: bool = False
    #: What a reader might wrongly take this to mean.
    does_not_establish: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "id": self.id, "claim": self.claim, "kind": self.kind.value,
            "authority": self.authority, "channel": self.channel,
            "verified_by_subterra": self.verified_by_subterra,
            "does_not_establish": list(self.does_not_establish),
        }


CLAIMS: tuple[AuthorClaim, ...] = (
    AuthorClaim(
        id="gnss-elevation-is-ellipsoidal",
        claim=("the GNSS-derived elevation values in the exported SEG-Y files are "
               "stored as ellipsoidal heights (WGS84) rather than NAP heights"),
        does_not_establish=(
            "which SEG-Y trace-header field holds that ellipsoidal height -- the "
            "4TU files carry TWO per-trace elevation fields and the author names "
            "neither",
            "a numerical ground elevation for any particular trace",
            "that Subterra's `record.elevation` currently holds the ellipsoidal value",
        ),
    ),
    AuthorClaim(
        id="radarmap-can-transform-to-rd-nap",
        claim=("within RadarMap the GNSS elevations can be transformed to RD/NAP "
               "coordinates and elevations"),
        does_not_establish=(
            "that any such transform was applied to the published files",
            "a geoid model, its version, or a separation value",
        ),
    ),
    AuthorClaim(
        id="gnss-antenna-height-accounted-for",
        claim=("the RTK measurements used a GNSS rover with a constant antenna "
               "height, and that antenna-height offset was already accounted for "
               "during acquisition"),
        does_not_establish=(
            "anything about the GPR antenna -- this is the GNSS ROVER's antenna, "
            "and a GNSS antenna-height correction is not a GPR time-zero correction",
            "that the GPR depth axis begins at the ground",
            "a numerical antenna height",
        ),
    ),
    AuthorClaim(
        id="no-time-zero-or-air-gap-correction",
        claim=("the published SEG-Y files contain the original acquisition data; no "
               "time-zero correction or air-gap removal was applied, so the ground "
               "surface does not necessarily correspond to depth zero and an "
               "air-path contribution remains present in the data"),
        does_not_establish=(
            "a numerical time-zero offset, in nanoseconds or in metres",
            "a numerical air-gap thickness",
            "a propagation velocity",
            "a corrected time zero, or any depth conversion",
        ),
    ),
)


@dataclass(frozen=True)
class OpenQuestionForAuthor:
    """
    A question this response did NOT answer, phrased so it could be asked next.

    The first one is the whole reason the vertical chain has not moved further:
    the author settled WHAT the elevations are and not WHICH field holds them,
    and the two candidates differ by 42-45 m.
    """
    id: str
    question: str
    blocks: str
    why_it_matters: str
    status: str = "OUTSTANDING -- not asked"
    #: Set where Subterra has measured something that narrows the question.
    subterra_evidence: str = ""


OPEN_QUESTIONS: tuple[OpenQuestionForAuthor, ...] = (
    OpenQuestionForAuthor(
        id="which-header-holds-the-ellipsoidal-height",
        question=("Which SEG-Y trace-header field holds the WGS84 ellipsoidal "
                  "height -- Receiver Group Elevation (bytes 41-44) or Source "
                  "Surface Elevation (bytes 45-48)?"),
        blocks="applying the declared vertical datum to a stored elevation value",
        why_it_matters=("the two fields differ by 42.2-45.2 m depending on site, so "
                        "attaching the datum to the wrong one puts a ~44 m error "
                        "into every elevation this platform reports"),
        status="ANSWERED BY MEASUREMENT -- no author question needed",
        subterra_evidence=(
            "RESOLVED by comparison against AHN, the Dutch national terrain model "
            "(PDOK, NAP orthometric), across 366,019 traces in 107 activities and "
            "12 sites. Bytes 41-44 track AHN to -0.83 m mean; bytes 45-48 sit "
            "+43.38 m above it. The difference varies 42.217-45.206 m and "
            "correlates with latitude at -0.999 (planar R^2 0.998, residual sd "
            "0.034 m), which is geoid behaviour and not a constant instrument "
            "offset -- and it matches the published NL separation range (41 m "
            "Groningen to 47 m Limburg) in both magnitude and north-south "
            "gradient. So bytes 45-48 hold the ellipsoidal GNSS height and bytes "
            "41-44 an orthometric NAP-like height. Hypothesis A is REJECTED: it "
            "would put the ground ~44 m below what AHN measures. See "
            "docs/4tu-elevation-field-identification.md"),
    ),
    OpenQuestionForAuthor(
        id="time-zero-offset-magnitude",
        question=("What is the time-zero offset, or the antenna-to-ground air gap, "
                  "for the published acquisitions -- in nanoseconds or in metres?"),
        blocks="relating the GPR depth axis to the ground surface",
        why_it_matters=("the author establishes that the offset EXISTS and is "
                        "uncorrected; without its magnitude no depth on this "
                        "dataset can be referred to the ground"),
        status=("OUTSTANDING -- sent by email on 2026-08-15 (operator-stated); "
                "awaiting reply; letter body at docs/4tu-author-letter-draft.md"),
        subterra_evidence=(
            "NARROWED, NOT ANSWERED, by Subterra's own measurement and derivation -- "
            "the question stays OUTSTANDING because none of this is the author's "
            "confirmation. schemas.time_zero's metadata_instrument_time_zero reads the "
            "real SEG-Y DelayRecordingTime header field (a standard, documented field, "
            "not a reinterpreted vendor one) and MEASURES a real, nonzero, per-line "
            "value: 2.641 ns (01.1/Path8), 2.446 ns (01.5/Path1), 0.88 ns (06.1/Path1), "
            "2.25 ns (012.8/Path1) -- genuinely different line to line, so no single "
            "dataset-wide constant would be honest even if the author supplies one. "
            "scripts/four_tu_topographic_correction_audit.py additionally found that "
            "even after that per-line correction, the antenna's height above ground "
            "varies enough WITHIN a line (5-16 cm, all 4 lines checked) to add a "
            "further material per-trace refinement (0.19-0.60 ns, exceeding each "
            "line's own ~0.097 ns sample interval). None of this tells us whether "
            "DelayRecordingTime, for THIS instrument, means instrument electronic "
            "delay, air-gap, or both combined -- only the author's own knowledge of "
            "the acquisition setup can settle that, which is exactly why the letter "
            "still asks. See docs/roadmap.md's Time-zero correction and Velocity "
            "model estimation rows."
        ),
    ),
    OpenQuestionForAuthor(
        id="propagation-velocity",
        question=("Was a propagation velocity determined for any of the surveyed "
                  "sites, and if so by what method (CMP, hyperbola fitting, known "
                  "target depth)?"),
        blocks="converting two-way time to physical depth",
        why_it_matters=("the depth axis Subterra currently shows is derived from a "
                        "converter default of 0.1 m/ns that nobody measured on this "
                        "ground"),
        status=("OUTSTANDING -- sent by email on 2026-08-15 (operator-stated); "
                "awaiting reply; letter body at docs/4tu-author-letter-draft.md"),
    ),
)


@dataclass(frozen=True)
class DimensionAssessment:
    """One spatial/depth dimension, before and after this response."""
    dimension: str
    before: str
    after: str
    basis: EvidenceKind
    changed: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return {"dimension": self.dimension, "before": self.before,
                "after": self.after, "basis": self.basis.value,
                "changed": self.changed, "detail": self.detail}


#: The reassessment the response actually supports. Four dimensions move; four
#: do not, and the ones that do not are the ones a reader would most like to.
REASSESSMENT: tuple[DimensionAssessment, ...] = (
    DimensionAssessment(
        dimension="horizontal reference (CRS)",
        before="available -- per-trace NMEA positions decoded from the headers",
        after="available -- unchanged",
        basis=EvidenceKind.MEASURED_IN_FILE, changed=False,
        detail="the response says nothing about horizontal reference, and nothing needed saying",
    ),
    DimensionAssessment(
        dimension="vertical datum of the GNSS elevation",
        before="UNDECLARED -- the converter recorded the value and refused to name its datum",
        after=("author-stated as WGS84 ellipsoidal, and DECLARED on the platform "
               "against SEG-Y bytes 45-48, attributed to the author, unverified"),
        basis=EvidenceKind.AUTHOR_STATED, changed=True,
        detail=("this is the real gain: the datum was genuinely unknown and is now "
                "stated by the dataset's author. WHICH of the two ~44 m-apart fields "
                "holds it is Subterra's measurement against AHN, not the author's "
                "statement, and the declaration records both parts separately. The "
                "datum is attached to the ACQUISITION ELEVATION and not to the "
                "vertical axis, which remains two-way time from instrument time "
                "zero -- so nothing below the surface moved. See "
                "docs/4tu-vertical-datum.md"),
    ),
    DimensionAssessment(
        dimension="surface elevation profile",
        before="absent -- no surface model was linked, and the line's own elevations had no datum",
        after=("representable -- a per-trace elevation profile with horizontal "
               "positions exists in the file for every trace, awaiting the datum "
               "attachment"),
        basis=EvidenceKind.MEASURED_IN_FILE, changed=True,
        detail=("measured: 314/314 traces on the audited line carry both elevation "
                "fields and a position; the profile varies smoothly along track"),
    ),
    DimensionAssessment(
        dimension="GNSS antenna height",
        before="unknown",
        after="author-stated as constant and already accounted for during acquisition",
        basis=EvidenceKind.AUTHOR_STATED, changed=True,
        detail=("this concerns the GNSS ROVER antenna and the elevation values it "
                "produced. It says nothing about the GPR antenna or its time zero, "
                "and must not be read as a depth-origin offset"),
    ),
    DimensionAssessment(
        dimension="depth-axis origin relative to ground",
        before="BLOCKED -- Subterra assumed time zero is not the ground",
        after=("BLOCKED -- now author-CONFIRMED that it is not the ground, with no "
               "magnitude given"),
        basis=EvidenceKind.AUTHOR_STATED, changed=True,
        detail=("the state does not move, but its basis does: a cautious Subterra "
                "default became an established fact about the data. The magnitude "
                "remains the blocker"),
    ),
    DimensionAssessment(
        dimension="propagation velocity",
        before="BLOCKED -- converter default of 0.1 m/ns, uncalibrated",
        after="BLOCKED -- unchanged; the response does not mention velocity",
        basis=EvidenceKind.UNKNOWN, changed=False,
    ),
    DimensionAssessment(
        dimension="vertical registration of subsurface points",
        before="BLOCKED",
        after="BLOCKED -- needs the depth origin AND a velocity, and has neither",
        basis=EvidenceKind.UNKNOWN, changed=False,
    ),
    DimensionAssessment(
        dimension="absolute elevation of a subsurface reflector",
        before="BLOCKED",
        after=("BLOCKED -- the surface side is now nearly resolvable, the subsurface "
               "side is not"),
        basis=EvidenceKind.UNKNOWN, changed=False,
        detail=("an absolute elevation needs surface elevation MINUS depth below "
                "surface; the response advances the first term and leaves the second "
                "entirely open"),
    ),
)


def changed_dimensions() -> tuple[DimensionAssessment, ...]:
    return tuple(d for d in REASSESSMENT if d.changed)


def still_blocked() -> tuple[DimensionAssessment, ...]:
    return tuple(d for d in REASSESSMENT if d.after.startswith("BLOCKED"))


def as_dict() -> dict:
    return {
        "authority": AUTHORITY,
        "authority_role": AUTHORITY_ROLE,
        "channel": CHANNEL,
        "received_at": RECEIVED_AT,
        "verified_by_subterra": False,
        "response_verbatim": RESPONSE_VERBATIM,
        "claims": [c.as_dict() for c in CLAIMS],
        "open_questions": [
            {"id": q.id, "question": q.question, "blocks": q.blocks,
             "why_it_matters": q.why_it_matters, "status": q.status,
             "subterra_evidence": q.subterra_evidence}
            for q in OPEN_QUESTIONS
        ],
        "reassessment": [d.as_dict() for d in REASSESSMENT],
    }
