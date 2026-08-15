# Shallow-reflector and time-zero audit: **nothing held anchors t0**

Eleven candidate anchors examined across every holding. **None constrains t0.
None constrains velocity.**

And a correction that matters more than the inventory:

> **Stage 24's recommendation — "a reflector at 0.1–0.2 m" — was wrong.**
> The t0/velocity confounding is **scale-invariant**. It depends on the
> *relative spread* of the depth set, not on depth. BAM already holds a target
> at 94 mm and is exactly as confounded as TU1208's 1.8 m targets.

Reproduce: `python -m scripts.stage25_shallow_anchor_audit --out artifacts/tu1208/shallow_anchor_audit.json`

## 1. The law, and why "go shallower" fails

For `t = t0 + (2/v)·d`, the correlation between the fitted intercept and slope is

```
corr(t0, slope) = -mean(2d)/sqrt(mean(4d²)) = -1 / sqrt(1 + CV²)
```

where CV is the coefficient of variation of the depth set. Verified against a
direct OLS covariance and against scaling — multiply every depth by 10 or 100
and the correlation does not move to 12 decimal places.

| Depth set | shallowest | deepest | CV | corr(t0, slope) |
|---|---|---|---|---|
| TU1208 silt | 0.80 m | 1.83 m | 0.332 | −0.949 |
| TU1208 limestone | 1.20 m | 2.40 m | 0.279 | −0.963 |
| TU1208 gneiss 14/20 | 0.90 m | 2.10 m | 0.327 | −0.951 |
| TU1208 gneiss 0/20 | 1.15 m | 2.20 m | 0.264 | −0.967 |
| **BAM Pk266 ducts** | **0.094 m** | 0.275 m | 0.367 | **−0.939** |
| BAM Pk266 step walls | 0.210 m | 0.570 m | 0.344 | −0.946 |

BAM's ducts are **an order of magnitude shallower** than TU1208's targets and
buy 0.01 of correlation. That is the refutation, in held data rather than in
argument.

**Two structural facts follow.** For strictly positive depths `mean(2d) > 0`, so
the correlation is **always negative** — t0 and velocity are never independent
under this model. And a two-level design cannot beat **−1/√2 ≈ −0.707** however
shallow its shallow point is, even at exactly zero.

## 2. Candidate acquisition designs, ranked

| Design | depths | CV | corr | σ(t0) per 1 ns pick noise | |
|---|---|---|---|---|---|
| **C+ — repeated measured system delay + two targets** | 0, 0, 0, 1.0, 2.0 | 1.333 | **−0.600** | **0.559 ns** | **best** |
| C — measured system delay + one deep target | 0, 2.0 | 1.000 | −0.707 | 1.000 ns | strong |
| A — shallow + deep known reflector | 0.15, 2.0 | 0.860 | −0.758 | 1.084 ns | good |
| E — shallow surveyed target + three deep | 0.15, 1.0, 1.5, 2.0 | 0.588 | −0.862 | 0.987 ns | moderate |
| **B — multiple shallow reflectors** | 0.10, 0.15, 0.20 | 0.272 | **−0.965** | 2.198 ns | **worst** |

**Design B is worse than the real TU1208 targets.** It is also precisely what
Stage 24's wording would have produced if acted on. Clustering reflectors near
the surface is as degenerate as clustering them deep.

**What actually breaks the degeneracy is an observation at d = 0** — a directly
measured system delay — because it constrains t0 without passing through v.
Everything else only eases the coupling. Ranked against the stage's criteria:

| | scientific strength | cost | fits architecture | solves t0 | solves v |
|---|---|---|---|---|---|
| **C/D — measured or manufacturer system delay** | highest | low (a metal plate at a measured standoff, or a vendor figure) | `DepthOriginOffset` already models it | **yes, directly** | no |
| **CMP gather** *(not in the stage's list; the standard method)* | highest | moderate — needs separable antennas | depth-conversion declaration | via v | **yes, directly** |
| A/E — shallow + deep surveyed targets | moderate | high (excavation and survey) | existing target-truth pattern | partially | partially |
| B — multiple shallow reflectors | **negative** | high | — | no | no |

C and CMP are complementary: one fixes t0 directly, the other fixes v directly.
Either removes a parameter from the fit rather than conditioning it better.

## 3. The evidence inventory

| Dataset | Feature | Verdict | Why |
|---|---|---|---|
| 4TU | `DelayRecordingTime`, all 751 files | **RULED OUT** | see §4 |
| 4TU | author statement on time zero / air gap | constrains interpretation only | makes the offset's *existence* certain, supplies no magnitude |
| 4TU | permittivity 8.16–19.46 | not a measurement | provider-declared, no method; constrains t0 not at all |
| TU1208 | 10-cm limestone surface layer + asphalt | **RULED OUT** | the only shallow documented interface — but it sits under an asphalt course of unpublished thickness, so `d` is unknown, and a 10 cm layer is below resolution at these frequencies |
| TU1208 | 36 surveyed pipe targets | **RULED OUT** | Stage 24: no association; separately confounded |
| TU1208 + hillside | MALÅ `SIGNAL POSITION`, `SYSTEM CALIBRATION` | **UNRESOLVED** | see §5 |
| BAM | `rhf_position` = 0.0 | **RULED OUT** | vendor's "not set", not a measured zero |
| BAM | 4 ducts, 94.4–274.5 mm, published X | **association available, identifiability still fails** | see §6 |
| BAM | step back walls | **RULED OUT** | step X ranges unpublished, and the thickness list carries no stated X ordering |
| hillside | 24 surveyed corner elevations | wrong quantity | says where the ground is in *space*, not in *time* |
| all | metal plate / CMP / reference trace | **ABSENT** | no such file exists in any holding |

## 4. `DelayRecordingTime` is formally ruled out

SEG-Y rev 1 defines it as *the time between source initiation and the start of
sample recording* — a **recording-start offset**, not a propagation path. Two
independent measurements confirm it is not the air gap:

- Read as an air path, its full range across 751 files implies antenna heights
  of **0.00 to 2.00 m**. The author states the antenna sits "a few centimetres"
  above the surface — about **0.33 ns** two-way.
- **9 of 751 files carry exactly 0**, which for an air-launched antenna would
  mean no air path *and* no internal delay.

It is also **unit-ambiguous**. The scalar-to-times field (bytes 215–216) is
**−1000 on every file**, which per the standard means *divide by 1000 to get
milliseconds* — making these delays physically absurd. The nanosecond reading
rests on the same vendor pre-scaling inference the sample interval already
needs. Measured range: raw 0–13307 across three sample-interval groups
(97 ps ×666, 117 ps ×2, 195 ps ×83), constant within each file.

**Ruled out as t0.** It remains a known additive component of the instrument's
time origin; it is not a ground-surface reference.

## 5. The MALÅ fields: checked against the vendor spec, and unresolved

`SIGNAL POSITION`, `RAW SIGNAL POSITION` and `SYSTEM CALIBRATION` appear in all
328 MALÅ `.rad` files held and are the most promising lead in the corpus. They do
not survive checking:

- MALÅ's own published format specification — Guideline Geo, *Appendix 1 –
  Detailed description of RD3, RD7 and RAD formats* — enumerates the `.rad`
  parameters and **does not list any of the three**. The phrase "time zero"
  appears nowhere in it.
- The values are mutually incoherent: hillside carries `SIGNAL POSITION`
  **1053.5 against a 66.3 ns window**, which cannot be a time in ns; TU1208
  carries −0.033 to −0.381.

**UNRESOLVED, not ruled out** — a vendor answer could still make them usable,
and that is a cheap question to ask.

## 6. BAM: the one genuine architectural asset

BAM's ducts are the only place in the holdings where **association is
published**: target X is given numerically (250/750/1250/1750 mm) and the scanner
grid is expressed in the same millimetre specimen frame, so which traces sit over
which duct requires no inference. That is exactly what TU1208 lacks.

It still does not anchor t0 — corr −0.939. But it means **BAM, not TU1208, is
the dataset on which the calibration machinery could be exercised end to end**
once a t0 constraint exists, because gate 1 is already passed there.

## 7. Stage 8–12 status

| Dimension | 4TU | TU1208 | Why |
|---|---|---|---|
| CRS | **PARTIAL** | **BLOCKED** | 4TU: geographic positions decoded, EPSG undeclared. TU1208: local site grid, no CRS |
| Horizontal datum | **PARTIAL** | **BLOCKED** | as above |
| Vertical datum | **UNBLOCKED** *(acquisition elevation only)* | **BLOCKED** | Stage 21: WGS84 ellipsoidal, author-attributed, `verified=False`. Scoped to the stored elevation — **not** the depth axis |
| Surface elevation | **PARTIAL** | **BLOCKED** | 4TU: per-trace GNSS + AHN over project 01. TU1208: none published |
| Depth-axis origin | **BLOCKED** | **BLOCKED** | no t0 evidence anywhere; §4 rules out the only candidate 4TU had |
| Propagation velocity | **BLOCKED** | **BLOCKED** | 4TU has a declared permittivity, not a measurement; TU1208 has modelled permittivities, caveated by their authors |
| Physical depth | **BLOCKED** | **BLOCKED** | needs both of the above |
| Subsurface absolute elevation | **BLOCKED** | **BLOCKED** | needs physical depth *and* surface elevation *and* a datum |
| Spatial registration | **PARTIAL** | **BLOCKED** | 4TU registers horizontally; TU1208 has no along-line origin |

**No dimension was upgraded because another became known.** The 4TU
acquisition-elevation datum is established and its depth chain is untouched — a
datum for a stored elevation is not a datum for the depth axis, which the
architecture enforces in code.

## 8. The twelve questions

1. **Independent shallow reflector anywhere?** No. The only shallow documented
   interface (TU1208's 10 cm limestone) has an unknown depth and is below
   resolution.
2. **Independent time-zero / system-delay measurement anywhere?** No. Zero of
   11 candidates. No CMP, no metal plate, no reference trace exists in any holding.
3. **Can TU1208 solve t0?** No — association fails, and identifiability fails
   independently.
4. **Can BAM solve t0?** No. Its association is sound; its depth set is
   confounded at −0.939.
5. **Can 4TU solve t0?** No. Its only header candidate is ruled out in §4.
6. **Is `DelayRecordingTime` usable as t0?** **No** — recording-start metadata,
   physically contradicted by the implied antenna heights and by nine zeros,
   and unit-ambiguous.
7. **Any cross-dataset evidence validating the architecture?** Partially, and
   worth stating precisely: **BAM validates that published association is
   achievable** — the hardest thing TU1208 lacks. It does not validate the
   time→depth calibration, because no dataset can yet supply t0. No parameter
   was transferred anywhere; none exists to transfer.
8. **Minimum real-world evidence to solve t0 + velocity?** A **directly measured
   system delay** (design C — a metal plate at a measured standoff, or a
   manufacturer figure) **plus one independently associated reflector at any
   depth**. Adding a CMP gather makes both parameters independently measured
   rather than jointly fitted. Note what is *not* required: shallow targets.
9. **Can Stage 8–12 progress without another author response?** For 4TU's
   **horizontal** chain, yes — a declared EPSG would move CRS and horizontal
   datum, and needs no author. For the **depth** chain, no: it needs a
   measurement nobody has made, and no correspondence can substitute.
10. **Which blocker next?** The depth-axis origin, attacked by measuring a
    system delay rather than by acquiring more targets.
11. **Solvable by a different existing dataset instead of modifying 4TU?**
    Not from anything held — this audit is that search, and it returned nothing.
    Two cheap external routes remain: ask MALÅ what `SIGNAL POSITION` means
    (§5), and ask GSSI for the 1.5/2.6 GHz antenna's internal delay, which would
    give BAM a design-C anchor on a dataset whose association is already solved.
12. **Scientifically impossible from current holdings?** Any physical depth, any
    subsurface absolute elevation, and any statement about a reflector's true
    position on or below either dataset. Not merely unmeasured — **not
    identifiable** from what is held, and no amount of reprocessing changes it.

## 9. Integrity

No synthetic signal, target, geometry or coordinate. No guessed t0 or velocity.
No parameter transferred between datasets. No declaration written, no dataset
record modified, no readiness altered. Candidate designs are **depth sets fed to
closed-form algebra** — parameter arithmetic, explicitly permitted, and the tests
check the module for numeric-array and randomness idioms to keep it that way.
