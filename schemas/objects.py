"""
SubsurfaceObject: a persistent identity that observations can be attached to.

WHAT AN OBJECT IS. A hypothesis with a stable id. It exists so that "the
thing seen at trace 40 of line 3" and "the thing seen at trace 12 of line 4"
can be talked about as possibly the same thing, across sessions and exports,
without either observation being altered.

WHAT AN OBJECT IS NOT. A buried utility. Creating one asserts only that some
observations have been ASSOCIATED -- and association is a hypothesis backed by
evidence, not a discovery. The status vocabulary keeps that visible:

    hypothesised   one or more observations associated; nothing corroborates
                   them beyond the association itself
    corroborated   observations from INDEPENDENT acquisitions were associated
                   -- different survey lines, different instruments, different
                   passes. Stronger, still not truth.
    attested       an attested ground-truth label refers to it. Only this
                   status may be spoken of as a real thing, and only because
                   something outside the detector established it.

A detector agreeing with itself never promotes an object. `corroborated`
requires independence, and `attested` requires a `SemanticLabel` of kind
GROUND_TRUTH -- which itself requires an attestation. The validator enforces
both, so promotion cannot happen by accident or by repetition.

POSITION. An object's position is DERIVED from its members and is marked as
such. When the members cannot be placed on Earth -- odometry, a local grid,
an undeclared projection -- the object's position is `NoPosition` with the
reason, and it stays that way. An object is never given a coordinate so that
it can be drawn.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from schemas.provenance import ProvenanceClass
from schemas.spatial import NoPosition, Position


class ObjectStatus(str, Enum):
    HYPOTHESISED = "hypothesised"
    CORROBORATED = "corroborated"
    ATTESTED = "attested"


class ObservationKind(str, Enum):
    """What kind of thing was observed. All are already first-class elsewhere."""
    CANDIDATE = "candidate"     # an AnomalyCandidate
    LABEL = "label"             # a SemanticLabel
    MANUAL = "manual"           # a human-placed observation


class ObservationRef(BaseModel):
    """
    A pointer to one observation, with enough context to locate it again.

    `acquisition_id` is what independence is judged on: two observations from
    the same survey line are not independent evidence, however far apart their
    traces. It defaults to the frame, which is one acquisition by definition.
    """
    kind: ObservationKind
    dataset_id: str = Field(..., min_length=1)
    observation_id: str = Field(..., min_length=1)
    frame_id: Optional[str] = None
    source_file: Optional[str] = None
    trace_index: Optional[int] = None
    position: Position = Field(
        default_factory=lambda: NoPosition(
            reason="this observation carries no position of its own"))

    @property
    def acquisition_id(self) -> str:
        return self.frame_id or self.source_file or self.dataset_id


def make_object_id(dataset_id: str, member_ids: list[str]) -> str:
    """
    Stable identity from the member set, so re-resolving the same associations
    yields the same object rather than a new one each run.
    """
    raw = dataset_id + "|" + "|".join(sorted(member_ids))
    return "obj_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


class SubsurfaceObject(BaseModel):
    """One hypothesised subsurface thing, and the observations behind it."""
    id: Optional[str] = None
    dataset_id: str = Field(..., min_length=1)
    status: ObjectStatus = ObjectStatus.HYPOTHESISED
    members: list[ObservationRef] = Field(..., min_length=1)

    #: Derived from the members. Never invented; `NoPosition` when the members
    #: cannot be placed.
    position: Position = Field(
        default_factory=lambda: NoPosition(
            reason="no member observation carries a position on Earth"))
    position_provenance: ProvenanceClass = ProvenanceClass.DERIVED
    position_basis: str = "derived from the member observations"

    #: The association ids that produced this object, so the reasoning is
    #: reachable from the result.
    association_ids: list[str] = Field(default_factory=list)
    #: Ground-truth label ids, if any. Required for ATTESTED.
    attested_by: list[str] = Field(default_factory=list)

    notes: Optional[str] = None
    created_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @model_validator(mode="after")
    def _status_must_be_earned(self):
        acquisitions = {m.acquisition_id for m in self.members}
        if self.status == ObjectStatus.ATTESTED and not self.attested_by:
            raise ValueError(
                "an object may only be `attested` when `attested_by` names at least one "
                "ground-truth label. A detector cannot attest to its own findings."
            )
        if self.status == ObjectStatus.CORROBORATED and len(acquisitions) < 2:
            raise ValueError(
                f"`corroborated` requires members from at least two independent "
                f"acquisitions; these come from {len(acquisitions)} "
                f"({sorted(acquisitions)}). Repeated observations within one survey "
                f"line are not independent evidence."
            )
        if self.position_provenance == ProvenanceClass.MEASURED:
            raise ValueError(
                "an object's position is DERIVED from its members; the object itself "
                "measured nothing."
            )
        if self.id is None:
            self.id = make_object_id(
                self.dataset_id, [m.observation_id for m in self.members])
        return self

    @property
    def acquisition_count(self) -> int:
        return len({m.acquisition_id for m in self.members})

    @property
    def is_placed(self) -> bool:
        return getattr(self.position, "kind", "none") != "none"


def derive_position(members: list[ObservationRef]) -> tuple[Position, str]:
    """
    An object's position from its members' positions.

    Only GEOGRAPHIC members contribute, and only their mean is taken -- the
    centroid of what was actually observed. Mixing coordinate kinds would be
    averaging metres with degrees, so a member set with no geographic position
    yields `NoPosition` and says why.
    """
    from schemas.spatial import GeographicPosition, PositionKind

    geo = [m.position for m in members
           if getattr(m.position, "kind", None) == PositionKind.GEOGRAPHIC]
    if not geo:
        kinds = sorted({str(getattr(m.position, "kind", "none")) for m in members})
        return (NoPosition(reason=(
            f"no member observation carries a geographic position (kinds present: "
            f"{kinds}); the object exists but cannot be placed on Earth")),
            "no geographic member")
    lat = sum(p.lat for p in geo) / len(geo)
    lon = sum(p.lon for p in geo) / len(geo)
    return (GeographicPosition(lat=lat, lon=lon),
            f"centroid of {len(geo)} geographic member observation(s) out of "
            f"{len(members)}")


def build_object(dataset_id: str, members: list[ObservationRef],
                 association_ids: Optional[list[str]] = None,
                 attested_by: Optional[list[str]] = None,
                 notes: Optional[str] = None) -> SubsurfaceObject:
    """
    Assembles an object and assigns the STRONGEST status its evidence earns --
    never more.
    """
    position, basis = derive_position(members)
    attested = attested_by or []
    if attested:
        status = ObjectStatus.ATTESTED
    elif len({m.acquisition_id for m in members}) >= 2:
        status = ObjectStatus.CORROBORATED
    else:
        status = ObjectStatus.HYPOTHESISED
    return SubsurfaceObject(
        dataset_id=dataset_id, status=status, members=members,
        position=position, position_basis=basis,
        association_ids=association_ids or [], attested_by=attested, notes=notes,
    )
