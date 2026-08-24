# Grimsel GPR position-zero reconciliation — final pre-contact check

**Question.** Can the GPR profile's position zero be established from evidence
already publicly available, without contacting ETH?

**Answer: No.** Both candidate leads were investigated to their source and
neither closes the gap. One (`AUgallery.txt`) is ruled out outright — it
describes an unrelated physical feature. The other (Figure 3a) is a
schematic with no embedded coordinates or station numbers; its only new
contribution is qualitative. **The GPR-to-grid relationship stays
Category C (approximate/inferred) for the specific numeric tie.** No score
increase is applied. This also corrects an overstated claim in the prior
pass's own report (§4).

**No platform state changed. No files were retained** — the figure image
downloaded for direct inspection was viewed and deleted; nothing was
committed to the repository beyond this document.

---

## 1. What `AUgallery.txt`'s "32.33 m" actually means

Full file content, already captured verbatim in the prior pass and
re-examined here against the accompanying source code (`tunnel.m`), which
names every field:

```
AU gallery:
length 67.0381 approx. diam: 2.4

length: 6.7
distance to crossing: 32.3331

667472.5905   158922.9470   1747.8140
667470.9550   158856.2410   1747.6370
667468.1935   158890.8360   1747.7522
```

```matlab
Tunnel.AUgallery.diameter = 2.4;              %m
Tunnel.AUgallery.lengthNS = 67.0;             %m
Tunnel.AUgallery.lengthEW = 6.7;              %m
Tunnel.AUgallery.distfromStoCross = 32.33;    %m
```

**This is a different physical structure from the AU tunnel the GPR ran
in.** Three independent pieces of evidence establish that, not one:

1. **Diameter.** The gallery is 2.4 m; the AU tunnel itself is 3.475 m
   (`Tunnel.AU.diameter`, same source file). A different bore diameter is a
   different excavation.
2. **Shape.** The gallery has two stated leg lengths in two directions
   (`lengthNS = 67.0`, `lengthEW = 6.7`) — a dog-legged side passage, not a
   single straight run like `AUTunnel.txt`'s two-point line.
3. **Naming.** `AUgallery` is one of four distinct AU-prefixed files
   alongside `AUTunnel`, `AUcavern`, and `AUexcav` — the archive's own
   convention keeps these as separate physical features throughout (this
   was also true of the `tunnel.m` function, which loads all four as
   separate structures and never merges them).

The variable name itself settles the semantics: **`distfromStoCross`** —
distance from the gallery's own **S**tart to where it **cross**es
something (almost certainly the AU tunnel or another gallery it
intersects) — a property of the gallery's internal geometry, elicited from
whoever built this MATLAB model to plot the gallery's own bend correctly.

**Conclusion, stated plainly, per the task's own instruction not to
assume:** "distance to crossing: 32.33 m" refers to the **AU gallery's own
shape**, not to the GPR profile, not to a tunnel chainage the GPR used, and
not to any quantity that reconciles the 49.03 m GPR length against the
44.59 m `AUTunnel.txt` segment. **This lead is ruled out, not partially
useful.** It does not appear again in the reconstruction below.

## 2. What Figure 3a actually establishes

Fetched and viewed directly (the rendered PNG,
`se-11-1441-2020-f03-web.png`, 1,195,138 bytes downloaded and inspected,
then deleted) plus the exact caption and the one body paragraph that
references it, quoted verbatim from the open-access HTML:

**Caption:** *"Acquisition geometry for the three geophysical data sets. GPR
data were acquired using shielded antennas in the tunnels (a) …"*

**Body text:** *"Common-offset measurements with an antenna spacing of
0.33 m were performed in the VE and AU tunnels (Fig. 3a) with the imaging
plane oriented in the direction of the experimental volume (approximately
45° from the vertical towards the east and west, respectively)."*

**What the panel shows, described from direct inspection:** the AU tunnel
(vertical cylinder) and VE tunnel (diagonal cylinder) as 3D schematic
shapes, a red line labelled "GPR profile AU" drawn along nearly the full
visible length of the AU tunnel cylinder, a matching red line for "GPR
profile VE" along the VE tunnel, blue arrows annotating "45° inclined
downward" (the antenna tilt, already known from the text above) and a
"Measurement direction" arrow, translucent surfaces labelled `S1.0`,
`S3.1`, `S3.2`, `S1.1`–`S1.3` (the shear-zone surfaces from the geological
model, drawn for context), and a 25 m scale bar.

**What it does not show:** any coordinate axis, tick mark, station number,
distance label, or numeric annotation tying the red "GPR profile AU" line
to a specific tunnel position. The caption and the only body paragraph
that describes it give **antenna geometry** (spacing, tilt), which this
audit already had from the `.rad` header and the prior pass's paper read —
**not new positional information**.

**On why this was not pixel-measured:** panel (a) is a **3D perspective
schematic**, not an orthographic technical drawing. The scale bar and the
GPR profile line are not confirmed to lie in the same depth plane, so a
pixel-ratio measurement between them would not be deterministic — it would
be exactly the kind of visual estimate the task instructs against treating
as a coordinate. **No pixel measurement was attempted or is reported as a
number.**

**One qualitative fact, and only qualitative:** the red profile line
visibly spans very close to the AU tunnel's full drawn length, not a short
sub-segment. This is consistent with — but does not prove — the hypothesis
that the 49.03 m GPR profile extends somewhat beyond the specific
44.59 m two-point segment `AUTunnel.txt` describes (e.g. into the cavern
or portal). It is recorded as a **hypothesis the figure is consistent
with**, not a fact the figure establishes.

**Panel (c), checked for completeness:** shows a genuine axis-labelled 3D
plot (East [m], North [m], Height [m]) of the AU and VE tunnels and
boreholes for the **3D seismic** survey specifically — not the GPR. Its
axis ranges (East to ~70 m, North to ~140 m in the local, origin-subtracted
frame) are broadly consistent with the local coordinates implied by
`AUTunnel.txt` (≈73 m East, 105–149 m North after subtracting
667400/158800), which is a useful sanity check that the two independently
read sources describe the same tunnel — but panel (c) does not draw the
GPR profile at all, so it adds no direct evidence for §3.

## 3. Deterministic reconstruction — not attempted

**Neither source establishes position zero, so no coordinate
reconstruction is performed.** Forcing one from what is available would
require silently assuming which end of the tunnel the GPR started from and
how the residual ~4.4 m is distributed — exactly the assumptions the task
prohibits. Nothing is calculated in this section.

## 4. Cross-check — including a correction to the prior pass

Run against everything already in hand, per the task's instruction to
report conflicts rather than adjust them away:

| Check | Result |
|---|---|
| GPR filename direction ("N-to-S") vs. `AUTunnel.txt`'s due-north-south segment | **Consistent** — independent corroboration, unchanged from the prior pass |
| GPR length (49.03 m) vs. `AUTunnel.txt` segment length (44.59 m) | **Conflict, unresolved.** A ~4.4 m gap remains; Figure 3a is only qualitatively consistent with the profile running slightly longer than this one documented segment, not quantitatively confirmatory |
| Figure 3a profile extent vs. tunnel drawing | Qualitatively consistent (profile spans nearly the full drawn tunnel) — **not a numeric check** |
| `plot_GPR.m` horizontal offset (local +55, +145) vs. `AUTunnel.txt` point 1 (local ≈ +73.09, +149.14) | **Conflict, confirmed again.** ~18 m difference in the easting-equivalent axis; the vertical-only near-agreement noted below does not extend here |
| **`plot_GPR.m` vertical offset vs. tunnel elevation — correction to the prior report** | **The prior pass's claim that these "agree to better than a metre" was an overstatement and is retracted here.** Re-deriving the formula (`z = ry·sin(Dip) + 34 − 24.5`, `Dip = −60°`, `ry` ranging 0 to −52) shows `z` spans **≈ +9.5 to +54.5** across the draped image, not a single value — it is a *tilted surface*, not a point. The tunnel's local elevation (≈ +33.3 to +33.6, from `1733.3–1733.6 − 1700`) falls **within** that broad range, which is a much weaker statement than "agrees to within a metre." Recorded honestly here as a self-correction, not restated as evidence for anything |

**No adjustment was made to force agreement.** The 4.4 m length conflict
and the 18 m horizontal offset conflict both stand unresolved.

## 5. GPR-to-grid classification

### **C — Approximate/inferred.**

Not A: nothing states the coordinates directly. Not B: no documented
geometry lets the position be computed without an unstated assumption
(which specific tunnel reference point is the GPR's zero, and how the
4.4 m residual is distributed). What is known — the tunnel's true 3D path,
the profile's approximate orientation and near-full-tunnel extent, and the
antenna geometry — is real and useful for a future computation, but does
not itself constitute one.

## 6. Grimsel score — unchanged

**No rubric category is re-scored.** Per the task's own instruction ("if
it remains C or D, do not artificially increase the score"), and because
this pass's findings are two negative/inconclusive results rather than new
positive evidence, **the score stays at 78/100** (`docs/grimsel-geological-model-file-audit.md`).
The one correction in §4 (the vertical-offset overstatement) does not
change any scoring line either, because that line was never scored on the
strength of `plot_GPR.m`'s agreement in the first place — it was reported
as corroborating colour, not counted as points.

## 7. Grimsel classification — unchanged

### **B — Conditional benchmark.**

## 8. Remaining scientific uncertainty

- **GPR profile absolute start/end coordinates: still unknown.** Neither
  investigated lead provides them.
- **The 4.4 m length discrepancy between the GPR profile and the
  `AUTunnel.txt` segment: unresolved**, and no longer has an untested
  candidate explanation (the gallery lead is closed).
- **Which tunnel endpoint is the GPR's position zero: unknown.**
- Everything already listed as open in the prior two audits (vertical
  datum realisation, positional uncertainty on the shear-zone surfaces,
  rotation between local and true-north frames) remains open, untouched by
  this pass.

## 9. Questions for ETH — separated, scientific vs. licensing

**Only the scientific/geospatial questions are new or sharpened by this
pass.** The licensing questions are reproduced unchanged from
`docs/grimsel-deep-evidence-audit.md` for completeness, clearly separated,
not sent.

### Scientific / geospatial

1. Which point on the AU tunnel (as given in `AUTunnel.txt`, absolute
   Swiss-grid coordinates 667473.09/158949.14/1733.33 and
   667473.09/158904.55/1733.59) corresponds to the GPR profile's
   `START POSITION: 0.000000`?
2. The GPR profile is 49.03 m; the `AUTunnel.txt` segment between those two
   points is 44.59 m. Does the profile extend beyond one or both of those
   points — for example into the AU cavern or gallery — and if so, by how
   much at which end?
3. Is there a rotation, in addition to the stated translation, between the
   visualization tool's local coordinate frame (origin 667400/158800/1700)
   and true Swiss-grid north?
4. What vertical datum realisation underlies "Elevation = 1700" in that
   coordinate definition?
5. What is the estimated positional uncertainty of the interpolated S3
   shear-zone surface?

### Licensing (reproduced from the prior audit, unchanged)

6. Does the GPR/seismic dataset's "non-commercial use" rights statement
   extend to derived validation metrics computed from the raw traces, or
   only to the raw files themselves?
7. Would academic benchmarking of a software platform that may later
   become commercial fall inside or outside "non-commercial use" as
   intended by the rights-holder?
8. May numerical results derived from this dataset be published in
   Subterra's own documentation?

## 10. Is Grimsel ready for the next licensing/author-confirmation stage?

**Yes — but only for the combined question list above, not as a claim
that the scientific question is close to resolved.** The scientific gap
(position zero) turned out not to be closeable from public evidence after
genuinely trying both available leads, which is itself the useful result
this pass was asked to produce: it converts "we haven't looked yet" into
"we looked, and here precisely is what's missing." Sending the combined
list is a reasonable single round-trip to the same two contacts already
identified (Doetsch, Krietsch) rather than two separate emails — but that
is a recommendation for the next task to act on, not an action taken here.

---

## What was not done, per the task's explicit instructions

No email was sent. No legal conclusion was drawn. No coordinate was
invented or estimated from pixels. No production code, converter,
localisation logic, 3D reconstruction, or benchmark adapter was touched.
The figure image downloaded for direct inspection was viewed and deleted;
nothing from this pass was committed to the repository beyond this
document.
