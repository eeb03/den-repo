"""
Devices and acquisition sessions: the second way evidence enters Subterra.

Stage 9 established that a FILE is an acquisition source. This establishes that
a DEVICE SESSION is another one, and the whole point is that they converge:
both produce an `ImportJob` -- the acquisition record -- which goes through the
same identification, validation, spatial assessment and ingestion. There is no
hardware path and no file path. There is one acquisition boundary with two ways
of reaching it.

NO HARDWARE IS IMPLEMENTED HERE. No USB, no serial, no vendor SDK, no streaming,
no device commands. A device in this module is a RECORD of what somebody says
they used, and a session is a record of an acquisition event. Nothing in
Subterra can currently talk to an instrument, and nothing here pretends
otherwise.

THE DISTINCTION THIS MODULE EXISTS TO ENFORCE:

    what a device CAN produce   !=  what a session DID produce
    what a user TYPED           !=  what a device REPORTED
    a simulated device          !=  a physical one
    a device-reported position  !=  a validated spatial reference

A device that lists GNSS among its capabilities has told you nothing about
whether a particular session got a fix. A capability is a statement about
hardware; evidence is a statement about an acquisition. Collapsing them is how
a survey with no satellite lock ends up with coordinates.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from schemas.subterra_record import SensorType


class DeviceKind(str, Enum):
    """
    Whether this record describes real hardware or a stand-in.

    SIMULATED IS NOT A LESSER PHYSICAL. It is a different thing, and the
    difference must survive into every dataset a simulated session produces --
    otherwise test data becomes indistinguishable from measurement, which is the
    single most damaging thing an acquisition layer could allow.
    """
    PHYSICAL = "physical"
    SIMULATED = "simulated"


class IdentitySource(str, Enum):
    """
    Where a device's identity came from.

    `USER_DECLARED` is the only value anything currently writes: a person typed
    a manufacturer and a model into a form. `DEVICE_REPORTED` exists so that a
    future adapter which reads a serial number off an instrument has somewhere
    to say so -- and so that a user-typed serial can never be mistaken for one.
    """
    USER_DECLARED = "user_declared"
    DEVICE_REPORTED = "device_reported"


class SessionState(str, Enum):
    """
    The lifecycle of one acquisition event.

    SEPARATE FROM `ImportJob.state`, deliberately, because they describe
    different things: a session is the acquisition EVENT, an import job is the
    INGESTION of what that event produced. One session may produce several
    acquisitions, or none. Folding them together would make "the survey is
    finished" and "the file has been parsed" the same sentence, and they are
    routinely not.

        CREATED ──▶ READY ──▶ ACQUIRING ──▶ COMPLETED
                                  │
                                  ├──▶ CANCELLED
                                  └──▶ FAILED
    """
    CREATED = "CREATED"
    READY = "READY"
    ACQUIRING = "ACQUIRING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


#: Which transitions are legal. A session that has ended does not resume: a
#: second acquisition event is a second session, and reopening one would make
#: its start and end times describe two different things.
ALLOWED_TRANSITIONS: dict[SessionState, tuple[SessionState, ...]] = {
    SessionState.CREATED: (SessionState.READY, SessionState.CANCELLED, SessionState.FAILED),
    SessionState.READY: (SessionState.ACQUIRING, SessionState.CANCELLED, SessionState.FAILED),
    SessionState.ACQUIRING: (SessionState.COMPLETED, SessionState.CANCELLED, SessionState.FAILED),
    SessionState.COMPLETED: (),
    SessionState.CANCELLED: (),
    SessionState.FAILED: (),
}

#: States in which a session may still receive acquisitions. A completed session
#: is a closed record of what happened; attaching to it later would rewrite
#: history.
ACCEPTS_ACQUISITIONS = (SessionState.READY, SessionState.ACQUIRING)

TERMINAL_STATES = (SessionState.COMPLETED, SessionState.CANCELLED, SessionState.FAILED)


# --- failure categories ----------------------------------------------------
#
# Kept distinct because each has a different answer, exactly as Stage 9's
# acquisition stages are. "Device error" standing for all six tells the user
# nothing they can act on.
FAILURE_DEVICE_UNAVAILABLE = "device-unavailable"   # nothing to acquire from
FAILURE_SESSION_START = "session-start"             # could not begin
FAILURE_ACQUISITION = "acquisition"                 # began, measurement failed
FAILURE_TRANSPORT = "transport"                     # communication interrupted
FAILURE_PAYLOAD = "payload"                         # measurement arrived invalid
# Ingestion failure is NOT here: it belongs to the import job, which already has
# its own stage vocabulary. A session does not fail because a parser did.

FAILURE_STAGES = (
    FAILURE_DEVICE_UNAVAILABLE, FAILURE_SESSION_START, FAILURE_ACQUISITION,
    FAILURE_TRANSPORT, FAILURE_PAYLOAD,
)


class InvalidTransition(ValueError):
    """The session cannot move from where it is to where it was asked to go."""


def transition(current: SessionState, requested: SessionState) -> SessionState:
    allowed = ALLOWED_TRANSITIONS.get(current, ())
    if requested not in allowed:
        raise InvalidTransition(
            f"a session cannot go from {current.value} to {requested.value}"
            + (f"; from {current.value} it may only go to "
               f"{', '.join(s.value for s in allowed)}" if allowed
               else f"; {current.value} is terminal"))
    return requested


# ---------------------------------------------------------------------------
# what an adapter may state
# ---------------------------------------------------------------------------

class DeviceCapabilities(BaseModel):
    """
    What a device CAN produce. Never what it did.

    Expressed in the platform's existing `SensorType` vocabulary rather than a
    second modality enum, so a capability and a dataset's modality are the same
    word and cannot drift.
    """
    modalities: list[SensorType] = Field(default_factory=list)
    #: Whether the device is capable of reporting its own position, orientation
    #: or absolute time. Capability only -- a session reports separately whether
    #: any of it actually arrived.
    reports_position: bool = False
    reports_orientation: bool = False
    reports_absolute_time: bool = False
    #: Declared operating/antenna frequency in MHz -- the unit GPR equipment
    #: specs use (see converters/mala_converter.py, gssi_converter.py
    #: `antenna_frequency_mhz`). Absent means nobody has said, not "unknown 0".
    frequency_mhz: Optional[float] = None
    #: Declared channel count. A single-channel unit and a multi-channel array
    #: are different instruments; this is what the operator says the unit has,
    #: never inferred from a file.
    channels: Optional[int] = None
    #: Declared sampling configuration, e.g. {"sample_interval_ns": 0.4,
    #: "samples_per_trace": 512}. Free-form for the same reason
    #: `SessionEvidence.acquisition_parameters` below is: instruments vary in
    #: what they configure, and this is recorded verbatim, interpreted by
    #: nobody here.
    sampling_configuration: dict[str, Any] = Field(default_factory=dict)
    #: File formats this instrument can write, chosen from the platform's own
    #: read registry (`converters/registry.py`) so a declared export format is
    #: guaranteed to be one Subterra can actually ingest -- never a second,
    #: independently maintained format list.
    supported_export_formats: list[str] = Field(default_factory=list)
    notes: Optional[str] = None

    @field_validator("supported_export_formats")
    @classmethod
    def _export_formats_are_known(cls, value: list[str]) -> list[str]:
        from converters.registry import supported_extensions
        known = supported_extensions()
        unknown = [f for f in value if f not in known]
        if unknown:
            raise ValueError(
                f"unsupported export format(s) {unknown}; Subterra reads "
                f"{sorted(known)}"
            )
        return value

    def describes(self, modality: SensorType) -> bool:
        return modality in self.modalities


# ---------------------------------------------------------------------------
# how a device's evidence is meant to reach Subterra -- a third thing,
# neither capability nor evidence
# ---------------------------------------------------------------------------

class Transport(str, Enum):
    """
    How a device's evidence is meant to reach Subterra. NAMED, not built:
    only `FILE_DROP` is implemented. `NETWORK` and `SERIAL` exist so a caller
    can state the true shape of the instrument's intended path without the
    platform pretending to support it -- and so a refusal names the
    transport instead of collapsing into "device unavailable".
    """
    FILE_DROP = "file_drop"
    NETWORK = "network"
    SERIAL = "serial"


class DeviceAdapter(BaseModel):
    """
    HOW this device's evidence is meant to arrive. Not a connection, a
    session, or a capability -- a third thing:

        Device.capabilities   what the instrument CAN produce
        DeviceAdapter          HOW Subterra receives it
        SessionEvidence        what one acquisition DID provide

    `transport=file_drop` states that files this instrument writes enter
    through the existing acquisition boundary (`POST /api/imports`),
    optionally attributed with a `session_id`. It is not a claim that
    anything has arrived, and it is not a watch folder: Subterra still
    receives a file only when somebody posts one.

    Deliberately minimal. No host, port, path, baud rate, MAC address,
    pairing token, connection state, last-seen timestamp, or signal strength
    -- every one of those would imply a live link that does not exist.
    """
    transport: Transport

    @field_validator("transport")
    @classmethod
    def _only_file_drop_is_implemented(cls, value: Transport) -> Transport:
        if value != Transport.FILE_DROP:
            raise ValueError(
                f"'{value.value}' is a named transport, not an implemented one. "
                "Only 'file_drop' is currently accepted: files this device writes "
                "enter through the existing import boundary. This is not a "
                "connection failure -- no attempt to reach the transport was made."
            )
        return value


class SessionEvidence(BaseModel):
    """
    What a session ACTUALLY provided, as opposed to what the device could have.

    Every field defaults to absent. A device with `reports_position=True` whose
    session got no fix produces `position_provided=False`, and the two live in
    different objects so no code path can read one for the other.

    NOTHING HERE IS A MEASUREMENT. It records whether a KIND of information
    arrived, so the spatial workflow and the dataset report can say what is
    missing. The values themselves live where they always have: on records, on
    frames, and in spatial declarations.
    """
    position_provided: bool = False
    position_source: Optional[str] = None      # "device_reported" | "user_declared"
    orientation_provided: bool = False
    orientation_source: Optional[str] = None
    absolute_time_provided: bool = False
    #: Acquisition parameters as the device or operator stated them -- antenna,
    #: sample interval, trace interval, mode. Recorded verbatim, interpreted by
    #: nobody here.
    acquisition_parameters: dict[str, Any] = Field(default_factory=dict)

    def missing(self, capabilities: DeviceCapabilities) -> list[str]:
        """
        What the device could have supplied and this session did not.

        The gap between capability and evidence, stated rather than smoothed
        over. This is what makes "the device has GNSS" and "this survey has
        coordinates" two answerable questions instead of one misleading one.
        """
        gaps: list[str] = []
        if capabilities.reports_position and not self.position_provided:
            gaps.append("a position: the device can report one and this session did not")
        if capabilities.reports_orientation and not self.orientation_provided:
            gaps.append("an orientation: the device can report one and this session did not")
        if capabilities.reports_absolute_time and not self.absolute_time_provided:
            gaps.append("an absolute acquisition time: the device can report one and "
                        "this session did not")
        return gaps
