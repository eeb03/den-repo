"""
Recording a spatial declaration, and applying it to the frames.

TWO WRITES, DELIBERATELY SEPARATE. A declaration is stored as an append-only
row -- who claimed what, when, on whose authority -- and then applied to the
`SurveyFrame` so every existing consumer (`views.resolve`,
`vertical_reference.assess`, the dataset report, `frame_provenance`) keeps
working without knowing this module exists. The row is the audit trail; the
frame is the value. Storing only the frame would lose the claim; storing only
the row would leave every reader to reimplement its interpretation.

THE RAW MEASUREMENT IS NEVER REWRITTEN. Applying a declaration edits frame
METADATA -- the reference a measurement is expressed in -- and never a measured
value. The one apparent exception proves the rule: `apply_geo_tie` writes
`record.registered_position` while leaving `record.position` exactly as the
instrument reported it, so a bad tie can be replaced without having destroyed
what was measured underneath it. `position_provenance` keeps native, registered
and derived distinguishable for ever after.

EVERY DECLARATION BECOMES AN ASSUMPTION ON THE FRAME. `Assumption(key, value,
basis, verified)` already exists and is already surfaced by `frame_provenance`
and the dataset report, so a user's velocity shows up next to the converter's
own assumptions in the same list, phrased the same way, with `verified=False`
because nobody checked it. Nothing a user types is ever promoted to a
measurement.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from database.frames_store import load_frames, save_frames, synthesize_frames_from_records
from database.models import SpatialDeclaration, gen_uuid
from database.records_store import load_records, save_records
from schemas.spatial import (
    AcquisitionElevationDatum,
    AffineControlPoint,
    Assumption,
    AxisKind,
    ControlPoint,
    CRSKind,
    CRSProvenance,
    NorthReference,
    SpatialRef,
    VerticalDatum,
)
from schemas.spatial_reference import DeclarationKind
from utils.logger import get_logger

logger = get_logger(__name__)


class DeclarationError(ValueError):
    """The declaration cannot be accepted as stated."""


def _require(value: Any, name: str) -> Any:
    if value in (None, "", [], {}):
        raise DeclarationError(f"{name} is required")
    return value


# ---------------------------------------------------------------------------
# validation, per kind
# ---------------------------------------------------------------------------

def _validated_crs(value: dict) -> dict:
    """
    A horizontal reference, asserted by somebody.

    ALWAYS `SUPPLIED_BY_CALLER`. A user cannot declare that the SOURCE declared
    something -- that provenance belongs to the file, is set by the converter,
    and would be a forgery if the interface could write it. Nor can a user mark
    a CRS `inferred`: an inference needs a stated justification and a mechanism,
    and typing a code into a box is neither.
    """
    code = str(_require(value.get("code"), "code")).strip()
    if not code:
        raise DeclarationError("code is required")
    kind = str(value.get("kind") or CRSKind.PROJECTED.value)
    try:
        crs_kind = CRSKind(kind)
    except ValueError:
        raise DeclarationError(
            f"kind must be one of {[k.value for k in CRSKind]}, not {kind!r}")
    if crs_kind not in (CRSKind.GEOGRAPHIC, CRSKind.PROJECTED):
        raise DeclarationError(
            f"an EPSG code is not meaningful for a {crs_kind.value} frame; such a frame has "
            "no Earth reference by definition. Declare a GeoTie instead.")
    # Constructed here so `SpatialRef`'s own validators reject a code with no
    # provenance rather than this module re-checking what the schema owns.
    ref = SpatialRef(
        kind=crs_kind, code=code, crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER,
        name=value.get("name") or "supplied by a caller through the spatial workflow",
        horizontal_units="deg" if crs_kind == CRSKind.GEOGRAPHIC else "m",
    )
    return ref.model_dump(mode="json")


#: Which stored quantity a vertical datum is being declared FOR.
#:
#: A survey frame can carry more than one vertical quantity, and they do not
#: share a datum. The 4TU GPR lines are the case that forced this: the frame's
#: vertical AXIS is two-way time measured from instrument time zero, which has
#: no geodetic datum at all, while the acquisition ELEVATION in the SEG-Y
#: headers is a GNSS height that does. Declaring one datum for "the frame" would
#: have to pick one of those and silently mislabel the other.
VERTICAL_DATUM_APPLIES_TO = {
    "acquisition_elevation": (
        "the acquisition elevation stored with the survey -- the GNSS or "
        "levelling height of the instrument position, not the depth axis"),
    "vertical_axis": (
        "the frame's own vertical axis, for an acquisition whose axis IS an "
        "elevation or depth rather than a time"),
}
DEFAULT_VERTICAL_DATUM_APPLIES_TO = "vertical_axis"


def _validated_vertical_datum(value: dict) -> dict:
    """
    What the vertical coordinates are measured from, and WHICH coordinates.

    `applies_to` defaults to `vertical_axis`, which is what every caller before
    it meant and keeps their behaviour unchanged. Naming
    `acquisition_elevation` says the datum describes the stored elevation and
    not the axis -- the only honest option when the axis is a time.
    """
    code = str(_require(value.get("code"), "code")).strip()
    applies_to = (value.get("applies_to") or DEFAULT_VERTICAL_DATUM_APPLIES_TO)
    if applies_to not in VERTICAL_DATUM_APPLIES_TO:
        raise DeclarationError(
            f"applies_to must be one of {', '.join(sorted(VERTICAL_DATUM_APPLIES_TO))}; "
            f"got {applies_to!r}")

    datum = VerticalDatum(
        code=code, provenance=CRSProvenance.SUPPLIED_BY_CALLER,
        name=value.get("name") or code)
    out = datum.model_dump(mode="json")
    out["applies_to"] = applies_to
    # Free text naming the exact stored field, where a caller knows it. Carried
    # verbatim so a later reader can tell WHICH of several elevations was meant.
    if value.get("field"):
        out["field"] = str(value["field"]).strip()
    return out


def _validated_antenna_offset(value: dict) -> dict:
    """
    Where the depth/time axis begins, relative to the ground.

    NO DEFAULT, ON EITHER FIELD. An offset of zero is a physical claim -- that
    the reference point was on the ground -- and assuming it is how an
    air-launched survey ends up with every reflector half a metre out. Nor is
    the reference point defaulted: it used to fall back to "sensor phase
    centre", which quietly answered a question the caller had not been asked,
    and a phase-centre height is not an axis-origin offset.

    SIGN: positive means the reference point is ABOVE the ground. Not chosen
    here -- this declaration has recorded `positive_direction: sensor above
    ground` since it was introduced, and inverting it now would silently flip
    every value already declared under it.

    SYNTAX IS NOT PHYSICS. Everything below checks that the number is a finite
    quantity in a representable range. Nothing here checks that it is TRUE, and
    the assessment says so wherever the offset appears.
    """
    from schemas.spatial import DepthOriginOffset, OffsetEvidence, OriginReference

    raw = _require(value.get("offset_m"), "offset_m")
    try:
        offset = float(raw)
    except (TypeError, ValueError):
        raise DeclarationError(f"offset_m {raw!r} is not a number")
    if offset != offset or abs(offset) == float("inf"):
        raise DeclarationError("offset_m is not finite")
    if not -10.0 <= offset <= 10.0:
        # A representability bound, not a law of physics: beyond a few metres
        # this is no longer a sensor-to-ground geometry the platform models, and
        # a mistyped centimetre value lands here rather than in a dataset.
        raise DeclarationError(
            "offset_m must be between -10 and 10 metres; a larger reference-to-ground "
            "offset is not a survey geometry this platform can represent. The unit is "
            "metres -- 45 cm is 0.45, not 45.")

    # REQUIRED CHECKS OUTSIDE THE try. `DeclarationError` subclasses ValueError,
    # so an `except ValueError` around `_require` swallows "this is required"
    # and reports "must be one of ..." instead -- telling a caller who omitted
    # the field to correct a value they never sent.
    raw_from = _require(value.get("measured_from"), "measured_from")
    try:
        measured_from = OriginReference(raw_from)
    except ValueError:
        raise DeclarationError(
            f"measured_from must be one of "
            f"{', '.join(r.value for r in OriginReference)}; only "
            f"{OriginReference.DEPTH_AXIS_ORIGIN.value} answers what vertical "
            f"registration asks")

    raw_evidence = _require(value.get("evidence"), "evidence")
    try:
        evidence = OffsetEvidence(raw_evidence)
    except ValueError:
        raise DeclarationError(
            f"evidence must be one of {', '.join(e.value for e in OffsetEvidence)}")

    declaration = DepthOriginOffset(
        offset_m=offset,
        measured_from=measured_from,
        measured_to=str(value.get("measured_to") or "ground surface"),
        evidence=evidence,
        # Filled in by the route from the declaration's own attribution, so the
        # offset carries its authority wherever the axis travels.
        supplied_by=str(value.get("supplied_by") or "unattributed"),
        note=value.get("note"),
    )
    return declaration.model_dump(mode="json")


def _validated_depth_conversion(value: dict) -> dict:
    """
    A propagation velocity, checked against physically justified bounds.

    Reuses `converters.ids_dt_converter.validate_velocity`, whose bounds are not
    invented -- they are the IDS acquisition software's own MinPropVel/MaxPropVel
    limits, with the upper bound also being the speed of light. Borrowing that
    check keeps one definition of "physically plausible" rather than a second
    that could drift from it.
    """
    from converters.ids_dt_converter import validate_velocity

    velocity, reason = validate_velocity(value.get("velocity_m_per_ns"))
    if velocity is None:
        raise DeclarationError(reason or "a propagation velocity is required")
    return {
        "method": "constant_velocity",
        "velocity_m_per_ns": velocity,
        "basis": str(value.get("basis") or "supplied by a caller; not measured on this site"),
        # Recorded on the conversion itself so no consumer has to look elsewhere
        # to learn that this depth is an assumption.
        "derived": True,
    }


def _validated_geo_tie(value: dict) -> dict:
    """Control points, checked by the existing tie builder."""
    from ingestion.geo_tie import build_geo_tie

    raw_points = _require(value.get("control_points"), "control_points")
    if not isinstance(raw_points, list) or len(raw_points) < 2:
        raise DeclarationError(
            "a GeoTie needs at least two control points: one point fixes a location "
            "but not the line's bearing, so nothing can be interpolated from it")
    try:
        points = [ControlPoint.model_validate(p) for p in raw_points]
    except Exception as exc:  # noqa: BLE001
        raise DeclarationError(f"a control point is not valid: {exc}")

    try:
        tie = build_geo_tie(
            points,
            supplied_by=str(value.get("supplied_by") or "unattributed"),
            max_rms_residual_m=value.get("max_rms_residual_m"),
            applies_to=value.get("applies_to"),
            notes=value.get("notes"),
        )
    except Exception as exc:  # noqa: BLE001 -- GeoTie's own validators
        raise DeclarationError(str(exc))
    return tie.model_dump(mode="json")


def _validated_affine_tie(value: dict) -> dict:
    """Control points for a 2D affine registration, checked by the existing tie builder."""
    from ingestion.affine_tie import build_affine_tie

    raw_points = _require(value.get("control_points"), "control_points")
    if not isinstance(raw_points, list) or len(raw_points) < 3:
        raise DeclarationError(
            "an AffineTie needs at least three control points: a 2D affine map has six "
            "unknowns and three non-collinear point correspondences are the minimum that "
            "can determine it")
    try:
        points = [AffineControlPoint.model_validate(p) for p in raw_points]
    except Exception as exc:  # noqa: BLE001
        raise DeclarationError(f"a control point is not valid: {exc}")

    try:
        tie = build_affine_tie(
            points,
            supplied_by=str(value.get("supplied_by") or "unattributed"),
            max_rms_residual_m=value.get("max_rms_residual_m"),
            applies_to=value.get("applies_to"),
            notes=value.get("notes"),
        )
    except Exception as exc:  # noqa: BLE001 -- AffineTie's own validators
        raise DeclarationError(str(exc))
    return tie.model_dump(mode="json")


def _validated_surface_reference(value: dict) -> dict:
    """
    Another dataset asserted to be this survey's surface.

    ACCEPTING THE LINK IS NOT ACCEPTING THE ANCHOR. This records that somebody
    considers dataset X the surface model for dataset Y. Whether X can actually
    anchor anything is decided by `assess_surface`, which checks the linked
    frames for an elevation axis and a declared datum -- and reports
    `unvalidated` when they are absent, however confidently the link was made.
    """
    surface_id = str(_require(value.get("surface_dataset_id"), "surface_dataset_id")).strip()
    return {"surface_dataset_id": surface_id, "note": value.get("note")}


def _validated_orientation(value: dict) -> dict:
    """
    A claim about antenna heading -- not a track bearing, not an IMU record.

    NO DEFAULT REFERENCE. True, magnetic and grid north disagree by amounts
    that vary with location and date, so a heading with an assumed reference
    would misattribute that difference to the antenna.
    """
    raw_heading = _require(value.get("heading_deg"), "heading_deg")
    try:
        heading = float(raw_heading)
    except (TypeError, ValueError):
        raise DeclarationError(f"heading_deg {raw_heading!r} is not a number")
    if heading != heading or abs(heading) == float("inf"):
        raise DeclarationError("heading_deg is not finite")
    if not 0.0 <= heading < 360.0:
        raise DeclarationError("heading_deg must be within [0, 360)")

    raw_reference = _require(value.get("reference"), "reference")
    try:
        reference = NorthReference(raw_reference)
    except ValueError:
        raise DeclarationError(
            f"reference must be one of {', '.join(r.value for r in NorthReference)}, "
            f"not {raw_reference!r}")

    return {"heading_deg": heading, "reference": reference.value}


_VALIDATORS = {
    DeclarationKind.CRS: _validated_crs,
    DeclarationKind.VERTICAL_DATUM: _validated_vertical_datum,
    DeclarationKind.ANTENNA_OFFSET: _validated_antenna_offset,
    DeclarationKind.DEPTH_CONVERSION: _validated_depth_conversion,
    DeclarationKind.GEO_TIE: _validated_geo_tie,
    DeclarationKind.AFFINE_TIE: _validated_affine_tie,
    DeclarationKind.SURFACE_REFERENCE: _validated_surface_reference,
    DeclarationKind.ORIENTATION: _validated_orientation,
}


def validate_declaration(kind: DeclarationKind, value: dict) -> dict:
    if kind not in _VALIDATORS:
        raise DeclarationError(f"unknown declaration kind {kind!r}")
    if not isinstance(value, dict):
        raise DeclarationError("value must be an object")
    return _VALIDATORS[kind](value)


# ---------------------------------------------------------------------------
# applying a declaration to the frames
# ---------------------------------------------------------------------------

def _assumption_for(kind: DeclarationKind, value: dict, supplied_by: str) -> Assumption:
    """
    The frame-level record of what was asserted and on whose authority.

    `verified=False` on every one of them, without exception. Nothing a person
    types has been checked against anything; a tie's residual is the closest
    this comes, and `build_geo_tie` sets that itself only when three or more
    points were actually fitted.
    """
    described = {
        DeclarationKind.CRS: f"horizontal reference {value.get('code')}",
        # NAMES THE QUANTITY, not just the code. "vertical datum WGS84
        # ellipsoidal" on a frame whose axis is two-way time reads as a claim
        # about the axis; the scope is what makes it true rather than false.
        DeclarationKind.VERTICAL_DATUM: (
            f"vertical datum {value.get('code')} for "
            + ("the acquisition elevation"
               + (f" ({value['field']})" if value.get("field") else "")
               + ", NOT the vertical axis"
               if value.get("applies_to") == "acquisition_elevation"
               else "the vertical axis")),
        DeclarationKind.ANTENNA_OFFSET:
            f"{value.get('offset_m')} m from {value.get('measured_from')} to "
            f"{value.get('measured_to')} ({value.get('evidence')}); positive means the "
            f"reference point is above the ground",
        DeclarationKind.DEPTH_CONVERSION:
            f"propagation velocity {value.get('velocity_m_per_ns')} m/ns",
        DeclarationKind.GEO_TIE:
            f"{len(value.get('control_points') or [])} control point(s)",
        DeclarationKind.AFFINE_TIE:
            f"{len(value.get('control_points') or [])} control point(s), 2D affine",
        DeclarationKind.SURFACE_REFERENCE:
            f"surface model {value.get('surface_dataset_id')}",
        DeclarationKind.ORIENTATION:
            f"antenna heading {value.get('heading_deg')} deg from {value.get('reference')}",
    }[kind]
    # ORIENTATION carries a structured {heading_deg, reference} value rather
    # than the single-scalar `or`-chain below, for two reasons: neither field
    # alone identifies the claim, and a heading of exactly 0.0 (due north) is
    # a real, valid value that the `or`-chain would treat as falsy and skip.
    # `assess_orientation` reads this dict back to name the heading verbatim.
    if kind == DeclarationKind.ORIENTATION:
        assumption_value: Any = {
            "heading_deg": value.get("heading_deg"), "reference": value.get("reference"),
        }
    else:
        assumption_value = (value.get("code") or value.get("velocity_m_per_ns")
                            or value.get("offset_m") or value.get("surface_dataset_id")
                            or supplied_by)
    return Assumption(
        key=f"declared_{kind.value}",
        value=assumption_value,
        basis=(f"SUPPLIED BY CALLER through the spatial reference workflow: {described}, "
               f"asserted by {supplied_by!r}. This is a declaration, not a measurement."),
        verified=False,
    )


def apply_declaration(dataset_id: str, kind: DeclarationKind, value: dict,
                      supplied_by: str, frame_id: Optional[str] = None) -> dict:
    """
    Write the declaration into the dataset's frames.

    Returns a summary of what changed. Raises `DeclarationError` when the
    declaration cannot be applied to what is actually stored -- a velocity for a
    dataset with no time axis, a tie for a dataset with no odometry.
    """
    records = load_records(dataset_id)
    frames = load_frames(dataset_id) or (
        synthesize_frames_from_records(records) if records else [])
    if not frames:
        raise DeclarationError(
            "this dataset has no survey frames, so there is nothing to reference")

    targets = [f for f in frames if frame_id is None or f.frame_id == frame_id]
    if not targets:
        raise DeclarationError(f"no frame {frame_id!r} in this dataset")

    changed: list[str] = []
    #: Frames whose VERTICAL AXIS the typed change deliberately did not touch,
    #: each with a reason. The declaration is still recorded on those frames --
    #: on the quantity it actually describes, and as an attributed assumption.
    axis_untouched: list[dict] = []
    assumption = _assumption_for(kind, value, supplied_by)

    if kind == DeclarationKind.CRS:
        ref = SpatialRef.model_validate(value)
        for frame in targets:
            frame.spatial_ref = ref
            changed.append(frame.frame_id)

    elif kind == DeclarationKind.VERTICAL_DATUM:
        datum = VerticalDatum.model_validate(
            {k: v for k, v in value.items() if k not in ("applies_to", "field")})
        applies_to = value.get("applies_to", DEFAULT_VERTICAL_DATUM_APPLIES_TO)

        for frame in targets:
            # THE DEFAULT IS UNCHANGED, deliberately. A datum declared without
            # `applies_to` lands on the frame's vertical axis exactly as it
            # always has -- that is the Stage 12 workflow (datum, then depth
            # origin, then the dimension settles) and it is the vertical
            # reference of the SURVEY, not a claim about the axis's units.
            #
            # `acquisition_elevation` is the narrower case: the datum describes
            # a stored elevation and says nothing about what the depth axis is
            # referenced to. Writing it onto the axis would answer a question
            # nobody asked, and would advance the vertical-reference dimension
            # on evidence that does not bear on it. It goes to the frame's own
            # slot for that quantity instead -- RECORDED, structurally, just not
            # attached to the axis it does not describe.
            if applies_to == "acquisition_elevation":
                frame.acquisition_elevation_datum = AcquisitionElevationDatum(
                    datum=datum, field=value.get("field"))
                axis_untouched.append({
                    "frame_id": frame.frame_id,
                    "axis_kind": frame.vertical_axis.kind.value,
                    "reason": (
                        f"the datum describes {value.get('field') or 'the acquisition elevation'}, "
                        f"not this frame's vertical axis, which is "
                        f"{frame.vertical_axis.kind.value} measured from "
                        f"{frame.vertical_axis.origin!r}"),
                    "recorded_as": "an attributed assumption on the frame",
                })
                continue
            frame.vertical_axis = frame.vertical_axis.model_copy(
                update={"vertical_datum": datum})
            changed.append(frame.frame_id)

    elif kind == DeclarationKind.DEPTH_CONVERSION:
        eligible = [f for f in targets
                    if f.vertical_axis.kind in (AxisKind.TWO_WAY_TIME_NS,
                                                AxisKind.TWO_WAY_TIME_MS,
                                                AxisKind.TWO_WAY_TIME_S)]
        if not eligible:
            raise DeclarationError(
                "no frame carries a measured time axis, so there is no time for a velocity "
                "to convert. A depth that already exists is not re-derived here.")
        for frame in eligible:
            frame.vertical_axis = frame.vertical_axis.model_copy(update={"conversion": value})
            changed.append(frame.frame_id)

    elif kind == DeclarationKind.ANTENNA_OFFSET:
        # WRITTEN ONTO THE AXIS, which is what changed in stage 12. Before this
        # it was recorded as an assumption and nothing read it, so declaring an
        # offset could never move the assessment: `assess` decided whether the
        # axis zero was the ground by searching a free-text string.
        #
        # IT STILL MOVES NOTHING. `origin`, every sample and every stored depth
        # are untouched; this records the RELATIONSHIP between the axis zero and
        # the ground, which is exactly the missing piece and nothing more. No
        # sample is shifted, because shifting samples is a different operation
        # that needs a velocity this stage deliberately does not supply.
        from schemas.spatial import DepthOriginOffset

        declared_offset = DepthOriginOffset.model_validate(
            {**value, "supplied_by": supplied_by})
        for frame in targets:
            frame.vertical_axis = frame.vertical_axis.model_copy(
                update={"origin_offset": declared_offset})
            changed.append(frame.frame_id)

    elif kind == DeclarationKind.GEO_TIE:
        from ingestion.geo_tie import GeoTie, GeoTieError, apply_geo_tie, tied_spatial_ref

        tie = GeoTie.model_validate(value)
        try:
            registered = apply_geo_tie(records, tie, path_id=tie.applies_to)
        except GeoTieError as exc:
            raise DeclarationError(str(exc))
        # ADDITIVE: `apply_geo_tie` wrote `registered_position` and left every
        # `position` as the instrument reported it.
        save_records(dataset_id, records)
        for frame in targets:
            frame.geo_tie = tie
            frame.registered_spatial_ref = tied_spatial_ref(tie)
            changed.append(frame.frame_id)
        assumption = _assumption_for(kind, value, supplied_by)
        logger.info("geo tie registered %d record(s) in %s", registered, dataset_id)

    elif kind == DeclarationKind.AFFINE_TIE:
        from ingestion.affine_tie import (
            AffineTie, AffineTieError, apply_affine_tie, tied_spatial_ref_for_affine,
        )

        tie = AffineTie.model_validate(value)
        try:
            registered = apply_affine_tie(records, tie, path_id=tie.applies_to)
        except AffineTieError as exc:
            raise DeclarationError(str(exc))
        # ADDITIVE: `apply_affine_tie` wrote `registered_position` and left
        # every `position` as the instrument reported it.
        save_records(dataset_id, records)
        for frame in targets:
            frame.affine_tie = tie
            frame.registered_spatial_ref = tied_spatial_ref_for_affine(tie)
            changed.append(frame.frame_id)
        assumption = _assumption_for(kind, value, supplied_by)
        logger.info("affine tie registered %d record(s) in %s", registered, dataset_id)

    elif kind == DeclarationKind.SURFACE_REFERENCE:
        changed = [f.frame_id for f in targets]

    elif kind == DeclarationKind.ORIENTATION:
        # A claim about antenna heading, not a track bearing and not an IMU
        # record. Nothing structured on the frame describes an orientation --
        # unlike CRS or the vertical axis, there is no dedicated field to
        # write. The declaration lives entirely as the frame Assumption
        # attached below, which `assess_orientation` reads back.
        changed = [f.frame_id for f in targets]

    attributed = set(changed) | {s["frame_id"] for s in axis_untouched}
    for frame in frames:
        if frame.frame_id in attributed:
            frame.assumptions = [
                a for a in (frame.assumptions or []) if a.key != assumption.key
            ] + [assumption]

    save_frames(dataset_id, frames)
    return {"frames_changed": changed,
            "vertical_axis_not_changed": axis_untouched,
            "assumption": assumption.model_dump(mode="json")}


# ---------------------------------------------------------------------------
# the declaration log
# ---------------------------------------------------------------------------

def active_declarations(db, dataset_id: str) -> list[SpatialDeclaration]:
    return (
        db.query(SpatialDeclaration)
        .filter(SpatialDeclaration.dataset_id == dataset_id,
                SpatialDeclaration.superseded_at.is_(None))
        .order_by(SpatialDeclaration.created_at.desc())
        .all()
    )


def all_declarations(db, dataset_id: str) -> list[SpatialDeclaration]:
    return (
        db.query(SpatialDeclaration)
        .filter(SpatialDeclaration.dataset_id == dataset_id)
        .order_by(SpatialDeclaration.created_at.desc())
        .all()
    )


def record_declaration(db, dataset_id: str, kind: DeclarationKind, value: dict,
                       supplied_by: str, user_id: Optional[str],
                       frame_id: Optional[str] = None,
                       note: Optional[str] = None) -> SpatialDeclaration:
    """
    Append the claim, superseding any earlier claim of the same kind and scope.

    SUPERSEDED, NOT DELETED. The earlier row stays, with the id of the one that
    replaced it, so "what did we think the datum was in March, and who said so"
    remains answerable after somebody corrects it. That question is the reason
    for keeping a log rather than a column.
    """
    now = datetime.utcnow()
    row = SpatialDeclaration(
        id=gen_uuid(), dataset_id=dataset_id, frame_id=frame_id, kind=kind.value,
        value=value, supplied_by=supplied_by, note=note,
        declared_by_user_id=user_id, created_at=now)

    superseded = (
        db.query(SpatialDeclaration)
        .filter(SpatialDeclaration.dataset_id == dataset_id,
                SpatialDeclaration.kind == kind.value,
                SpatialDeclaration.frame_id.is_(frame_id) if frame_id is None
                else SpatialDeclaration.frame_id == frame_id,
                SpatialDeclaration.superseded_at.is_(None))
        .all()
    )
    for previous in superseded:
        previous.superseded_at = now
        previous.superseded_by = row.id

    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("spatial declaration %s recorded for %s by %r",
                kind.value, dataset_id, supplied_by)
    return row


def stale_products(db, dataset_id: str, declarations) -> list[str]:
    """
    Derived products computed BEFORE the newest spatial declaration.

    A CRS, a datum, a tie or a velocity changes what the data means, so anything
    computed from the old reference is describing a different world. Nothing is
    recomputed here -- fusion is expensive and re-running it silently would hide
    the very change this is reporting. The state is made explicit and the
    decision is left to somebody who can see it.
    """
    if not declarations:
        return []
    newest = max(d.created_at for d in declarations if d.created_at)

    from database.models import FusionSample

    stale = [
        f"fusion sample {s.id}" for s in db.query(FusionSample).all()
        if dataset_id in (s.dataset_ids or []) and s.created_at and s.created_at < newest
    ]
    return stale
