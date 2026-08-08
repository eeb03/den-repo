# Asynchronous dataset import

The first path by which a user can put their own data into Subterra. It wraps
the existing ingest pipeline; it does not reimplement any of it.

```
POST /api/imports          upload -> persist -> create job -> queue      202
GET  /api/imports/formats  what the converter registry can actually read
GET  /api/imports/jobs     recent jobs, newest first
GET  /api/imports/jobs/{id}  one job's current state
```

`POST /api/datasets/ingest` is **unchanged and still present**. It has no test
coverage of its own, so it was not removed: an unseen caller could depend on it.

## What a job reports, and what it does not

| Field | Meaning |
|---|---|
| `state` | `QUEUED` · `RUNNING` · `SUCCEEDED` · `FAILED` |
| `stage` | the pipeline step: `converting`, `validating`, `preprocessing`, `persisting`, `registering`, `complete` |
| `error_stage` / `error_message` | which step raised, and the backend's own message |
| `dataset_id` | present only once a dataset has actually been registered |

**There is no percentage, and there will not be one.** `_run_ingest_pipeline`
reports which step it is in via an `on_stage` callback; it cannot report how far
through a step it is. A bar filled to "3 of 5 steps" would be a number the
platform invented about its own progress, which is the same failure mode as
inventing a number about the ground. The interface renders a stage track
instead.

## Execution model, and its limits

A module-level `ThreadPoolExecutor(max_workers=1)` in `jobs/runner.py`. No
Redis, no Celery, no broker.

One worker rather than FastAPI's `BackgroundTasks` for two reasons, both about
accuracy: `QUEUED` becomes a real state (a second import genuinely waits), and a
multi-minute CPU-bound ingest cannot compete with ordinary API calls for the
request threadpool.

**Stated limits, so nobody has to discover them:**

1. **Single process.** Jobs run inside the API process. Two uvicorn workers
   would each run their own executor and each pick up work; this design does
   **not** survive a multi-worker deployment as-is.
2. **Restart does not resume.** A job RUNNING when the process dies is not
   restarted — but it is not left lying either. `mark_orphaned_jobs_failed()`
   runs at startup and moves any QUEUED/RUNNING row to FAILED with a stated
   reason, so the API can always represent what happened. A job never silently
   disappears.
3. **No retry.** A failed job stays failed; the user imports again.
4. **In-memory queue.** Work waiting in the executor is lost on restart; the
   same reconciliation catches it, because the row is QUEUED in the database.

**Migration path.** Replace `submit()` with an enqueue to a real broker and run
`_execute` in a separate worker process. The job table, the four states, the
stage names and the API do not change.

## File handling

Every upload lands in **its own directory**, `datasets/raw/imports/<job_id>/`.

- **Filenames are sanitised** to a single path component with a restricted
  character set. The extension is preserved deliberately — the converter
  registry dispatches on it, so mangling it would turn a supported file into an
  unknown one.
- **Collisions are unrepresentable.** Two users uploading `line1.sgy` write to
  different job directories.
- **Partial uploads cannot be mistaken for finished ones.** Bytes stream to a
  `.part` file which is renamed only on success; a failed or oversized upload is
  deleted.
- **Unreadable formats are refused before anything is written**, so a rejected
  import leaves no bytes behind.
- **2 GiB limit** (`jobs/storage.MAX_UPLOAD_BYTES`), a module constant rather
  than a setting because `configs/` was a frozen path in this change.

This deliberately does not inherit the behaviour of the older
`POST /api/datasets/ingest`, which writes to `settings.raw_dir / file.filename`
with the client's filename unmodified — so a crafted name can escape `raw_dir`
and a repeated name silently overwrites. That endpoint is untouched here and
should be hardened or retired in a later change.

## Ownership — why `owner_id` is only on the job

`ImportJob.owner_id` exists, nullable and unenforced, so the import path is not
the thing that has to be retrofitted when authentication lands.

**It was deliberately NOT added to `Dataset`.** There is no Alembic and no
migration tooling in this repository; the schema comes from
`Base.metadata.create_all`, which creates *missing tables* but never alters
existing ones. Adding a column to the `Dataset` model would make SQLAlchemy emit
`SELECT datasets.owner_id …` against a live table that does not have it,
breaking the entire datasets API and the workspace. A new table is safe; a new
column on an existing table needs a migration first.

That migration is the prerequisite for multi-user upload. Until it exists,
**every dataset is visible to every caller and all files share one tree** —
which is why authentication has not been added: enforcing identity without
ownership columns would be security theatre.
