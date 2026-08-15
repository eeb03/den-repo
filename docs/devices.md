# Devices and acquisition sessions

Stage 10. The abstraction that lets a **device session** be an acquisition
source alongside a **dropped file**, converging on the same boundary.

> Stage 9: *a file is an acquisition source.*
> Stage 10: *a device session is another one.*

## No hardware is implemented

**There is no hardware integration.** No USB, no serial, no Bluetooth, no vendor
SDK, no streaming, no device commands, no antenna control. Nothing in Subterra
can talk to an instrument.

A device here is a **record of what somebody says they used**, and a session is a
**record that an acquisition event happened**. That is provenance, and it is all
this stage claims to be. The UI says so on the page rather than in a footnote,
and a test asserts no route or component claims a connection.

## The chain

```
Device ──▶ Acquisition Session ──▶ Acquisition (ImportJob) ──▶ Dataset
```

One session may produce **several acquisitions, or none**. A device is not a
dataset; a session is not a dataset.

## Where the convergence happens

A session has **no upload endpoint of its own**. It produces an acquisition
through `POST /api/imports` — the same route FileDrop uses — with a
`session_id`. Everything after receipt is the same code:

```
FileDrop ──┐
           ├──▶ POST /api/imports ──▶ identification ──▶ review hold
Session  ──┘                              ──▶ validation ──▶ ingestion ──▶ dataset
```

A separate hardware endpoint would be a second pipeline, and the two would
drift. A test enumerates the live routes and asserts no device or session route
accepts an upload.

`session_id` is nullable, because a FileDrop acquisition genuinely has none: a
file is a source in its own right, not a session with a missing device.

## Capability is not evidence

The distinction this stage exists to enforce.

| | |
|---|---|
| `Device.capabilities` | what the instrument **can** produce |
| `Session.evidence` | what this acquisition **did** provide |

A device with `reports_position: true` has said nothing about whether a
particular session got a fix. `GET /api/sessions/{id}` returns a
`capability_gap` — what the device could have supplied and this session did not
— and the UI renders it as its own list.

**`SessionEvidence` stores no measurements.** It records *whether* a kind of
information arrived. The values themselves live where they always have: on
records, on frames, and in spatial declarations, where they already carry
provenance. A test asserts the model has no field for a coordinate, an
orientation, a datum, a depth or a velocity.

## The DeviceProfile

`Device.capabilities` (`schemas/devices.py::DeviceCapabilities`) carries the
instrument's declared profile: `manufacturer`, `model`, `device_type` live on
the `Device` row itself; `modalities`, `reports_position`,
`reports_orientation`, `reports_absolute_time`, `frequency_mhz`, `channels`,
`sampling_configuration` and `supported_export_formats` live on
`capabilities`.

**Every field is optional and user-declared, never inferred.** A blank
`frequency_mhz` means nobody has said, not "unknown" spelled as zero. Nothing
here reads a value from a dropped file, a SEG-Y header or a session — those
are read paths that exist elsewhere (`converters/*.py` for a file,
`SessionEvidence` for a session) and stay separate on purpose: what a person
typed into a device form is a different kind of claim from what a file
declared.

`sampling_configuration` is a free-form dict for the same reason
`SessionEvidence.acquisition_parameters` is: instruments vary in what they
configure, and this is recorded verbatim, interpreted by nobody here.

`supported_export_formats` is validated against `converters/registry.py`'s
own `supported_extensions()` — the same registry `GET /api/imports/formats`
serves to the import screen. A device profile can declare only formats
Subterra can actually read, never a second, independently maintained list
that could drift and promise support that does not exist.

**Capability ≠ evidence, still.** A profile field describes what the
instrument *can* do; it says nothing about what a particular session
*produced*. `SessionEvidence` remains the only place that records whether a
session actually provided a position, an orientation or an absolute time.

## The DeviceAdapter

A third object, alongside capability and evidence — a `DeviceAdapter`
(`schemas/devices.py::DeviceAdapter`) states **how** a device's evidence is
meant to reach Subterra:

| | |
|---|---|
| `Device.capabilities` | what the instrument **can** produce |
| `DeviceAdapter` | **how** Subterra receives it |
| `SessionEvidence` | what one acquisition **did** provide |

Confusing any two of these is how a file drop starts looking like a live
connection: a device with `adapter.transport = file_drop` has said nothing
about whether any file has arrived, exactly as `reports_position: true` has
said nothing about whether a session got a fix.

**`file_drop` is the only implemented transport.** It means: files this
instrument writes enter through the existing acquisition boundary
(`POST /api/imports`), optionally attributed with a `session_id` — the same
route FileDrop uses. It is **not** a watch folder. Subterra still receives a
file only when somebody posts one; nothing here polls, watches a directory,
or imports on its own.

`network` and `serial` are **named, not built**. Declaring either is refused
with `422` — the error says the transport is not yet implemented, never
"could not connect", "device unavailable" or "timeout", because no attempt to
reach anything was ever made. The devices page does not offer either as a
selectable option, so there is no control that could look like it connects.

**Absence is undeclared, not `file_drop`.** `Device.adapter` is nullable and
defaults to `null`. A device with no declared adapter is a valid, ordinary
device — the field exists to state the transport when it is known, not to
require one.

Persisted as a JSON column on the existing `Device` row, the same weight as
`capabilities`. No new table, no new acquisition path, no PATCH endpoint —
`POST /api/devices` accepts an optional `adapter`, and `GET` device and
session payloads return it (`null` when undeclared).

## User-declared is not device-reported

`identity_source` is fixed at `user_declared` and is **not a request field**. A
client that could set it could assert that an instrument reported its own serial
number, which would be a forgery. A future adapter that genuinely reads a serial
off hardware writes `device_reported`, and the two stay distinguishable
everywhere downstream. The UI labels each serial with which it is.

## Simulated is not physical

`Device.kind` is `physical` or `simulated`, and the marker travels into every
dataset a simulated session produces (`GET /datasets/{id}/acquisition` returns
`device.is_simulated`). Test data that cannot be told from measurement is the
worst thing an acquisition layer can leak.

**No simulated device exists in this repository's data.** The kind is available
for anyone who needs a stand-in; nothing creates one automatically.

## Session lifecycle

```
CREATED ──▶ READY ──▶ ACQUIRING ──▶ COMPLETED
                │          │
                └──────────┴──▶ CANCELLED / FAILED
```

Kept **separate from `ImportJob.state`** because they answer different
questions: a session is the acquisition *event*, an import job is the
*ingestion* of what it produced. Folding them together would make "the survey is
finished" and "the file has been parsed" one sentence, and they routinely are
not. Only the word `FAILED` is shared.

A terminal session never reopens — a second acquisition event is a second
session, and reopening one would make its start and end times describe two
different things. A completed session cannot receive an acquisition: attaching
to a closed event would rewrite history rather than record it.

### Failure categories

`device-unavailable`, `session-start`, `acquisition`, `transport`, `payload` —
each with a different answer, so "device error" never stands for all five.

**Ingestion failure is deliberately not among them.** That belongs to the import
job, which has its own stages. A session does not fail because a parser did.

## Spatial

Stage 8's system is reused unchanged. A session records *whether* it provided a
position, an orientation or an absolute time; the spatial reference of the
resulting dataset is still assessed by `schemas/spatial_reference.py` from what
the frames actually declare, and still resolved through the spatial workflow.

**A device reporting coordinates does not make a dataset spatially registered.**
The device-reported position enters as records and frames like any other, and
the seven-dimension assessment judges it on the same terms.

## Provenance

```
device (what somebody says they used)
   └─▶ session (an acquisition event, with its operator)
        └─▶ acquisition (bytes, checksum, arrival time)
             └─▶ dataset (what Subterra made of it)
```

`GET /api/datasets/{id}/acquisition` returns all four. A FileDrop dataset
reports `session: null, device: null` rather than having them invented.

## Raw data

Device evidence is preserved exactly as FileDrop evidence is: streamed once,
checksummed in the same pass, never rewritten. A test asserts the stored bytes
are byte-identical to what was sent.

## API

| | |
|---|---|
| `POST /api/devices` | record a device |
| `GET /api/devices` | list your own and system devices |
| `GET /api/devices/{id}` | inspect |
| `POST /api/devices/{id}/sessions` | begin a session |
| `GET /api/sessions/{id}` | session, device, capability gap, acquisitions, datasets |
| `POST /api/sessions/{id}/state?to=` | move along the lifecycle |
| `POST /api/sessions/{id}/evidence` | record what the session provided |
| `POST /api/sessions/{id}/fail` | record a failure and its category |

One `state` endpoint rather than `start`/`complete`/`cancel`: the legal
transitions live in one table, and three routes would each re-check it and
drift.

## Security

The existing model, unchanged. A device or session belonging to somebody else is
a **404, never a 403**. System devices (NULL owner) are readable by all and
writable by none, the rule datasets already follow. A session cannot be created
against another user's device, and an acquisition cannot be attributed to a
session the caller does not own.

## Limitations

- **No transport of any kind.** A session is a record; nothing acquires.
- **No live progress.** The import job's existing states are the only progress
  there is, because they are the only progress that happens.
- **Evidence is asserted, not verified.** Subterra cannot check that a session
  which claims a GNSS fix had one. It records who claimed it.
- **No device sharing.** Devices are per-owner or system; there is no team model.
