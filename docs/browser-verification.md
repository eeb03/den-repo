# Browser verification

The frontend's tests run in jsdom, which parses markup but renders nothing,
runs no layout, and executes no iframe. Everything the workspace claims about
what a *person sees* was therefore unverified until this pass. This document
records what a real browser actually did, so the next session does not repeat
the setup archaeology.

**Nothing in this pass modified the repository, the benchmarks or the
artifacts.** `HEAD` was `0daa3e7` before and after; the BAM and 4TU artifact
hashes are unchanged.

## Environment

Run on 2026-08-08 against `0daa3e7`.

| piece | how |
|---|---|
| Backend | `subterra-test` image with **the repo bind-mounted read-only at `/app`** |
| Database | the running `subterra_data_platform-db-1` PostGIS container, over the compose network |
| Frontend | `next dev` on :3000 (Next 16.3.0, Turbopack) |
| Browser | the installed Chrome, driven by the Python Playwright already present |

```bash
docker run -d --rm --name subterra-verify-api \
  --network subterra_data_platform_default -p 8000:8000 \
  -v "$PWD:/app:ro" --tmpfs /app/logs:rw -w /app \
  -e DATABASE_URL="postgresql://subterra:subterra@db:5432/subterra_data" \
  subterra-test:viewer python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Three details that cost time and are worth not rediscovering:

- **The backend cannot run on this host.** No interpreter on the machine —
  system Python, `~/venv`, `~/venv-metal` — has `sqlalchemy`. The container is
  not a preference, it is the only way to start the API here.
- **Bind-mount the repo; do not run the image's own copy.** The image predates
  the current commits, so an unmounted run serves a backend without
  `/api/benchmark/artifacts`. Same trap as the test suite.
- **`--tmpfs /app/logs`** is required with a read-only mount: the logger opens
  `logs/subterra.log` at import and the API will not start without it.
- Port 8000 is deliberate — it is `API_BASE`'s default, so no
  `NEXT_PUBLIC_SUBTERRA_API` override is involved and the verified
  configuration is the default one.
  **Since 2026-08-09 that default is 8001**, matching the port
  `docker-compose.yml` publishes; the reasoning is unchanged, so a later run
  should publish **`-p 8001:8000`** and still involve no override. The command
  above is left as it was actually run.

Playwright has no browsers in its cache; Chrome is driven directly via
`executable_path`. No browser download was needed.

## What was checked

Eleven routes: `/`, `/datasets`, `/benchmark`, `/datasets/{id}` for **all six**
datasets held, and the legacy `/viewer` and `/client`. For each: HTTP status,
console errors, page errors, failed requests, 4xx/5xx responses, rendered text
and a full-page screenshot. Then one interaction pass: select a layer and watch
view resolution happen.

## Results

**No page errors and no failed requests on any route.** Every 4xx observed is a
documented refusal being displayed rather than a fault:

| observed | verdict |
|---|---|
| `400` on `/api/datasets/{id}/trace_grid?field=signal`, all 6 datasets | expected. The UI renders the backend's own sentence: *"Records are missing trace_index/depth metadata -- not genuine multi-sample GPR trace data."* |
| `404` on `/favicon.ico` from both servers | cosmetic; no icon is defined |

### The null-island claim, confirmed in a real engine

This is the finding jsdom could never produce. On INGV v1 (10,727 records,
`geographic_record_count` 0) the **embedded viewer itself** renders:

> Loaded 1 dataset(s), 0 positioned point(s) shown. 10727 record(s) carry no
> geographic position and are NOT plotted (the API reports lat/lon 0.0 for
> these; they are not located at 0,0).

The scene is empty, not a cloud of points at (0, 0). `ee963b7` did what it
says, and the workspace's banner names the position sources above it.

Note for anyone reading `bc80da1`: its description of a **gated** embed is
superseded. Current `embedded-viewer.tsx` deliberately does *not* gate — the
viewer filters on `position_kind` itself, and duplicating that judgement in the
UI would give one question two answers that can drift.

### View resolution is genuinely the backend's answer

Clicking the layer card issued exactly one `POST /api/views/resolve` → `200`,
and the pane rendered the response verbatim: `map`, `radargram`, `depth_slice`
and `scene_3d` unavailable with the backend's own `reason` and `missing`
strings, `metadata` **RESOLVED**. Five views shown, five views returned — none
invented, none dropped.

`scene_3d` carries the reason that matters to the roadmap:

> a 3D scene needs an absolute elevation for the selection, and no dataset held
> has an established vertical relationship: the GPR depth axis starts at
> instrument time-zero, not the ground surface, and no source declares a
> vertical datum

### The benchmark page

Renders BAM and 4TU side by side with figures at full stored precision
(`0.06521739130434782`, not `0.065`), `BLOCKED` gates in the refusal style,
`RESOLVED` on activity-level 4TU only, and the 125/112/7/6 ground-truth split.
Nothing is rounded, combined or reinterpreted on screen.

### Integration tests: executed, not skipped

The 19 live-backend tests had never run — they self-skip when the API is
unreachable, which it always had been. With the API up:

```
Test Files  7 passed (7)
     Tests  101 passed (101)
```

`api.integration.test.ts` took **22.8 s** and `honesty.integration.test.ts`
**29.4 s**, against 64 ms and 72 ms when they were no-opping. That timing is the
evidence they really ran. The frontend's honest count is now 101 executed, not
82 executed and 19 skipped.

## Open issue found: workspace pages are slow, not broken

Two dataset pages exceeded a 45 s `networkidle` budget. They are not hung —
given time they render completely and correctly:

| dataset | records | settles at |
|---|---|---|
| Lazaresti GPR depth slice | 157,040 | **75 s** |
| INGV-UNISA Site 1 GPR (v1) | 10,727 | **35 s** |

Cause, measured rather than guessed. Each endpoint is fast alone (~2 s), but
five concurrent requests take a wall time equal to their **sum** (8.9 s for
four ~2 s calls). The handlers are synchronous `def`, so FastAPI runs them in
its threadpool — and the work is CPU-bound Python building large JSON payloads,
so the GIL serialises them. On top of that the embedded viewer fetches
`/api/datasets/{id}/points`, which is 2.8–6.4 MB and 2.7–7.1 s on its own and
occupies the same lane.

Nothing here is a correctness or honesty defect, and **no fix was attempted**.
Recorded so the slowness is understood as a known cost rather than mistaken for
a hang.

## Not defects

- A circle overlapping the sidebar legend in screenshots is `NEXTJS-PORTAL`,
  Next's dev-mode indicator. It does not exist in a production build.
- `frontend/AGENTS.md` and `frontend/CLAUDE.md` are written by `next dev`
  itself (Next 16 `generate-agent-files.js`), not by hand.

## Still unverified

- **The production build in a browser.** Everything above is `next dev`.
  `next build` passes, but `next start` was not exercised in Chrome.
- **Responsive layout.** One viewport only (1440×1400, dark theme).
- **Accessibility.** No keyboard-only or screen-reader pass.
- **Object and label selection.** Every dataset held has zero objects and zero
  labels, so only the *frame* selection path could be exercised on real data.
- **A resolved `scene_3d`.** It is unresolvable for every dataset held, by the
  backend's own answer. The inverted test in `view-resolution.test.tsx` remains
  the only check that a resolved scene would render, and it stays jsdom-only
  until a vertical registration exists.

---

# Pass 2: the Phase 7 sweep, verified

Run on 2026-08-22 against `22b08ba`. This closes the "re-verification is still
owed" gap the roadmap recorded against the first pass, which predated
composition honesty, DEM support, device modality parity and the entire
`/fusion` route.

**Nothing in this pass modified the repository's source, the benchmarks or
the artifacts.** Two accounts and several datasets were created through the
running application as test fixtures; they exist only in the dev database
this pass stood up and are not part of the committed tree.

## Environment

| piece | how |
|---|---|
| Backend | `subterra_data_platform-api:latest` image, **repo bind-mounted read-only at `/app`**, run as a replacement for a stale 8-day-old container that had no bind mount (see finding below) |
| Database | the existing `subterra_data_platform-db-1` PostGIS container |
| Frontend | `next dev` on :3000 (Next 16.3.0, Turbopack), restarted clean mid-session (see finding below) |
| Browser | Playwright MCP's own Chromium (`chrome-for-testing`), not installed at session start |

### Finding: Playwright's browser was not installed

The MCP tools were registered but `browser_navigate` failed with "Browser
'chrome-for-testing' is not installed" on the first call. Fixed by running
`npx @playwright/mcp install-browser chrome-for-testing` (downloads ~270 MB).
Not a product defect — a environment-setup gap in this session, recorded so
the next session does not waste time treating it as a backend problem.

### Finding: the running API container was 8 days stale

`docker ps` showed `subterra_data_platform-api-1` already up, but
`docker inspect` showed no bind mount over `/app` — only `datasets/`,
`logs/`, `artifacts/`. The image was built 8 days before this pass, predating
nearly all of the Phase 7 commits (fusion redaction, DEM enum, run-fusion
control, the generic 422 serializer). Verifying against it would have
silently re-run the *first* pass. Fixed by stopping it and starting a
replacement bind-mounting the current working tree read-only, matching the
pattern this document already prescribes for exactly this reason. Confirmed
current by watching migrations 008–012 (device adapter, session survey
area/CRS/vertical reference/processing version) apply on startup — those are
Phase 3 additions, so their presence proves the mounted code is current, not
the 8-day-old baked image.

### Finding: `next build` run alongside a live `next dev` corrupts its chunks

Running `next build` in the same `frontend/` directory as a *live* `next dev`
process (to verify the production build compiles, per the audit's baseline
step) overwrote `.next/`, which both commands use by default. The running
dev server then 500'd on every static chunk until restarted. Confirmed by
`.next/BUILD_ID` timestamp matching the build, not the dev server's start
time. Not a product defect — a test-sequencing hazard in this session.
Fixed by killing and restarting `next dev` after the build. Recorded so a
future pass runs `next build` in a separate worktree or after tearing down
`next dev`, not alongside it.

## Baseline

| check | result |
|---|---|
| Backend tests | **2,188 passed, 0 failed**, Docker, fresh `subterra-test` image built from `22b08ba` (1012.7s) |
| Frontend tests | **570 passed (34 files), 0 failed**, including the live-backend integration suites (`api.integration.test.ts` 28.9s, `honesty.integration.test.ts` 179.3s — real network time, not the 64–72ms self-skip) |
| Typecheck | `tsc --noEmit`: clean |
| Lint | `eslint .`: clean |
| Production build | `next build`: compiles, all 16 routes generate (7 dynamic, 9 static) |

## What was checked, and how

A real account was registered through `/register` and used for every
authenticated workflow below (Playwright, real Chromium, real network calls
to the bind-mounted API — no mocking).

### Composition honesty

Checked the dataset list, dataset switcher, a dataset workspace
(`Lazaresti COP30 DEM`, declared `satellite`), its report, and its
candidates route. Every surface says "Declared sensor: satellite" or
"declared satellite" — never presents it as the recorded instrument. The
signal chain, radargram pane, candidates pane and dataset-report capability
rows all render the same sentence: *"this dataset's recorded modality
composition is satellite; \[X\] does not apply to it"* (X = the GPR
signal-processing chain / a radargram / candidate analysis / object
classification, as appropriate to the surface). Confirmed the console carries
no errors beyond the one already-documented `400` on
`trace_grid?field=signal`.

### DEM support — full workflow, not just the picker

Uploaded a real GeoTIFF (`SRTMGL3_36.7_-120.2_36.8_-120.1.tif`, 9,252 bytes)
through `/import`.

- The declared-sensor-type picker showed the full ten-member enum (`gpr`,
  `seismic`, `magnetometer`, `ert`, `gravity`, `lidar`, `dem`, `satellite`,
  `gps`, `imu`) with **no member pre-selected** — the Import button stayed
  disabled until an explicit choice was made — and **no `other`**.
- After declaring `dem`, the "What arrived" screen offered the Band-1
  elevation checkbox described in the roadmap ("Band 1 of this raster is
  elevation in metres") with the honesty caveat that this is the operator's
  claim, not something the file stated.
- The completed import: 144 records, 144/144 positioned, `EPSG:4326`,
  vertical datum honestly `NOT DECLARED`, Candidates `BLOCKED` with *"this
  dataset's recorded modality composition is dem; candidate analysis is a
  GPR-trace capability and does not apply to it"*.

**DEM preprocessing semantics (item asked for by this audit): verified safe,
left alone.** `default_preprocessing_mode(DEM)` falls through to `"trace"`
(`api/routes/datasets.py`), and the import log confirmed it actually ran:
`Preprocessing pipeline (mode=trace) applied to 144 records`. Read the
converter and the pipeline to check whether that is harmful: `GeoTIFFConverter`
writes `signal=[float(val)]` (`converters/geotiff_converter.py:168`) and never
sets `depth` (stays `None`, the schema default). In `mode="trace"`,
`remove_outliers`/`denoise_signal` both short-circuit below their length
thresholds (`len(signal) < 3` / `< window`) and `normalize_signal`
short-circuits on `std == 0`, which a one-element array always has;
`interpolate_missing_depth` needs 2+ known depths and gets zero. All four
steps are therefore a **provable no-op** on a DEM record, not merely an
untested one. No new DEM preprocessing mode was implemented — the existing
fallback has no product consequence, exactly the outcome the audit prompt
asked to confirm before building anything.

### Device registration parity

Registered a physical device (`TestMfg TM-GPR-1`) through `/devices`: the
same ten-member enum, no pre-selected default (Record button stayed disabled
until a type was chosen), and a separate "Other modalities" checkbox group
that appears after the primary type is picked and correctly excludes it from
its own list. Declared `gpr` as primary plus `gps` and `imu` as additional
modalities; the saved card read "Modalities: gpr, gps, imu". **Reloaded the
page** — persistence confirmed, no console errors.

### Fusion — preview, then save, end to end

On `/fusion`, left every dataset unchecked (fuse everything visible) and
clicked Preview. The request took **~2 minutes** wall time — not a hang;
`docker logs` showed the backend genuinely processing 200,288 records (21,454
excluded for no horizontal position) into 352 spatial cells, 9 multimodal,
before returning `200`. This matches the already-documented "slow, not
broken" pattern from Pass 1 (synchronous handlers, GIL-serialized, CPU-bound
JSON work) extended to a new endpoint — **no fix was attempted, matching the
Pass-1 precedent**, but note below the one gap Pass 1 didn't have.

The preview rendered 9 samples (all `gpr`+`satellite`, from the two public
Lazaresti datasets), each with `radius_m` and `n_reprojected` populated.
"Save these samples" was disabled until the preview matched the current
configuration by value, then enabled after Preview returned. Clicking it
persisted successfully (`POST .../fusion/run?...persist=true` → `200`,
another ~2.5 minutes of real compute) and the UI correctly showed "Saved. Change
a setting and preview again to run another fusion," with Save re-disabled.
Zero console errors across the entire flow.

**Minor UX gap found, not fixed:** neither Preview nor Save shows any
loading/progress affordance during the multi-minute wait beyond the button
itself going disabled. Given the Pass-1 precedent of documenting slowness as a
known cost rather than fixing it, and that this is a UX polish item rather
than a correctness or honesty defect, it is recorded here rather than
patched.

**Redaction:** the live run above happened to produce samples entirely from
two *public* datasets, so it did not exercise the foreign-id-redaction path
by coincidence of geography (the private test datasets imported this session
were in California and Italy; the public samples are all in Romania and
outside the fusion radius). Verified instead by: (1) a direct second-account
check — registered `audit-user2@subterra.test` and confirmed `GET
/api/fusion/samples` under that account contains zero references to either
private dataset id created in this session, and (2) the dedicated backend
test `test_a_shared_samples_partner_id_is_redacted_not_shown_or_dropped` in
`tests/test_auth_and_ownership.py`, part of the 2,188 passing above.

### Negative/error paths — the generic 422 serializer, confirmed live

Registered with a 1,100-character password (no client-side `maxlength`
exists on the field; the server enforces `max_length=1024`). FastAPI's own
request validation returned a structured 422
(`[{"loc": ["body", "password"], "msg": "String should have at most 1024
characters", ...}]`). The UI rendered:

> password: String should have at most 1024 characters

not `[object Object]` — confirming `formatDetail()` in `services/api.ts`
handles a real structured 422 through an actual form submission, not only
through its unit tests (`api-error-detail.test.ts`, 5 tests, already
passing).

### A genuine GPR line, not just refusals

All six originally-held datasets are point/CSV-derived and correctly refuse
the radargram view (*"Records are missing trace_index/depth metadata"*) —
matching Pass 1 exactly, still true. To verify the **positive** path,
imported a real multi-sample SEG-Y line (`C1T_7,5_0001.SGY`, the same line
the regression baseline pins) as `gpr`. Processing correctly resolved to
`gpr_full` (the benchmark-aligned default, confirmed live, not just by
reading code). The radargram rendered a genuine local-anomaly z-score B-scan
from 34,704 records and reported *"No candidates on this survey line. That is
a result, not a failure: no region satisfied the generation rule"* — the
honest near-chance detector behaviour the roadmap already documents, now
seen rendering correctly rather than only measured offline.

## Result

No regressions found. No genuine product bugs found. Every Phase 7 change
audited (composition honesty, DEM, device parity, fusion, the 422 serializer)
behaves in the browser exactly as its commit message and the roadmap claim.
The only code-adjacent output of this pass is confirmation that the DEM
preprocessing fallback needs no change (see above) — no source file was
modified.
