# Record loading

Why Subterra's measured-data surfaces were slow, what the cause turned out to
be, and what was changed. The headline: **one flag on a read path was costing a
second full parse of the corpus**, and the damage was superlinear rather than
merely doubled.

## 1. The measured bottleneck

Stage 15 found that two concurrent consumers of the same dataset took ~66 s each
where sequentially they took 6.8 s and 18.4 s. The obvious explanation — "the
one-entry cache is too small" — is wrong, and provably so: **both consumers
wanted the same dataset**, so a size bound is not what they collided on.

## 2. Root cause, measured

`api/candidates.py` passed `use_cache=False` at two call sites. The cache's
contract reserves that flag for callers that intend to **mutate** what they get
back; the candidate path mutates nothing. The flag bought no safety and cost a
second full parse.

A materialised corpus is not small:

| | |
|---|---|
| Corpus | 157,040 records, 69.3 MB on disk |
| Materialised | **384 MB** traced Python allocation |
| Per record | **2,565 bytes** |

And a second copy is not merely twice the cost:

| Operation | Time |
|---|---|
| Parse with nothing else resident | **4.0 s** |
| Parse **while another copy is resident** | **14.0–17.4 s** |

That is the mechanism. The second allocation runs against an allocator and
garbage collector already carrying 384 MB of live objects, so the cost of the
identical work rises 3.5–4×. Two consumers each holding a copy is what turned
6.8 s into 66 s.

Confirmed directly in a controlled two-thread trial on the real corpus:

| Arrangement | Parses | Wall |
|---|---|---|
| One consumer bypasses the cache (as shipped) | **2** | 13.4 s |
| Both use the cache | **1** | 4.7 s |

## 3. Where parse time goes

| Stage | Time |
|---|---|
| read file | 0.2 s |
| split lines | 0.1 s |
| `json.loads` | 2.8 s |
| **pydantic model construction** | **13.3 s** |

Pydantic construction dominates. This matters for §5 below: it means the
remaining cost is object construction, not I/O, so no amount of caching strategy
removes it — only constructing fewer objects would.

## 4. The change

Two lines. `api/candidates.py` now uses the cache on both read paths.

That is option **A** from the stage brief's preference order — *reuse of an
already-loaded immutable representation when multiple consumers need the same
records* — and no cache was added, resized, or invented. The one-entry bound is
unchanged because the measurements gave no reason to change it: the workflow
that costs time is several consumers of **one** dataset, which one entry serves.

**Why sharing is safe, verified rather than assumed.**
`interpretation.anomaly_candidates` is a read-only interpretation layer that
never mutates records, never writes `ground_truth` and persists nothing.
`test_candidate_generation_does_not_mutate_the_records` hashes every record
before and after a real generation run on a real corpus and asserts they are
identical. Candidate output is byte-identical cached vs uncached.

**The write paths still bypass, and must.** `api/routes/datasets.py` keeps
`use_cache=False` where a handler reprocesses, DEM-aligns or appends and saves
records back; handing those the shared objects would corrupt every later reader.
A test asserts those bypasses and their stated reasons remain.

## 5. Rejected alternatives

| Option | Why not |
|---|---|
| **Multi-entry cache (B)** | The measured problem is two consumers of ONE dataset. A second entry would not have removed a single parse from the workflow that was slow, and at 384 MB per entry it trades a latency problem for a memory one. |
| **Field-selective loading (C)** | Callers genuinely use the whole record — the trace grid reads `signal`, `depth` and three metadata keys; the report reads position, quality and provenance fields; candidates read metadata and `signal`. A projection would need to satisfy their union, which is most of the model. |
| **Streaming/chunked (D)** | The connected-component rule needs a whole survey line at once, and the ring statistic must see the line without chunk boundaries. Chunking would change the science, which the brief forbids. |
| **Caching the derived products** | Would create a second source of truth for records and a second staleness problem, to avoid work that sharing already avoids. |

## 6. Invalidation semantics — unchanged

Sharing does not weaken freshness; the existing rules apply to one more consumer.

A cached parse is valid only while `(path, mtime_ns, size)` is unchanged, and
`save_records` clears the cache explicitly on **every** write rather than relying
on that identity. So a cached corpus does not survive:

- **reprocessing** — `run_pipeline` saves records back, which clears
- **DEM alignment** — same
- **depth-slice append** — same
- **deletion** — the file stops existing; `load_records` returns `[]`
- **a rewrite within one timestamp tick** — size travels with mtime, and the
  explicit clear covers it regardless

Staleness of *candidates* is a separate mechanism and is untouched: the
fingerprint is computed from the records as they are now, and the cache only
guarantees that they are the current ones. Spatial declarations, rescoring and
acquisition changes continue to affect candidate staleness exactly as before.

Parse identity is per dataset, so datasets cannot be confused for one another —
asserted by `test_datasets_stay_isolated`. Authorization is unaffected: the cache
sits below the route layer and every route keeps its `require_dataset_access`
dependency.

## 7. Before and after

Same corpus, same machine, median of three trials, measured through the HTTP API
on a real ingested 4TU line (160,768 records), with the before/after taken by
reverting only `api/candidates.py` and rebuilding.

| | Before | After | Improvement |
|---|---|---|---|
| `GET /candidates/{id}` | 22.86 s | **0.71 s** | **32×** |
| `GET /trace_grid` (+reliability, +footprints) | 4.73 s | **3.76 s** | 1.3× |
| **Concurrent grid + candidates (wall)** | **28.17 s** | **2.79 s** | **10×** |
| Parses per radargram page load | 2 | **1** | halved |
| Peak resident copies of the corpus | 2 (~768 MB) | **1 (~384 MB)** | halved |

The concurrent figure is the one that matters: it is what the radargram page
actually issues, and it is where two resident copies did their damage.

**On variance.** Individual trials range widely (`trace_grid` 2.19–8.52 s after
the change) because the first request to a fresh container pays both an empty
cache and a cold OS page cache — the corpus is read through a macOS bind mount,
which is slow on first touch. Medians are reported for that reason, and an
earlier benchmark run had to be discarded entirely because the backend test
suite was saturating the same six cores.

The dataset report measured 0.81 s before and 2.06 s after. It does one cached
load either way and this change does not touch its path; the difference is
warm/cold state, not a regression. Cold, a first radargram load still costs
~13–27 s, almost all of it the first parse — see the limitations below.

## 8. Remaining limitations

- **A cold parse still costs ~4 s per 157k records**, and pydantic construction
  is 13 of the 16 s in the breakdown above. Removing that means constructing
  fewer Python objects — a columnar or array-backed representation — which is a
  data-model change, not a caching change, and is out of scope here.
- **The cache holds one dataset.** Alternating between two datasets re-parses
  each time. That is the documented, deliberate bound, and no measured workflow
  currently pays it.
- **The report path is unimproved** because it was already sharing the cache.
- **Memory is not bounded by count.** One 384 MB entry is fine; a corpus ten
  times larger would not be, and nothing currently refuses it.

## 9. Where it lives

| Concern | Module |
|---|---|
| The cache and its identity rules | `database/records_store.py` (unchanged) |
| The fixed consumer | `api/candidates.py` |
| Measurement harness | `scripts/measure_record_loading.py` |
| Cache contract tests | `tests/test_records_cache.py` (unchanged) |
| Reuse and non-mutation tests | `tests/test_candidate_record_reuse.py` |

Reproduce the measurements with:

```
python scripts/measure_record_loading.py --dataset <id> --out artifacts/perf/record_loading.json
```
