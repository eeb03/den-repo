# TU1208 time-zero and velocity: **BLOCKED**

Can Subterra estimate a time-zero and a propagation velocity from measured radar
response, and predict held-out surveyed depths without using those depths to
choose the evidence?

**On TU1208, no — and the experiment stops before fitting anything.** Two
independent reasons, either sufficient on its own.

| | |
|---|---|
| Verdict | **BLOCKED** |
| Gate 1 — association | **0 of 36** surveyed targets can be tied to a measured reflector |
| Gate 2 — identifiability | **5 of 6** depth groupings leave t0 and v ≥94% confounded |
| Fitted t0 | **none** |
| Fitted velocity | **none** |
| Held-out depth error | **undefined** — zero observations |
| Platform state changed | **none** |

Reproduce: `python -m scripts.tu1208_depth_calibration --out artifacts/tu1208/depth_calibration.json`
Artifact: `artifacts/tu1208/depth_calibration.json` · Truth: `tu1208-1-880e504036decbc4`

## The model, stated once

```
t_measured = t0 + 2 d / v
```

`t0` is a system delay — the instrument's own origin plus whatever air path
precedes the ground. **It is not the ground-surface time**, and nothing here
assumes it is.

## Gate 1 — the association fails, and it fails first

To turn a surveyed target into an observation of `t_measured`, the reflector
belonging to *that* target must be locatable from published geometry. That needs
two things in one frame:

1. **the target's transverse offset** from a named site reference;
2. **the profile's along-line origin** in that same reference.

Neither is published, for any target or any profile:

- The transversal sections print **scale-bar segment lengths** (silt and
  limestone `[0.5, 0.5, 0.7, 0.7, 0.7, 1.0, 1.0, 1.0]`, both gneiss regions
  `[2.0, 1.25, 1.25, 2.0]`) and nothing ties a bar's origin to the longitudinal
  axis by a printed number.
- No source states where a profile's first trace sits. **45 of 67** files carry
  a trace *spacing*, which fixes the axis's scale and not its zero.

So 36 of 36 targets are `UNRESOLVED`, each recording what it lacks.

**This is the whole point of stopping here.** With no published association, the
only remaining way to choose a reflector is to try candidates and keep whichever
reproduces the surveyed depth — which is constraint 9 exactly. A model built
that way would predict the depths perfectly and mean nothing.

### The instrument headers do not rescue it

| | |
|---|---|
| Files with a usable header time-zero | **1 of 67** |
| Files with an along-track scale | 45 of 67 |

GSSI's `rhf_position` reads **93.7–100.1 ns on 22 profiles whose recording
windows are 60–85 ns**. A delay longer than the window is not a delay; the
converter already refuses to apply it. Another 17 GSSI files hold `0.0`, the
vendor's "not set". MALÅ's `.rad` sidecar has no time-zero field at all, and the
paper states IDS's transmitter–receiver separation is confidential.

The single plausible value — 4.5 ns on `400MHz_Gneiss14-20_2_rev.dzt` — is one
operator setting on one profile, unverified against anything. One number is not
a calibration.

## Gate 2 — even with perfect picks, t0 and v are confounded

This is a property of the published depths alone, so it is computed regardless
of gate 1. For `t = t0 + (2/v)·d` the least-squares parameter covariance depends
only on the depth set. The number that matters is the correlation between the
intercept and slope estimates: at −1 they are indistinguishable.

| Grouping | n | span (m) | corr(t0, slope) | σ(t0) per 1 ns noise | σ(v)/v per 1 ns noise | |
|---|---|---|---|---|---|---|
| silt | 3 | 1.03 | **−0.949** | 1.83 ns | 3.40% | confounded |
| limestone | 3 | 1.20 | **−0.963** | 2.15 ns | 2.93% | confounded |
| gneiss 14/20 | 3 | 1.20 | **−0.951** | 1.86 ns | 2.95% | confounded |
| gneiss 0/20 | 3 | 1.05 | **−0.967** | 2.26 ns | 3.34% | confounded |
| all pipe layers pooled | 12 | 1.60 | **−0.952** | 0.95 ns | 1.46% | confounded |
| multilayer interfaces *(derived)* | 5 | 3.10 | −0.892 | 0.99 ns | 0.97% | marginal |

**Why.** Leverage on `t0` comes from reflectors near `d = 0`. TU1208's shallowest
surveyed target is **0.80 m**; every one of the 36 sits at 0.80 m or deeper. With
no reflector anchoring the intercept, a shift in t0 is almost exactly absorbed by
a change in velocity.

**Pooling does not help.** Twelve targets instead of three halve the standard
errors (1.83 → 0.95 ns) and leave the correlation where it was (−0.949 →
−0.952), because confounding is a *shape* property of the depth set, not a count.
Collecting more targets at the same depths would buy precision on a pair of
parameters that still cannot be told apart.

**The one marginal grouping is not usable.** The multilayer interfaces span
3.10 m and still only reach −0.892 — and those depths are **derived** by
cumulative sum, not surveyed, and they cross **five different materials**, so a
single velocity is wrong there by construction. The paper says as much: *"The
multilayer section remains a challenge for GPR specialists, to estimate the real
thicknesses and permittivity values of the various layers."*

## The ten questions

**1. Can TU1208 independently constrain time-zero?**
**No.** No usable header value, no surveyed reflector near zero depth, and no
association to produce an arrival time.

**2. Can TU1208 independently constrain propagation velocity?**
**Not from measurement.** The paper's FDTD-matched permittivities (silt 13,
limestone 6, gneiss 14/20 3, gneiss 0/20 5.5) are *modelled* and caveated by
their own authors. They are carried as a cross-check for a future fit and are
**not converted to velocities here**.

**3. Can the two be separated?**
**No.** 94–97% confounded on every surveyed grouping.

**4. What is the held-out physical-depth error?**
**Undefined.** Zero observations. Reporting 0.0 m would read as a perfect
prediction.

**5. Does one velocity work across materials?**
**Untested, and expected not to.** The authors' own permittivities span 3 to 13
— roughly a factor of two in velocity across the site. That is the reason this
dataset was chosen, and it remains unexercised.

**6. Strong enough for a dataset-specific declaration?**
**No.** There is nothing to declare. No `SpatialDeclaration` was written.

**7. What does this unlock in Stage 8–12?**
Nothing is unlocked, and one thing is **learned**: the existing architecture
already models the missing pieces correctly. `DepthOriginOffset` is the right
home for a t0 that is not the ground surface; the depth-conversion declaration is
the right home for a velocity; the assessment already refuses to call a derived
depth measured. **The gap is not architectural — it is evidential.** The one
concept the architecture lacks is a *depth-calibration observation set*: a
recorded (target, arrival time, association basis) triple that a declaration
could cite. This experiment's artifact is the shape such a record would take,
with zero rows in it.

**8. What remains blocked for 4TU?**
Everything that was blocked before, verified against live state after the run:

| | |
|---|---|
| time-zero | **unresolved** — `axis.origin_offset` is `None` |
| propagation velocity | **unresolved** — still the converter's uncalibrated 0.1 m/ns, labelled `derived` |
| physical reflector depth | **unresolved** |
| absolute subsurface elevation | **unresolved** |
| vertical_reference | `unresolved`, 2 missing items — unchanged from Stage 21 |

**No TU1208 parameter was copied into 4TU, because none exists.** The firewall
holds by construction rather than by discipline.

**9. Did any platform state change?**
**No.** No declaration, readiness state, converter, dataset record, schema,
threshold or candidate semantic. One new script, one artifact, one test file,
this document.

**10. Next highest-value dependency.**
In order:

1. ~~**A reflector at or near zero depth.** This is the binding constraint on
   identifiability, and it is cheap in a controlled acquisition: a target at
   0.1–0.2 m alongside deeper ones collapses the t0/v correlation. No amount of
   deep targets substitutes.~~
   **CORRECTED BY STAGE 25 — see [`stage25-shallow-time-zero-audit.md`](stage25-shallow-time-zero-audit.md).**
   A shallow *target* does not collapse the correlation: the confounding is
   scale-invariant, depending on the depth set's coefficient of variation and
   not on depth. BAM already holds a target at 94 mm and is confounded at
   −0.939, no better than TU1208's 1.8 m targets. What is actually needed is a
   **directly measured system delay** — an observation at d = 0, which
   constrains t0 without passing through v. Read naively, the struck-out wording
   above would have produced a cluster of shallow reflectors, which is the
   *worst* of the designs tested (−0.965).
2. **A published or measured along-line origin**, which is what gate 1 needs.
   For TU1208 that means author contact; for a new acquisition it is free.
3. **A CMP gather**, which measures velocity independently of t0 and breaks the
   coupling outright rather than mitigating it.

TU1208 remains the best *geometry* Subterra holds. What it cannot supply is the
association between that geometry and a trace.

## What was deliberately not done

No arrival time was picked — checked against the module's executable source,
docstrings stripped, for `argmax`, `find_peaks`, `hilbert`, `correlate` and any
numeric signal library. No velocity or t0 was fitted. No permittivity was
converted to a velocity. No synthetic radargram or target was created. No
declaration was written. The module cannot import `api.spatial`,
`apply_declaration`, `DeclarationKind`, `save_frames` or `save_records`, and a
test enforces each.

**A blocked result is the finding.** The stage set out to discover whether the
evidence permits a number, and the answer — with the reason quantified — is that
it does not.
