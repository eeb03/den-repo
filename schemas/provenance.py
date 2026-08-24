"""
One vocabulary for "where did this number come from", across every quantity
Subterra carries.

WHY THIS EXISTS. The platform already records provenance carefully, but in
five unrelated shapes: `SpatialRef.crs_provenance`, `VerticalDatum.provenance`,
`position_provenance()`'s native/registered/derived, the `Assumption` list on a
frame, and ad-hoc metadata keys like `velocity_source`. Each is right on its
own, and together they are impossible to render: a viewer cannot ask "is this
measured?" without knowing which of five mechanisms answers for that field.

This module is a READ-ONLY PROJECTION of those five. It stores nothing and
adds no new source of truth -- every classification below is computed from
fields the frame or record already carries, so a converter that changes what
it records changes what this reports, with no second place to update.

THE CLASSES ARE ORDERED BY HOW MUCH THE DATA VOUCHES FOR THEM:

    measured            an instrument recorded it
    declared_by_source  the file states it about itself
    supplied_by_caller  a human asserted it at ingest, for this dataset only
    derived             computed from other quantities by a stated rule
    inferred            deduced from the data's own values, with a justification
    assumed             taken as true without evidence, and labelled as such
    unavailable         genuinely absent -- not zero, not defaulted

`unavailable` is a first-class answer. A viewer that cannot distinguish
"depth is 0 m" from "there is no depth" will eventually draw the second as the
first, which is the failure this whole model exists to prevent.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from schemas.spatial import (
    POSITION_DERIVED, POSITION_REGISTERED, AxisKind, CRSProvenance, PositionKind,
    effective_position, position_provenance,
)


#: What `preprocess_trace_local_anomaly` leaves in `record.signal` once it has
#: run -- shared verbatim with `schemas.dataset_report.build_signal_chain` so
#: the provenance pane and the signal chain cannot describe the same
#: overwritten samples in two different sentences.
LOCAL_ANOMALY_BASIS = (
    "ring-based local anomaly z-score, a statistic derived from the "
    "processed amplitude -- not a physical unit"
)


class ProvenanceClass(str, Enum):
    MEASURED = "measured"
    DECLARED_BY_SOURCE = "declared_by_source"
    SUPPLIED_BY_CALLER = "supplied_by_caller"
    DERIVED = "derived"
    INFERRED = "inferred"
    ASSUMED = "assumed"
    UNAVAILABLE = "unavailable"


#: How much the data vouches for a class, 0 (least) to 5 (most). Used only for
#: sorting and for `weakest_class`, never to collapse classes into a score --
#: "assumed" and "inferred" are different kinds of doubt, not different amounts.
CLASS_STRENGTH: dict[ProvenanceClass, int] = {
    ProvenanceClass.UNAVAILABLE: 0,
    ProvenanceClass.ASSUMED: 1,
    ProvenanceClass.INFERRED: 2,
    ProvenanceClass.DERIVED: 3,
    ProvenanceClass.SUPPLIED_BY_CALLER: 4,
    ProvenanceClass.DECLARED_BY_SOURCE: 5,
    ProvenanceClass.MEASURED: 5,
}

#: Direct translation of the CRS vocabulary. `CRSProvenance.NONE` becomes
#: UNAVAILABLE rather than being dropped, so "no CRS" renders as a state.
_FROM_CRS: dict[CRSProvenance, ProvenanceClass] = {
    CRSProvenance.DECLARED_BY_SOURCE: ProvenanceClass.DECLARED_BY_SOURCE,
    CRSProvenance.SUPPLIED_BY_CALLER: ProvenanceClass.SUPPLIED_BY_CALLER,
    CRSProvenance.INFERRED: ProvenanceClass.INFERRED,
    CRSProvenance.NONE: ProvenanceClass.UNAVAILABLE,
}


class QuantityProvenance(BaseModel):
    """
    One renderable statement: this quantity, this class, and why.

    `basis` is required and non-empty. A provenance label with no
    justification is decoration; forcing the sentence is what keeps the
    classification honest when a converter changes.
    """
    quantity: str
    provenance: ProvenanceClass
    basis: str = Field(..., min_length=1)
    value: Optional[Any] = None
    verified: Optional[bool] = None
    source: Optional[str] = None       # which field or module answered


def _q(quantity, provenance, basis, value=None, verified=None, source=None):
    return QuantityProvenance(quantity=quantity, provenance=provenance, basis=basis,
                              value=value, verified=verified, source=source)


def frame_provenance(frame) -> list[QuantityProvenance]:
    """
    Everything a SurveyFrame can say about itself.

    Reads `spatial_ref`, `vertical_axis` (including its datum and conversion)
    and the `assumptions` list. Nothing is invented: a frame that declares
    nothing produces UNAVAILABLE entries, which is the honest rendering.
    """
    out: list[QuantityProvenance] = []
    ref = getattr(frame, "spatial_ref", None)
    if ref is not None:
        cls = _FROM_CRS.get(ref.crs_provenance, ProvenanceClass.UNAVAILABLE)
        out.append(_q(
            "horizontal_crs", cls,
            ref.name or (f"{ref.kind.value} reference"
                         if hasattr(ref.kind, "value") else "spatial reference"),
            value=ref.code, source="SurveyFrame.spatial_ref"))

    axis = getattr(frame, "vertical_axis", None)
    if axis is not None:
        # The axis itself: a time or elevation axis the instrument recorded is
        # measured; a depth axis only exists because something converted it.
        if axis.kind == AxisKind.NONE:
            out.append(_q("vertical_axis", ProvenanceClass.UNAVAILABLE,
                          "the frame declares no vertical axis",
                          source="SurveyFrame.vertical_axis"))
        elif axis.kind == AxisKind.DEPTH_M:
            out.append(_q("vertical_axis", ProvenanceClass.DERIVED,
                          f"depth axis in {axis.units}, measured from {axis.origin!r}",
                          value=axis.kind.value, source="SurveyFrame.vertical_axis"))
        else:
            out.append(_q("vertical_axis", ProvenanceClass.MEASURED,
                          f"{axis.kind.value} recorded by the instrument, "
                          f"origin {axis.origin!r}",
                          value=axis.kind.value, source="SurveyFrame.vertical_axis"))

        datum = getattr(axis, "vertical_datum", None)
        if datum is not None and datum.code:
            out.append(_q("vertical_datum",
                          _FROM_CRS.get(datum.provenance, ProvenanceClass.UNAVAILABLE),
                          datum.name or "vertical datum",
                          value=datum.code, source="VerticalAxis.vertical_datum"))
        else:
            out.append(_q("vertical_datum", ProvenanceClass.UNAVAILABLE,
                          "no vertical datum is declared, so elevations cannot be "
                          "compared with another source",
                          source="VerticalAxis.vertical_datum"))

        conv = getattr(axis, "conversion", None)
        if conv:
            out.append(_q("depth_conversion", ProvenanceClass.DERIVED,
                          f"{conv.get('method')}: {conv.get('formula')}",
                          value=conv.get("velocity_m_per_ns"),
                          source="VerticalAxis.conversion"))
        else:
            out.append(_q("depth_conversion", ProvenanceClass.UNAVAILABLE,
                          "no depth conversion was applied; records carry the "
                          "vertical axis above and no depth",
                          source="VerticalAxis.conversion"))

    # Frame assumptions carry their own basis and verified flag already. A
    # verified assumption is a measurement someone checked; an unverified one
    # is exactly what "assumed" means.
    for a in getattr(frame, "assumptions", []) or []:
        basis = (a.basis or "").lower()
        if a.verified:
            cls = ProvenanceClass.MEASURED if "measured" in basis else ProvenanceClass.DERIVED
        elif "supplied by caller" in basis or "asserted" in basis:
            cls = ProvenanceClass.SUPPLIED_BY_CALLER
        elif "derived from" in basis:
            cls = ProvenanceClass.DERIVED
        elif "declared by" in basis:
            cls = ProvenanceClass.DECLARED_BY_SOURCE
        elif "inferred" in basis:
            cls = ProvenanceClass.INFERRED
        else:
            cls = ProvenanceClass.ASSUMED
        out.append(_q(f"assumption:{a.key}", cls, a.basis, value=a.value,
                      verified=a.verified, source="SurveyFrame.assumptions"))
    return out


def record_provenance(record, frame=None) -> list[QuantityProvenance]:
    """
    Everything one record can say. `frame` is optional but sharpens the answer
    for depth and elevation, which the frame is what actually knows about.
    """
    out: list[QuantityProvenance] = []
    meta = getattr(record, "metadata", {}) or {}

    # --- position ---
    pos = effective_position(record)
    kind = getattr(pos, "kind", None)
    if pos is None or kind == PositionKind.NONE:
        reason = getattr(pos, "reason", None) or "no position was recorded"
        out.append(_q("position", ProvenanceClass.UNAVAILABLE, reason,
                      source="SubterraRecord.position"))
    else:
        stage = position_provenance(record)
        if stage == POSITION_REGISTERED:
            cls, basis = (ProvenanceClass.SUPPLIED_BY_CALLER,
                          "placed on Earth by a caller-supplied GeoTie; the "
                          "acquisition's own coordinate is preserved in `position`")
        elif stage == POSITION_DERIVED:
            cls, basis = (ProvenanceClass.DERIVED,
                          "computed from a native position plus a declared CRS")
        else:
            src = meta.get("position_source")
            cls = ProvenanceClass.MEASURED
            basis = f"the acquisition's own coordinate ({src})" if src else \
                "the acquisition's own coordinate"
        out.append(_q("position", cls, basis, value=str(kind),
                      source=f"position_provenance={stage}"))

    # --- signal ---
    if meta.get("anomaly_reliable") is not None:
        out.append(_q("signal", ProvenanceClass.DERIVED, LOCAL_ANOMALY_BASIS,
                      verified=bool(meta.get("anomaly_reliable")),
                      source="preprocess_trace_local_anomaly"))
    elif meta.get("processing_applied"):
        out.append(_q("signal", ProvenanceClass.DERIVED,
                      f"processed amplitude: {meta['processing_applied']}",
                      source="process_gpr_traces"))
    else:
        out.append(_q("signal", ProvenanceClass.MEASURED,
                      "amplitude as recorded by the instrument",
                      source="converter"))

    # --- time / depth ---
    if meta.get("two_way_time_ns") is not None:
        out.append(_q("two_way_time_ns", ProvenanceClass.MEASURED,
                      "acquisition time axis recorded by the instrument",
                      value=meta["two_way_time_ns"], source="converter"))
    if getattr(record, "depth", None) is None:
        out.append(_q("depth", ProvenanceClass.UNAVAILABLE,
                      "no depth exists: no propagation velocity was supplied",
                      source="SubterraRecord.depth"))
    else:
        v = meta.get("velocity_m_per_ns")
        src = meta.get("velocity_source")
        out.append(_q(
            "depth", ProvenanceClass.DERIVED,
            (f"derived from the measured time axis and a velocity of {v} m/ns "
             f"({src or 'source unrecorded'}); the velocity is an assertion about the "
             f"subsurface, not a measurement of it"),
            value=record.depth, source="SubterraRecord.depth"))

    # --- elevation ---
    elev = getattr(record, "elevation", None)
    if elev is None:
        out.append(_q("elevation", ProvenanceClass.UNAVAILABLE,
                      "no acquisition elevation is carried",
                      source="SubterraRecord.elevation"))
    else:
        datum = meta.get("acquisition_elevation_datum")
        undeclared = (datum in (None, "UNDECLARED"))
        out.append(_q(
            "elevation",
            ProvenanceClass.MEASURED if not undeclared else ProvenanceClass.INFERRED,
            ("acquisition elevation recorded by the instrument, but the source "
             "declares NO vertical datum, so it cannot be compared with another "
             "elevation source" if undeclared
             else f"acquisition elevation on datum {datum}"),
            value=elev, source=meta.get("acquisition_elevation_source", "converter")))

    if frame is not None:
        out.extend(p for p in frame_provenance(frame)
                   if p.quantity in ("horizontal_crs", "vertical_datum"))
    return out


def candidate_provenance(candidate) -> list[QuantityProvenance]:
    """
    An anomaly candidate's provenance.

    The separation this preserves is the important one: `evidence` is measured
    off the processed grid, `characteristics` are geometry derived from it, and
    `interpretation` is a neutral shape description. NONE of them is a claim
    about a physical object, and the basis strings say so.
    """
    out = [
        _q("evidence", ProvenanceClass.DERIVED,
           "measured directly off the anomaly z-score grid: cell count, peak and "
           "mean z, trace and depth ranges. A statistic, not an object",
           value=getattr(candidate.evidence, "n_supporting_cells", None),
           source="AnomalyCandidate.evidence"),
        _q("characteristics", ProvenanceClass.DERIVED,
           "geometric measures computed from the supporting cells (elongation, "
           "compactness, continuity, extents)",
           source="AnomalyCandidate.characteristics"),
        _q("interpretation", ProvenanceClass.DERIVED,
           f"neutral shape class {candidate.interpretation.anomaly_class!r}; "
           f"explicitly NOT a physical-object claim",
           value=candidate.interpretation.anomaly_class,
           source="AnomalyCandidate.interpretation"),
        _q("ground_truth", ProvenanceClass.UNAVAILABLE,
           "no ground truth is attached to this candidate; a detector candidate is "
           "never a confirmed object",
           source="AnomalyCandidate"),
    ]
    ch = candidate.characteristics
    if getattr(ch, "approx_lateral_extent_m", None) is None:
        out.append(_q("lateral_extent_m", ProvenanceClass.UNAVAILABLE,
                      "not derivable: the supporting traces carry no usable "
                      "horizontal position", source="AnomalyCandidate.characteristics"))
    else:
        out.append(_q("lateral_extent_m", ProvenanceClass.DERIVED,
                      f"distance between the candidate's edge traces, measured via "
                      f"{ch.lateral_extent_source}",
                      value=ch.approx_lateral_extent_m,
                      source="AnomalyCandidate.characteristics"))
    conf = candidate.confidence
    if getattr(conf, "velocity_m_per_ns", None) is None:
        out.append(_q("depth_extent_m", ProvenanceClass.UNAVAILABLE,
                      "the supporting cells disagree on velocity, so no single depth "
                      "extent is defensible", source="AnomalyCandidate.confidence"))
    else:
        out.append(_q("depth_extent_m", ProvenanceClass.DERIVED,
                      f"derived from the time axis and a velocity of "
                      f"{conf.velocity_m_per_ns} m/ns, which is an assumption",
                      value=getattr(ch, "approx_depth_extent_m", None),
                      source="AnomalyCandidate.confidence"))
    return out


def summarise(entries: list[QuantityProvenance]) -> dict:
    """
    A compact rendering aid: counts per class, and the weakest class present.

    `weakest_class` is what a viewer should badge an object with -- an object
    is only as trustworthy as its least-supported component, and showing the
    strongest would be exactly backwards.
    """
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.provenance.value] = counts.get(e.provenance.value, 0) + 1
    weakest = min((e.provenance for e in entries),
                  key=lambda c: CLASS_STRENGTH[c], default=None)
    return {
        "counts": counts,
        "weakest_class": weakest.value if weakest else None,
        "unavailable": [e.quantity for e in entries
                        if e.provenance == ProvenanceClass.UNAVAILABLE],
        "total": len(entries),
    }
