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
