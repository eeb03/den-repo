# TU1208 target geometry — transcription

The IFSTTAR geophysical test site's published target geometry, turned into
machine-readable ground truth. **Nothing is computed from a radargram**; no
velocity, no time-zero, no depth conversion, no detector label.

| | |
|---|---|
| Source | Dérobert & Pajewski (2018), *Remote Sensing* 10(4) 530, [10.3390/rs10040530](https://doi.org/10.3390/rs10040530), CC-BY-4.0 |
| Archive | Zenodo [10.5281/zenodo.1211173](https://doi.org/10.5281/zenodo.1211173), CC-BY-4.0 — **contains no target geometry** |
| Provenance class | `transcribed_from_publication` |
| `verified_by_subterra` | **false**, everywhere |
| Files | `benchmark/tu1208_targets.json` · `benchmark/tu1208_truth.py` · `tests/test_tu1208_target_truth.py` |
| Truth version | `tu1208-1-880e504036decbc4` (content hash) |

## 1. What was transcribed

**36 pipe targets** — 4 regions × 3 layers × 3 pipes — plus **18 other published
depths**, **5 multilayer thicknesses**, **4 modelled permittivities**, and **67
profile records**.

### Pipe-layer depths, as published

| Region | Figure | Layer 1 | Layer 2 | Layer 3 |
|---|---|---|---|---|
| silt | Fig 6 | **−0.80** | **−1.20** | **−1.83** |
| limestone | Fig 9 | **−1.20** | **−1.70** | **−2.40** |
| gneiss 14/20 | Fig 11 | **−0.90** | **−1.50** | **−2.10** |
| gneiss 0/20 | Fig 13(a) | **−1.15** | **−1.56** | **−2.20** |

**Four media, not three.** The Stage 22 audit summarised "Gneiss" as one region
at −0.90/−1.50/−2.10. That is Gneiss **14/20** only; Gneiss **0/20** is a
separate region with different depths, and merging them would fit one velocity
across two materials. A test holds them apart.

Three distinct depths per medium is the property that matters: it makes a later
`t = t0 + 2d/v` fit over-determined, so it yields residuals rather than an
assertion. **That fit is not performed here.**

### Pipe identity

Published composition, quoted: *"three pipes per layer: an empty steel pipe, a
PVC pipe full of water, and an empty PVC pipe (this is the laying order in all
layers, starting from the longitudinal axis of the test site)"*. Length 2.5 m.
Each `PipeTarget` carries its identity and its ordinal position from the axis —
**not** a distance, which is unavailable.

### The control region

The multilayer region is recorded as **attested empty of targets**: *"There are
five layers and no targets."* A statement of absence, not a blank field — the
same distinction `benchmark.ground_truth` draws for 4TU. Its caveat travels
with it: five material interfaces are real reflectors, so it controls for
*embedded targets*, not for "no reflector".

Its five published thicknesses (0.80 / 0.60 / 0.60 / 1.30 / 0.60 m) yield
interface depths by cumulative sum. Those are exposed separately as
`InterfaceDepth`, every instance flagged `derived=True` with its derivation
stated, because the figure prints thicknesses and never prints an interface
depth.

## 2. Files: all 67 verified

`resolve_files` requires a **bijection in both directions** — every published
name matches exactly one archive file, every archive radargram is claimed
exactly once, and each sits in the region directory the paper assigns it.

| Region | Directory | Paper | On disk |
|---|---|---|---|
| silt | `SILT` | 15 | 15 |
| multilayer | `MULTI-LAYER` | 4 | 4 |
| limestone | `LIMESTONE` | 15 | 15 |
| gneiss 14/20 | `GNEISS14-20` | 15 | 15 |
| gneiss 0/20 | `GNEISS0-20` | 18 | 18 |
| | | **67** | **67** |

The paper and the archive **disagree cosmetically** on several names, so
matching folds case and the `-`/`_` separators:

| Published | On disk |
|---|---|
| `200MHz_Limestone_2.dzt` | `200MHz-Limestone_2.dzt` |
| `900MHz_Limestone2_rev.dzt` | `900MHz_Limestone_2_rev.dzt` |
| `250MHz_Limestone2_rev.rd3` | `250MHz_Limestone_2_rev.rd3` |
| `350MHz_Gneiss14-20_2.dzt` | `350MHZ_gneiss14-20_2.DZT` |

The bijection requirement is what makes the fold safe: a wrong pairing would
leave a file unclaimed and raise.

`200MHz_Silt_h2h1.dzt` covers **two** acquisition lines in one file and is
recorded with `lines: [1, 2]` and the paper's explanation of the discontinuity.

Acquisition-line offsets are published as absolute numbers and are stored:
**line 1 = 1.25 m, 2 = 3.75 m, 3 = 6.25 m, 4 = 8.75 m** from the upstream border.

## 3. Surveyed, modelled, measured — kept apart

| Kind | What | Type | Notes |
|---|---|---|---|
| **surveyed** | target depths | `PipeTarget`, `PublishedDepth` | theodolite; 2 points per pipe on the upper side |
| **published numeric** | layer thicknesses, line offsets, profile metadata | `MaterialLayer`, `Profile` | printed in figures and tables |
| **derived** | multilayer interface depths | `InterfaceDepth` | cumulative sum, flagged |
| **modelled** | relative permittivity: silt 13, limestone 6, gneiss 14/20 3, gneiss 0/20 5.5 | `ModelledPermittivity` | FDTD model matching, authors' caveats attached, `is_a_velocity=False` |
| **measured radar response** | — | — | **not transcribed.** No arrival time, no amplitude |
| **inferred by Subterra** | — | — | **none** |

Permittivity is reached by its own function so that reading geometry can never
hand back a material property by accident. No code converts it to a velocity.

## 4. What is unavailable, and stays unavailable

13 quantities are enumerated with reasons. The ones that bite:

- **Pipe diameter** — never published for these pipes in any region. `None`, not
  0. (The 10-cm PVC tubes in §3.2 are the pit's drainage tubes, a different
  object, and are not borrowed.)
- **Absolute transverse offset of any target.** The sections print *segment
  lengths* on a scale bar; nothing printed ties the bar's origin to the
  longitudinal axis. Cumulative offsets would rest on a visual judgement, so
  the sequences are stored verbatim (silt and limestone
  `[0.5, 0.5, 0.7, 0.7, 0.7, 1.0, 1.0, 1.0]`; both gneiss regions
  `[2.0, 1.25, 1.25, 2.0]`) and per-pipe offset is `None`.
- **Which object owns three limestone depths** (−1.0, −1.5, −2.0) where the text
  describes blocks at *two* depths. `object` is `None` with `candidates`
  recorded. Same for four masonry depths in Fig 13(b).
- **Depth of the 500 mm concrete pipe** and of the **steel girder** — the latter
  because the paper says it is not drawn.
- **Along-line origin of every profile**, and **profile length for 20 of 67**
  (printed NA by the paper's own tables).
- **No CRS, no vertical datum, no absolute surface elevation.**

## 5. Two caveats that will govern any later depth experiment

**The printed 0.00 is not established to be the antenna surface.** Quoted:
*"all transversal schemes … do not show neither the 10-cm surface layer made in
limestone nor the asphalt wearing course"*, and the silt section additionally
omits *"about 30 cm of limestone"*. At least 0.10 m site-wide, ~0.30 m more in
silt, plus an unpublished asphalt thickness. Not quantified, and recorded as
`quantified: false`.

**Crown or centre?** The theodolite positioned each pipe from *"2 points on the
upper side"*, but the paper never says whether the printed layer depth is to the
crown or the centre — and with no published diameter the two cannot be related.

Both are open questions, not defects in the transcription. They are exactly the
sort of thing that would otherwise surface as an unexplained residual.

## 6. Separation from detection

Ground truth must not be reachable from the thing it judges, and that is a
property of the wiring:

- neither truth file imports `interpretation`, `preprocessing`,
  `benchmark.detection`, `benchmark.scoring` or `benchmark.association`;
- no module under `interpretation/` or `preprocessing/` mentions TU1208 at all;
- every truth dataclass is frozen, so a holder cannot edit a depth;
- `PipeTarget` carries no `label`, `score` or `y` field — a target depth is
  evidence, not a class;
- the module source is checked for `m/ns`, `299792458`, `sqrt`, `time_zero` and
  `t0 =`, none of which appear.

## 7. Identity

`truth_version()` is a **content hash of the transcription** — depths,
permittivities, file associations, gaps and open questions. Reordering records
does not change it; changing any transcribed value does, including claiming
`verified_by_subterra: true`. It reads nothing about a detector, so a benchmark
built on it stays comparable across detector changes.

## 8. What did not change

No declaration, no readiness state, no converter, no dataset record, no schema,
no candidate scoring, no benchmark threshold, no 4TU state. **TU1208 is not
READY** — it has no CRS, no vertical datum and no absolute surface elevation,
and transcribing a depth resolves none of them. A test asserts the word
`READY` appears nowhere in the transcription.

## 9. Reproducing the source read

The paper is open access. The figures carry the depths; the tables carry the
file names:

```
curl -L -o tu1208.pdf \
  https://res.mdpi.com/d_attachment/remotesensing/remotesensing-10-00530/article_deploy/remotesensing-10-00530.pdf
```

Depths: Figures 6 (p9), 9 (p11), 11 (p12), 13 (p13), zero-indexed PDF pages.
Files: Tables 3–7. Geolocation method: §3.4. Depth-datum caveat: §3.3.1.
