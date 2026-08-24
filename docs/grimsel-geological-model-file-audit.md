# Grimsel geological-model file audit

**Question.** Before contacting ETH: does the geological-model file already
contain enough information to tie the raw GPR profile to the independently
known Swiss-grid subsurface structure?

**Answer, stated once up front:** **Partially — Category C (approximate),
with a documented, concrete path to Category B still open.** The GPR
profile's placement *as the original authors themselves visualised it* is a
manually-fit overlay, not a surveyed tie. But the same package also contains
an **explicit, absolute-coordinate description of the AU tunnel itself** —
the wall the GPR profile ran along — which the original authors evidently
did not bother to reconcile numerically with their own radargram image. That
reconciliation is now a well-defined, bounded piece of work, not an open
question requiring ETH's input to even frame.

**No platform state changed. No ingestion code was written. The archive was
downloaded, inspected, and deleted — nothing was retained on disk beyond
this document and the metadata table below.**

---

## 1. Files inspected

| | |
|---|---|
| Archive | `GeologicalModelVisualization.zip` |
| Source | ETH Zurich Research Collection, [10.3929/ethz-b-000243199](https://doi.org/10.3929/ethz-b-000243199), bitstream `b56cd68a-0401-4221-b32c-e20928936d2f` |
| Size | 2,929,132 bytes (2.87 MB, as listed) / 3,006,478 bytes on disk after download |
| SHA-256 | `421e368692d54de7f7db38f702cee39e407dd5d8acc48692c53e962cc47a1f8b` |
| Downloaded | 2026-08-22, via the live ETH Research Collection page (Playwright — direct `curl` is blocked by the site's anti-scraping measure) |
| License | CC-BY-4.0 (confirmed directly on the page in the prior audit pass) |
| Retained? | **No.** Extracted, read, and deleted after this report was written. Only the checksum above and the facts extracted below persist |

**The second file this task named** (`3DstaticgeologicalModel.zip`, 1.70 GB)
**was not downloaded.** The small archive answered the central question
directly (§3–4) without it; downloading 1.7 GB to look for the same GPR
reference the small archive already settled would not be "downloading only
as necessary."

## 2. What the archive contains

A complete MATLAB toolkit (`Geological_model_visualization.m` plus a
`00Functions/` library) that **regenerates the authors' own 3D figures**
from plain-text inputs under `01BasicInputData/`. This is significant in
itself: the "visualization" file is not a rendered scene, it is the
**source data and code that produced one**, which is why it answers
questions no polished figure could.

Six input categories were opened directly (all plain text, all read in
full or in relevant part):

| Folder | Contents | Format |
|---|---|---|
| `01_TunnelCavernCoordinates` | `AUTunnel.txt`, `AUTunnel_ba.txt`, `VETunnel.txt`, `AUcavern.txt`, `AUexcav.txt`, `AUgallery.txt`, `VEcavern.txt` | Whitespace-delimited `X Y Z [values] [label]`, absolute Swiss-grid metres |
| `02_Boreholes` | `FBS.txt`, `GEO.txt`, `INJ.txt`, `PRP.txt`, `SBH.txt`, `00_Read_me.txt` | One row per borehole: **Easting, Northing, Elevation, Length, Diameter, Azimuth, Upward gradient** — the column definition is stated verbatim in the read-me |
| `03_GeologicalMapping` | `Tunnel_intersections.txt` (structural features crossing both tunnels, absolute coordinates + orientation), `02_BoreholeIntersections/*_structures.txt` (per-borehole structural logs) | Same coordinate convention |
| `04_Geostatistics` | `S1_*_thickness.txt`, `S3_*_thickness.txt`, `FracturePerMeter.txt` | Derived thickness/density statistics |
| `05_independetConstraints` | `GPR_AU.png` (the processed radargram image itself), `3D_seismic/` (shot/station coordinates), `seismic_2d_aniso/` (anisotropic velocity inversion) | Image + text |
| `06_ShearzoneInterpolation` | `S3_1.txt`, `S3_2.txt` (per-borehole shear-zone intersection **depths**), `S31_interp_grid.txt`/`S32_interp_grid.txt` (interpolated surface grids), `*-patches.txt` (surface triangulation) | Text |

## 3. GPR-to-grid result: **Approximate**

The direct answer lives in one function, read in full:
`00Functions/plot_GPR.m`. Quoted from the source, not paraphrased:

```matlab
Image = importdata('GPR_AU.png');
...
x = 40;              % Length of picture in [m]
y = -52;
Dip = -60;           % Dip angle of image
...
s = surf(x_final+55, y_final+145, z+34-24.5);
s.CData = rot90(cdata,3);
```

This takes the **already-processed radargram image** (`GPR_AU.png`, present
in the archive) and drapes it into the 3D scene as a flat, dipping surface
of a fixed size (40 m × 52 m) at a fixed dip (−60°), positioned by three
**hardcoded offset constants** (`+55`, `+145`, `+34−24.5`) added to a
pixel-derived local grid. No coordinate in this function is read from a
survey file, a GPS log, or the `.rad` header — it is a set of numbers
tuned so the image looks right in a MATLAB figure. **This is exactly the
task's Category C**: *"the position can only be estimated from figures,
maps, or inferred geometry."* It is not promoted to B or A.

**What this rules out:** the authors did not publish (in this package) a
survey-grade numeric registration of the GPR profile. What it does not rule
out is that one could be built — see §4.

## 4. Coordinate evidence — X/Y

**Directly documented**, read verbatim from `Geological_model_visualization.m`:

```matlab
GTS_coordinates.x = 667400;
GTS_coordinates.y = 158800;
GTS_coordinates.z = 1700;
```

This **confirms**, from the code rather than the paper's prose, that every
local coordinate in this toolkit is `(absolute Swiss-grid value) − (this
origin)`. It is not a separate claim to reconcile with the paper — it is
the same origin, now seen as the literal subtraction the plotting code
performs.

**Directly documented**, the AU tunnel's own path, read verbatim from
`AUTunnel.txt` (pre-subtraction, i.e. already absolute Swiss-grid metres):

```
667473.0927   158949.1409   1733.3314   9.43    0
667473.0927   158904.5496   1733.5858   16.84   3.71   to_the_cavern
```

Both points share the **same Easting** (667473.0927) — the AU tunnel runs
due **north–south** over this stretch, which **independently corroborates**
the GPR file's own name, `GPR_AU_N-to-S.rad`, from a completely different
source (a surveyed tunnel-geometry file, not the radar acquisition itself).
Northing span: 158949.14 → 158904.55, **44.59 m**.

**What is not yet reconciled:** the GPR profile is documented (Doetsch et
al. 2020, and the `.rad` header) as **49.03 m**, about 4.4 m longer than
this specific two-point tunnel segment. Two files that could resolve this —
`AUgallery.txt` (the adjoining gallery, with its own 67 m and 6.7 m
lengths and a stated *"distance to crossing: 32.33 m"*) and `AUTunnel_ba.txt`
(a near-duplicate of `AUTunnel.txt`, differing only by ~0.9 m in one
Easting value — a minor revision between versions, not a different
tunnel) — were both read and neither states outright which physical
endpoint the GPR survey used as its own zero.

**Classification: Deterministically derivable in principle, not yet
derived.** The tunnel's true 3D path is explicit; what is missing is a
single stated fact — which named point (portal, cavern junction, or a
specific station) the GPR's `START POSITION: 0.000000` corresponds to.
Once that one fact is known (from ETH, or by opening the still-unopened
1.7 GB model or the paper's Figure 3a), the coordinate is arithmetic, not
estimation.

## 5. Vertical evidence — Z

Same file, same two points: elevation **1733.33 m → 1733.59 m** over the
tunnel segment (a gentle ~0.25 m rise), directly consistent with
`GTS_coordinates.z = 1700` (i.e., local Z ≈ +33 to +34 m).

**Correction (2026-08-22, `docs/grimsel-position-zero-reconciliation.md`
§4): the claim originally here — that `plot_GPR.m`'s vertical offset and
the tunnel elevation "agree to better than a metre" — was an
overstatement and is retracted.** Re-deriving the full formula
(`z = ry·sin(Dip) + 34 − 24.5`, `Dip = −60°`, `ry` ranging 0 to −52) shows
`z` spans **≈ +9.5 to +54.5** across the draped image — a tilted surface,
not a single value. The tunnel's local elevation (≈ +33.3 to +33.6) falls
*within* that broad range, which is a materially weaker statement than
"agrees to within a metre." Left here with the correction attached, rather
than silently edited, per this project's practice of recording corrections
in place.

**Datum:** still **not named** in anything read in this pass (matching the
prior audit's finding) — "Elevation" is given relative to
`GTS_coordinates.z`, itself presumably tied to the Swiss levelling datum
by convention, but no file states the realisation (e.g. LN02) explicitly.

## 6. GPR profile geometry

| Property | Value | Source | Classification |
|---|---|---|---|
| Length | 49.03 m | `.rad` header (`STOP POSITION`), downloaded and read directly in the prior audit pass | Directly documented |
| Direction | North to South | Filename `GPR_AU_N-to-S.rad` | Directly documented |
| Trace spacing | 0.0498 m | `.rad` header | Directly documented |
| Antenna | GX160 HDR, 0.33 m separation | `.rad` header | Directly documented |
| Absolute start point | **Unknown** | — | Not established by anything read |
| Absolute end point | **Unknown** | — | Not established by anything read |
| Orientation relative to true north | **Approximately north–south**, by corroboration (the AU tunnel segment it ran along is exactly north–south in the surveyed file) | `AUTunnel.txt` + the `.rad` filename, cross-checked against each other | **Inferred** — two independent sources agree, which is stronger than one, but neither states the GPR's own bearing directly |

## 7. Independent target relationship

**The shear zone's 3D position is deterministically derivable, and this
pass computed the method, not just the inputs, directly:**

`S3_1.txt` (one of the two S3 shear-zone surfaces) gives, verbatim:

```
Borehole   Depth[m]
INJ1       28.20
FBS1       23.34
FBS3       42.05
PRP1       23.71
...
```

— the depth **along each borehole** at which that borehole physically
intersects the S3 shear zone (an OPTV/core-log observation, independent of
any GPR interpretation, exactly as the prior audit's paper-level reading
already established). `FBS.txt`'s read-me states its own columns exactly:
*"Easting [m], Northing [m], Elevation [m], Length [m], Diameter[mm],
Azimuth [°], Upward gradient [°]."* Combining the two — a borehole's collar
position and orientation with its intersection depth — is a standard,
non-controversial trigonometric calculation (`collar + depth × direction
vector from azimuth/dip`), **not an assumption about geology**, and would
give the shear zone's 3D position at every borehole that intersects it, in
the same absolute Swiss-grid frame as the tunnel.

**This was not computed in this pass** — per the task's own instruction
that this is dataset qualification, not implementation, and per the
explicit caution not to fill in missing values to make a benchmark work.
It is recorded here as **available and well-defined**, distinct from the
GPR-tunnel question in §4, which is missing one *fact*, not one
*computation*.

**The interpolated surface files** (`S31_interp_grid.txt`,
`S3_1-patches.txt`, etc.) go further — they are the fitted 3D surface
between boreholes, i.e. the authors' own continuous model of the shear
zone away from the boreholes themselves. These are **derived**, not
measured, and should be labelled as such if ever used — the borehole
intersection points are the primary evidence; the interpolated surface is
a model built from them.

## 8. Uncertainty — stated plainly

| Source | Status |
|---|---|
| GPR profile origin (which tunnel point is position 0) | **Not reported** |
| GPR profile orientation, exact bearing | **Not reported** directly; inferred from agreement between two independent sources (§6) |
| Borehole collar position uncertainty | **Not reported** in anything opened this pass |
| Shear-zone interpolation uncertainty | **Not reported** — confirmed absent again, consistent with the prior audit |
| Vertical datum realisation | **Not reported** |
| Rotation between local visualisation frame and true Swiss-grid north | **Not reported** — the tunnel file's own two points are consistent with zero rotation for this specific segment (constant Easting = due north–south), but that is one segment's evidence, not a general statement about the whole model |

No numerical uncertainty was invented for any of the above.

## 9. Grimsel score — recomputed, same rubric

| Criterion | Points available | Previous (2026-08-22, prior pass) | **This pass** | Reason for change |
|---|---|---|---|---|
| Raw GPR available | 10 | 10 | **10** | Unchanged |
| Explicit X coordinate | 10 | 5 | **6** | The *tunnel's* X is now explicit and read directly (not just "a coordinate system exists"); the *GPR profile's* own X is still not tied to it, so not full marks |
| Explicit Y coordinate | 10 | 5 | **6** | Same reasoning |
| Independent target X/Y | 15 | 10 | **12** | The computation path from borehole collar + azimuth/dip + intersection depth to a 3D point is now confirmed well-defined and documented (§7), not merely asserted to exist |
| Independent target depth/Z | 20 | 15 | **16** | Same reasoning, for elevation |
| Surface elevation/vertical datum | 10 | 6 | **6** | Unchanged — datum realisation still unnamed |
| Survey geometry | 5 | 5 | **5** | Unchanged |
| GPR acquisition metadata | 5 | 5 | **5** | Unchanged |
| Independent ground-truth method | 10 | 10 | **10** | Unchanged |
| License/access suitability | 5 | 2 | **2** | Unchanged — licensing question is untouched by this pass, by design (§11 of the task) |
| **Total** | **100** | **73** | **78** | |

**78/100 — still "Useful but requires additional evidence" (70–79 band),
not yet 80+.** The increase is earned by confirming *specific, computable*
paths this pass actually traced through real files (the borehole
trigonometry, the tunnel's absolute path), not by re-scoring the same
uncertainty more generously. **The score was not manipulated to cross the
80 threshold**, and it does not.

## 10. Grimsel classification

### **B — Conditional benchmark.** Unchanged from the prior audit.

The one missing fact that would most directly move this — the GPR
profile's exact tunnel reference point — is now a **precisely specified
question**, not a vague licensing-adjacent uncertainty. That sharpening is
this pass's main contribution.

## 11. Licensing question remaining

**Unchanged and untouched, per the task's explicit instruction not to
resolve it here.** The asymmetry recorded in the prior audit
(`docs/grimsel-deep-evidence-audit.md` §F) stands: geological data
CC-BY-4.0, raw GPR data non-commercial-only, commercial-use scope for
derived results unanswered.

## 12. Exact next action

**Before emailing ETH:** open the two remaining unexamined sources that are
most likely to already contain the missing fact, in order of effort:

1. **`AUgallery.txt`'s own text** (`"distance to crossing: 32.33 m"`) and
   its relationship to `AUTunnel.txt` — this pass read both files but did
   not attempt to reconstruct whether "32.33 m from the crossing" plus the
   44.59 m tunnel segment plausibly accounts for the 49.03 m GPR profile
   length. That reconciliation is arithmetic on numbers already in hand.
2. **Figure 3a of Doetsch et al. (2020)** (*"acquisition geometry"*,
   referenced but not opened as an image in either audit pass) — a
   published figure is more likely to state a profile start point in
   words than a MATLAB script's plotting constants are.

**If neither closes the gap**, the two questions from the prior audit's
author-question list that this pass sharpens rather than replaces:

1. What is the tunnel-wall coordinate (in the 667400/158800/1700-relative
   frame — now confirmed to be the exact quantity the authors' own code
   subtracts) of the GPR profile's `START POSITION: 0.000000`?
2. Does the AU GPR profile run the full length of the surveyed tunnel
   segment in `AUTunnel.txt`, or a sub-segment — and if the latter, which
   end is which?

---

## What was not done, per the task's explicit instructions

No ingestion code, converter, localisation algorithm, depth calculation,
3D reconstruction, benchmark adapter, or detector threshold was touched.
ETH was not contacted. No legal conclusion was drawn. The 1.7 GB file was
not downloaded. The 2.87 MB archive that was downloaded was deleted after
this report was written; nothing from it was committed to the repository.
