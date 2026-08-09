# Subterra frontend

The workspace UI for the Subterra Data Platform. **Presentation layer only** —
the FastAPI backend remains authoritative for all data, all spatial
mathematics and all scientific judgement.

## Status

The adapters are wired to the live FastAPI backend, the dataset workspace and
the benchmark page render real data, and the existing Plotly viewer is
embedded. Nothing on screen is sample or placeholder data.

Verified in a real browser against `0daa3e7` — all six datasets held, plus the
legacy `/viewer` and `/client`, with no page errors and no failed requests. See
`../docs/browser-verification.md` for what that pass did and did not cover.

`/` is **The Descent**: a nine-stage scroll narrative — surface, break, signal,
candidate, frame, fusion, provenance, gates, view — that follows the platform's
own pipeline. It fetches nothing, so it renders when the API is down. Every
figure is closed-form SVG geometry captioned as illustrative; the only live
facts on it are the two blocked gates (rendered with the workspace's own
`BlockedGate`) and the provenance vocabulary from `lib/provenance`. Motion is
CSS scroll-driven animation with a single `IntersectionObserver`; base styles
are the finished state, so reduced-motion and unsupported browsers get the
whole narrative.

Not done yet:

- **UI for four backend route groups** — `exports`, `fusion`, `sources`,
  `training`. The adapter covers datasets, objects, labels, overlays, views,
  provenance, trace_grid and benchmark.
- **Large datasets are slow.** The 157k-record workspace page needs ~75 s to
  settle; the cause is measured and recorded in the browser-verification doc.

## Running

The package manager is pinned via `packageManager: pnpm@9.15.4`. The pnpm on
`PATH` may be older (a v9 lockfile needs pnpm ≥ 9), so invoke it through
corepack:

```bash
corepack enable            # once
corepack pnpm install
corepack pnpm dev          # http://localhost:3000
```

The backend is expected at `http://localhost:8001` — the port
`docker-compose.yml` publishes, because Subterra Core already holds 8000. That
is the default, so `docker compose up` and `corepack pnpm dev` work together
with nothing to configure; set `NEXT_PUBLIC_SUBTERRA_API` only for a different
deployment. The existing `/viewer` and `/client` pages are untouched and remain
fully functional; the workspace header links to both.

```bash
corepack pnpm typecheck    # tsc --noEmit
corepack pnpm lint         # eslint .
corepack pnpm build        # next build -- fails on a real type error
```

## Relationship to the two existing UIs

| | what it is |
|---|---|
| `/viewer` (`visualization/viewer.html`) | The proven Plotly 3D / point-cloud / heatmap / B-scan viewer. Authoritative for spatial visualisation. |
| `/client` (`visualization/thin_client.html`) | The thin client. **The information-architecture reference for this app.** |
| `frontend/` (this) | The same information architecture in the Subterra design language. |

This app does not replace either. Visualisation is integrated **by embedding**
the existing implementation rather than porting it, so that no scientific
calculation is duplicated in TypeScript. A React port stays off the table until
parity is demonstrated.

## The rules this codebase is built around

These are not style preferences. Each mirrors a guarantee the backend makes
and, in most cases, a Python test that enforces it.

1. **A position is a discriminated union, not an optional coordinate.**
   `types/subterra.ts` has no variant carrying an optional lat/lon: a sample
   either has a geographic position or a documented reason for having none.
   Defaulting something to `(0, 0)` is unrepresentable, not merely
   discouraged.

2. **Unknown confidence is not zero confidence.** `confidence: null` means
   the source stated none. It renders as an em-dash with no bar drawn —
   never `0.0%`, which would be a fabricated measurement.

3. **The backend decides what can be displayed.** Which views can show a
   selection is answered by `POST /api/views/resolve`. The UI renders
   `reason` and `missing` verbatim and never substitutes its own text.
   `scene_3d` is currently unresolved for every dataset held; that renders
   as a designed unavailable state, never as a drawn scene.

4. **No synthetic geometry in the workspace.** The v0 design's
   `UndergroundScene` generates its point cloud with `Math.random()`. It is
   decorative art and may only ever appear on the marketing page, clearly
   labelled as illustrative.

5. **Five states, never collapsed.** empty / unpositioned / unavailable /
   unassociated / error are rendered differently by `StateBox`. "There are
   no objects" and "there are objects this view cannot place" are opposite
   statements about the data.

6. **Provenance is a first-class visual token,** with its own palette. It is
   deliberately not a ramp: the backend notes that "'assumed' and 'inferred'
   are different kinds of doubt, not different amounts", so each class gets
   its own hue and every chip renders its text label.

7. **Benchmark figures pass through untransformed.** Nothing here
   recomputes, rescales, rounds away or reinterprets a benchmark number, and
   BLOCKED gates render as blocked.

## Deliberate deviations from the v0 design export

| v0 | here | why |
|---|---|---|
| `typescript.ignoreBuildErrors: true` | removed | the correctness rules above live in the type system; suppressing type errors would defeat them |
| `@vercel/analytics` | removed | a local scientific tool should not beacon to a third party |
| `next/font/google` (Geist) | system font stack | keeps the build hermetic — no network fetch at build time |
| pnpm, version unpinned | pnpm pinned via `packageManager` | the pnpm on `PATH` is 8.15.1 and cannot read a v9 lockfile; corepack supplies 9.15.4 reproducibly |
| Recharts | not installed | nothing charts yet, and Plotly already serves the platform's visualisation |
| `Scan` / `Sensor` / `SystemHealth` / `Operator` types | not ported | the platform ingests files, not live instruments; it has no job lifecycle, telemetry or auth |

## Layout

```
app/
  (workspace)/            sidebar + header shell
    datasets/             dataset index
    datasets/[datasetId]/ three-pane workspace (thin-client IA)
    benchmark/            BAM and 4TU results
components/
  ui/                     shadcn primitives, ported from v0
  brand/                  logo
  shell/                  sidebar, header
  subterra/               the honesty primitives -- StateBox, ProvenanceTag,
                          UnavailableView, NotOnMap, ConfidenceValue
lib/                      cn, provenance metadata, formatters
types/subterra.ts         domain types, transcribed from the backend schemas
```
