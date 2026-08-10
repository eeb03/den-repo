# Dataset lifecycle

Stage 7. What a user can do to a dataset without a terminal, and what the
platform refuses to do on their behalf.

```
create ──▶ process ──▶ ready ──▶ inspect ──▶ rename ──▶ delete
              │           │          │                    │
              └─ failed   └─ empty   └─ stale ──▶ rescore ─┘
```

| Step | Where | State |
|---|---|---|
| create | `POST /api/imports` (async job) | supported since stage 2 |
| process | the import worker; `POST /{id}/reprocess` | supported |
| ready | derived status, see below | **new** |
| inspect | `GET /{id}/report` | stage 6 |
| rename | `PATCH /api/datasets/{id}` | **new** |
| stale → rescore | `POST /{id}/rescore` | **new** |
| delete | `DELETE /api/datasets/{id}` | **rewritten** |

## Identity: three things, kept separate

| | Changes? | Purpose |
|---|---|---|
| dataset id | never | what every record, frame, label and artifact is keyed on |
| name | freely | what a person calls it |
| source file | never via the UI | what the bytes actually were |

Renaming writes one column. The id, the raw path, the checksum, the frames'
`source_file` and every provenance entry are untouched — a test asserts the
report's `provenance` block is byte-identical across a rename.

**Names are not unique.** Two datasets in the corpus are already both called
"INGV-UNISA Site 1 GPR v3" and are genuinely different ingestion events.
Enforcing uniqueness would either reject that or silently mangle it. The id is
shown next to the name everywhere it matters.

## Status is derived, never stored

There is no status column. A stored status is a second copy of the truth that
drifts the moment a process dies between writing the data and writing the
status. Status is computed from the two facts that are actually true — whether
an import job is in flight, and whether records exist:

| Status | When |
|---|---|
| `importing` | a job for this dataset is QUEUED or RUNNING |
| `ready` | records are stored |
| `failed` | the last job FAILED and no records exist |
| `empty` | no job, no records |

The vocabulary is the job's, extended. `ImportJob.state` is carried through
unrenamed on every row, so the list and the import screen cannot disagree.

## Deletion

One line:

> **Derived data is removed. Source data and event logs are retained.**

| Removed | Retained |
|---|---|
| the `datasets` row and its versions | the **raw source file** |
| records, frames, labels, associations, objects | the **import job** record |
| fusion samples that included the dataset | |

**Why the raw file is never deleted.** It is the bottom of the evidence chain —
the original measurement every later claim reduces to — and it cannot be
regenerated. It is also demonstrably **shared**: the four INGV datasets have
identical source checksums and point into the same download, so deleting "one
dataset's" raw file would destroy three others' provenance. A user who wants
the bytes gone can remove them; the platform will not do it as a side effect of
tidying a list.

**Why the import job is never deleted.** An import happened. That a dataset was
later removed does not un-happen it, and deleting the job would make the import
history lie by omission. `dataset_id` on a job means "the dataset this import
produced", which may since have been deleted.

**Why fusion samples are.** They are derived: the output of a computation over
datasets, recomputable from whatever remains. A sample referencing a dataset
nobody can open is worse than no sample. This is the one place the policy
destroys something, and it destroys only a cached result.

**A dataset with an import in flight is refused** (409). Removing artifacts a
running job is writing would race it, and the job would finish by recreating
some of them.

The response enumerates what went and what stayed. "deleted: true" is not an
adequate answer for an irreversible operation over scientific data.

### What this fixed

The previous implementation deleted one database row. Everything a dataset
actually consists of lives in JSONL beside the database, and none of it was
touched. **The corpus on this machine carries 15 orphaned artifact sets
totalling 167 MB** for datasets that no longer exist — measured, not estimated.

Adding `cascade="all, delete-orphan"` would not have helped: the files are not
rows. `ARTIFACT_SUFFIXES` lists every per-dataset artifact, and a test reads the
stores' own path builders and fails if one writes something deletion does not
remove — which is exactly how the existing orphans accumulated.

The 15 that pre-date the fix are reported, never auto-deleted:

```
python -m scripts.find_orphaned_artifacts
```

Read-only by design. By the time anybody runs it there is no way to tell from
outside whether a file is residue or a dataset mid-import on another process,
and a tool that guessed and deleted 167 MB would be a worse bug than the one it
was written to clean up.

## Stale derived data

The report compares the **stored** quality score against one **recomputed** from
the records as they are now, and flags `score_is_stale` when they differ. Two of
the six datasets held differ by a lot — stored 0.30 against a computed 0.80 —
because they were scored before `NoPosition` replaced the `(0, 0)` placeholder,
so they were being penalised for coordinates their format never had.

`POST /{id}/rescore` corrects it. **It is not `reprocess`**, and the difference
is the whole reason it can be offered as a button:

| | reads | writes |
|---|---|---|
| `POST /{id}/reprocess` | records | **records** (dewow, gain, normalisation), score |
| `POST /{id}/rescore` | records | the score and its issue list |

Using `reprocess` to fix a wrong number *about* the data would change the data.
`rescore` is deterministic, idempotent, and touches no record, frame, label or
raw file. A test asserts its implementation contains no `run_pipeline`,
`save_records` or `save_frames`.

## Duplicates: detection only

Datasets ingested from the same source bytes are grouped by checksum and
reported as `shares_source_with`. **Nothing is merged, hidden or deleted.**

The four INGV rows share one checksum and one record count, and are still four
different things:

| id | format | quality | note |
|---|---|---|---|
| `1f4e0982` | `zip(100 files)` | 0.3 | read 100 files — the archive ships three copies of the same 50 lines |
| `e1f666cd` | `zip(50 files)` | 0.3 | |
| `809d15f4` | `zip(50 files)` | 0.8 | scored after the schema change |
| `c297f528` | `zip(50 files)` | 0.8 | 15 minutes later |

Identical bytes in; four ingestion events, two converter behaviours, two scoring
regimes. Collapsing them would destroy the only record of how converter
behaviour changed over time — which is provenance, not clutter.

**Option A was chosen** (detect and report) over version relationships (B) or
deduplication (C). B needs a lineage model that stage 7 does not have a use for
yet; C would delete evidence. If versioning becomes necessary, `DatasetVersion`
already exists and is unused.

## Access control

Unchanged mechanism, applied to the new routes. `require_owned_dataset` on
`PATCH`, `DELETE` and `rescore`; a non-owner gets **404, never 403**, so an id
cannot be probed for existence. System reference data (NULL owner) is readable
by everyone and modifiable by no one — the UI shows why rather than rendering
buttons that always fail.
