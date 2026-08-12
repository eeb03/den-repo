# FileDrop — the acquisition boundary

Stage 9. The controlled point at which externally produced measurement files
enter Subterra: received without alteration, identified before anything is
spent on them, and handed to the ingestion pipeline that already exists.

> **Never make the acquisition easier by making the evidence less trustworthy.**

## What already existed

Most of the boundary, unnamed. `ImportJob` already recorded the original
filename, the sanitised stored name, the size, the detected format, the
resulting dataset id and a failure stage. `jobs/storage.py` already streamed
uploads into a per-job directory with a 2 GiB cap and a traversal-proof
filename. `converters/registry.py` already classified files.

So **the acquisition record is `ImportJob`, extended — not a new table.** A
separate `Acquisition` entity would have been a second upload path with its own
ownership rules, its own failure vocabulary and its own drift.

## What Stage 9 added

1. **A checksum**, taken in the same pass that writes the bytes.
2. **Identification before ingestion** — format, modality, duplicates, and what
   the format can carry spatially.
3. **A hold point**: `review=true` stops at the boundary and reports what
   arrived.
4. **`POST /jobs/{id}/accept`** — the handoff to the existing pipeline.
5. **`GET /datasets/{id}/acquisition`** — the dataset's origin, addressable.

## The lifecycle

```
                                  ┌──▶ REJECTED        (nothing can read it)
                                  │
receive ──▶ RECEIVED ──▶ IDENTIFIED ──▶ QUEUED ──▶ RUNNING ──▶ SUCCEEDED ──▶ dataset
                │            │                                      │
                │            └──▶ NEEDS_INPUT ──▶ QUEUED           FAILED
                │                 (ambiguous, or bytes already held)
                └──▶ FAILED       (upload: empty, oversized, unreadable)
```

**One state machine, extended** — not a second one beside `ImportJob.state`.
Everything from `QUEUED` onward is the original ingestion job, untouched. A
second `acquisition_state` column would have been two fields that could
disagree about whether the same file was finished.

`review=false` remains the default, so every existing caller keeps the original
immediate behaviour. The new flow is opt-in.

## Acquisition is not the dataset

The acquisition describes **what somebody handed to Subterra** — bytes, a name,
a time of arrival. The dataset describes **what Subterra made of it**. One
acquisition may produce no dataset at all (unsupported, malformed, withdrawn),
and the record of its arrival survives either way.

## Preservation

The original bytes are written once, streamed, into the job's own directory and
never rewritten. Everything downstream — normalised records, frames, labels — is
derived data with its own home. The checksum is taken **in the same pass**: not
because a second read would be slow (though for 2 GiB it is), but because the
checksum must be of exactly the bytes that were written, not of whatever is at
that path later.

`Stage 7`'s deletion policy already refuses to delete a raw source file, so an
acquisition survives the deletion of the dataset it produced.

## Duplicates

Checksum comparison against the caller's own acquisitions and the datasets
visible to them. **Reported, never acted on** — the reasoning is Stage 7's,
unchanged: the four INGV datasets share one checksum and are four different
ingestion events under different converter behaviour. Identical bytes arriving
twice is a fact about the bytes, not a mistake to be corrected, so the
acquisition rests at `NEEDS_INPUT` and the user decides.

Scoped to what the caller may already see, so this cannot become a way to
discover that somebody else holds a particular file.

## Identification

Reads the registry, the extension and the size. **It does not parse the
payload** — a test asserts it calls no reader — because parsing here would
duplicate the converter and could disagree with it.

| State | Meaning |
|---|---|
| supported | a parser exists |
| recognized_unsupported | the format is known, no adapter reads it yet |
| unknown | nothing recognises it |

**The modality is the uploader's declaration.** A `.csv` may be GPR traces, a
point cloud or a DEM, and no converter can tell which from the bytes. So the
acquisition rests at `NEEDS_INPUT`, states the ambiguity, and reads the file as
whatever was declared — it does not guess.

## Spatial: expectation, not measurement

Identification reports what the **format** can carry, from the converter's
documented behaviour. It is explicitly *not* a claim about this file; the
dataset report answers that once the file has been read.

**Ingestion readiness is not spatial readiness is not reconstruction
readiness.** A file with no usable spatial reference is still worth parsing,
processing and assessing, so FileDrop offers to proceed and names what will be
blocked later instead of refusing. Stage 8's workflow is where the gaps get
resolved — FileDrop links to it rather than growing a second spatial form.

## Failure categories

`error_stage` keeps these distinguishable, because each has a different answer:

| Stage | Meaning |
|---|---|
| `upload` | the bytes never arrived intact (empty, oversized) |
| `format-check` | arrived, nothing can identify it |
| `identification` | identified, but not usably |
| `validation` | readable, but malformed |
| `ingestion` | accepted, the pipeline failed |

"Upload failed" standing for all five destroys the diagnosis.

## Security

Authentication on every route; `job_or_404` for access, so another user's
acquisition is a 404 rather than a 403. `sanitize_filename` strips both POSIX
and Windows separators before taking the basename, so `..\..\x.sgy` cannot
escape — tested against five hostile filenames. Size cap enforced **during** the
stream, not after. An empty or oversized upload leaves nothing on disk. The
claimed `Content-Type` is recorded and never trusted: dispatch is by what a
converter can actually read. Nothing uploaded is executed or evaluated.

## Provenance

```
original file  →  acquisition (checksum, filename, arrival)  →  dataset
```

`GET /api/datasets/{id}/acquisition` makes the left-hand side addressable.
Datasets ingested before FileDrop — including every published reference corpus —
report `acquisition: null` with the reason, rather than having an origin
reconstructed from a raw path. A plausible-looking origin is exactly the kind of
provenance that must not be manufactured.

## The IDS `.dt` time window

**The premise that this is missing is out of date, and it should not be worked
around.** The acquisition time window *is* carried by the file, in the H
record's ASCII field 2 (sweep time in seconds), repeated at field 3 in every
file examined. `converters/ids_dt_converter.py` reads it, cross-checks it
against the software's own vertical cell size, and **refuses** the file with a
specific message when it is missing, non-numeric or physically implausible.

FileDrop therefore offers no way to supply one, and the acquisition layer
contains no reference to a time window at all — a test asserts that. A window
nobody measured would rescale every sample in the file.

What a `.dt` genuinely lacks is a **horizontal position**: it carries
along-track distance from the wheel encoder, not a place on Earth. That is
reported in the spatial expectation, and the route out of it is Stage 8's
GeoTie.

## Limitations

- **No resumable upload.** A 2 GiB cap, streamed in one request. A dropped
  connection means starting again. Chunked upload is a real storage design and
  would be an untested one if added speculatively.
- **Identification does not read the payload**, so a file whose extension lies
  is identified by its extension and fails later, at validation — with the
  correct failure stage.
- **No MIME sniffing.** The claimed content type is recorded only.
