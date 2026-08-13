"""
The 4TU author response, and the states it does and does not move.

WHY THESE TESTS EXIST. An author reply is the most tempting kind of evidence to
over-read: it arrives from an authority, it is written in confident prose, and it
resolves something that has been blocked for stages. The failure mode is not
ignoring it -- it is quietly promoting "the author says the elevations are
ellipsoidal" into "our elevation field is ellipsoidal", which is a different
claim and, on this dataset, a ~44 m error.

So these hold the boundary: what the author stated, what Subterra measured, what
Subterra inferred, and the fact that the depth chain is exactly as blocked as it
was before -- with a better-founded reason.
"""
import pytest

from evidence.fourtu_author import (
    AUTHORITY, CLAIMS, OPEN_QUESTIONS, REASSESSMENT, RESPONSE_VERBATIM,
    EvidenceKind, as_dict, changed_dimensions, still_blocked,
)


def claim(claim_id: str):
    return next(c for c in CLAIMS if c.id == claim_id)


def dimension(name: str):
    return next(d for d in REASSESSMENT if d.dimension == name)


# ---------------------------------------------------------------------------
# attribution
# ---------------------------------------------------------------------------

def test_the_authority_is_the_author_not_subterra():
    assert AUTHORITY == "Dr. ter Huurne"
    assert all(c.authority == "Dr. ter Huurne" for c in CLAIMS)


def test_nothing_is_claimed_as_verified_by_subterra():
    """Subterra has checked none of this against an independent source."""
    assert all(c.verified_by_subterra is False for c in CLAIMS)
    assert as_dict()["verified_by_subterra"] is False


def test_every_author_claim_is_typed_as_author_stated():
    assert all(c.kind is EvidenceKind.AUTHOR_STATED for c in CLAIMS)


def test_the_response_is_stored_verbatim():
    """Quoted, not paraphrased, so the claims can be checked against the words."""
    assert "ellipsoidal heights (WGS84)" in RESPONSE_VERBATIM
    assert "No time-zero correction or air-gap removal was applied" in RESPONSE_VERBATIM


def test_no_date_is_invented_for_a_response_that_carries_none():
    assert as_dict()["received_at"] is None


# ---------------------------------------------------------------------------
# what the author did NOT establish
# ---------------------------------------------------------------------------

def test_no_numerical_offset_velocity_or_depth_is_recorded_anywhere():
    """
    The response establishes that a time-zero offset EXISTS and gives no
    magnitude. A number appearing here would be one nobody supplied.
    """
    payload = str(as_dict())
    for invented in ("origin_offset_m", "time_zero_ns", "air_gap_m",
                     "velocity_m_per_ns=", "0.1 m/ns for this site"):
        assert invented not in payload


def test_the_ellipsoidal_claim_does_not_name_a_header_field():
    disclaimers = " ".join(claim("gnss-elevation-is-ellipsoidal").does_not_establish)
    assert "which SEG-Y trace-header field" in disclaimers
    assert "TWO per-trace elevation fields" in disclaimers


def test_the_gnss_antenna_claim_is_not_a_gpr_time_zero_claim():
    """
    The single most inviting misreading in the response. The rover's antenna
    height is a GNSS correction; the GPR's time zero is a different instrument
    and a different quantity.
    """
    disclaimers = " ".join(claim("gnss-antenna-height-accounted-for").does_not_establish)
    assert "GNSS ROVER's antenna" in disclaimers
    assert "not a GPR time-zero correction" in disclaimers
    assert "the GPR depth axis begins at the ground" in disclaimers
    assert "numerical antenna height" in disclaimers


def test_the_time_zero_claim_withholds_every_number():
    disclaimers = " ".join(claim("no-time-zero-or-air-gap-correction").does_not_establish)
    for withheld in ("numerical time-zero offset", "numerical air-gap thickness",
                     "propagation velocity", "depth conversion"):
        assert withheld in disclaimers


# ---------------------------------------------------------------------------
# the reassessment
# ---------------------------------------------------------------------------

def test_the_depth_chain_is_still_blocked():
    """
    The headline restraint. An author reply arrived and physical depth is
    exactly as unavailable as it was.
    """
    blocked = {d.dimension for d in still_blocked()}
    assert "propagation velocity" in blocked
    assert "depth-axis origin relative to ground" in blocked
    assert "vertical registration of subsurface points" in blocked
    assert "absolute elevation of a subsurface reflector" in blocked


def test_the_depth_origin_state_did_not_move_but_its_basis_did():
    d = dimension("depth-axis origin relative to ground")
    assert d.before.startswith("BLOCKED") and d.after.startswith("BLOCKED")
    assert d.changed is True, "the basis changed even though the state did not"
    assert d.basis is EvidenceKind.AUTHOR_STATED


def test_the_vertical_datum_is_stated_but_not_yet_attachable():
    d = dimension("vertical datum of the GNSS elevation")
    assert d.basis is EvidenceKind.AUTHOR_STATED
    assert "NOT YET ATTACHABLE" in d.after


def test_the_surface_profile_is_measured_in_file_not_author_stated():
    """
    Subterra measured this one. Attributing it to the author would credit them
    with something they did not say.
    """
    d = dimension("surface elevation profile")
    assert d.basis is EvidenceKind.MEASURED_IN_FILE


def test_the_horizontal_reference_did_not_change():
    assert dimension("horizontal reference (CRS)").changed is False


def test_velocity_is_untouched_by_the_response():
    d = dimension("propagation velocity")
    assert d.changed is False
    assert d.basis is EvidenceKind.UNKNOWN


def test_exactly_the_dimensions_with_evidence_are_marked_changed():
    changed = {d.dimension for d in changed_dimensions()}
    assert changed == {
        "vertical datum of the GNSS elevation",
        "surface elevation profile",
        "GNSS antenna height",
        "depth-axis origin relative to ground",
    }


# ---------------------------------------------------------------------------
# the questions this response did not answer
# ---------------------------------------------------------------------------

def test_the_field_mapping_question_is_recorded_with_its_stakes():
    q = next(q for q in OPEN_QUESTIONS
             if q.id == "which-header-holds-the-ellipsoidal-height")
    assert "44 m error" in q.why_it_matters


def test_the_field_mapping_question_was_answered_by_measurement_not_by_the_author():
    """
    UPDATED AFTER THE ELEVATION-FIELD INVESTIGATION. This question was
    OUTSTANDING because the author named neither field. It was then settled by
    comparing both against an independent national terrain model -- so its
    status must say ANSWERED, and must say answered by MEASUREMENT, because
    recording it as author-stated would credit Dr. ter Huurne with something
    they did not say.
    """
    q = next(q for q in OPEN_QUESTIONS
             if q.id == "which-header-holds-the-ellipsoidal-height")
    assert "ANSWERED BY MEASUREMENT" in q.status
    assert "no author question needed" in q.status
    assert "AHN" in q.subterra_evidence
    assert "REJECTED" in q.subterra_evidence


def test_subterra_s_own_measurement_stays_separated_from_the_author_s_words():
    """
    The resolution is Subterra's measurement, and it lives in
    `subterra_evidence` -- never in `claim`, which is reserved for what the
    author actually wrote.
    """
    q = next(q for q in OPEN_QUESTIONS
             if q.id == "which-header-holds-the-ellipsoidal-height")
    assert "42.217-45.206 m" in q.subterra_evidence
    assert "366,019 traces" in q.subterra_evidence

    ellipsoidal = claim("gnss-elevation-is-ellipsoidal")
    assert "AHN" not in ellipsoidal.claim, \
        "the author said nothing about AHN; that is Subterra's evidence"
    assert "bytes 45-48" not in ellipsoidal.claim, \
        "the author named no header field"


def test_the_questions_the_data_cannot_answer_are_still_outstanding():
    """
    Identifying the elevation field settles nothing about depth. No request has
    been sent for these two, and claiming otherwise would invent one.
    """
    remaining = {q.id: q for q in OPEN_QUESTIONS
                 if q.id != "which-header-holds-the-ellipsoidal-height"}
    assert set(remaining) == {"time-zero-offset-magnitude", "propagation-velocity"}
    assert all(q.status.startswith("OUTSTANDING") for q in remaining.values())


def test_the_remaining_questions_cover_the_blocked_chain():
    ids = {q.id for q in OPEN_QUESTIONS}
    assert "time-zero-offset-magnitude" in ids
    assert "propagation-velocity" in ids
