# Roadmap and status

The authoritative status of each work area, with the evidence for the claim.
Recorded here because two other documents note that the roadmap "is not
recorded anywhere in this repository", which made every phase claim
unauditable.

Scope note: this is the **work-area** roadmap. The separate *Phase 0–12*
numbering referenced by `dataset-benchmark-plan.md` and
`benchmark-acquisition-plan.md` is still not committed anywhere, so the phase
numbers in those documents remain inferred, exactly as they say.

Last verified against `0daa3e7` on 2026-08-08.

| Area | Status | Evidence |
|---|---|---|
| Core backend / data platform | ✅ Complete | 1,116 tests pass in Docker; 1,167 files and 749,315 traces ingest across four formats and three vendors |
| Open GPR dataset investigation | ✅ Complete | `dataset-inventory.md`, `dataset-benchmark-plan.md`, `cmugpr-acquisition-assessment.md` |
| BAM benchmark acquisition | ✅ Complete | `external-gpr-benchmark-acquisition.md`; acquired and checksum-verified |
| BAM detection benchmark | ✅ Complete | `artifacts/bam/*.json`, 161 lines scored at both frequencies |
| 4TU utility benchmark | ✅ Complete | `artifacts/4tu/benchmark.json`, complete **125**-activity corpus |
| Benchmark test infrastructure | ✅ Strong | GPR regression 26 pass bit-identical; baseline identity 12/12 |
| Ground-truth / provenance safeguards | ✅ Established | `provenance.md`; enforced in backend tests and in the UI |
| Localisation / X-Y-Z scoring | 🔒 **BLOCKED** | Both artifacts carry the gate; 4TU publishes no trench coordinates, BAM's absolute origin is unverified |
| Frontend architecture audit | ✅ Complete | `frontend/README.md` |
| V0 frontend migration | 🟡 In progress | workspace, datasets and benchmark pages ship; marketing landing page not ported |
| Real API → new frontend | 🟡 Substantially complete | 8 of 12 backend route groups have UI; `exports`, `fusion`, `sources`, `training` do not |
| Browser verification | ✅ Complete (first pass) | `browser-verification.md` — 11 routes, all 6 datasets, 0 page errors, 0 failed requests |
| Detection improvement | ⏳ Open — one candidate tried and **rejected** | `detector-multiscale-experiment.md` |
| Author / evidence requests | 🟡 Open | outstanding queries to dataset publishers |
| Production-ready platform | ⏳ Later | no auth, no encryption, no dataset signing |

## Where detection actually stands

The baseline detector is the scientific reference and remains unchanged in the
default path. It is at or below chance on both benchmarks:

- BAM: recall 0.065 (1.5 GHz) and 0.093 (2.6 GHz); precision 0.135 and 0.147
  against a 0.1297 chance rate — 1.04× and 1.13× chance.
- 4TU: AUC 0.4452, Spearman ρ −0.0619, both at or below chance.

One candidate has been tried. The multi-scale ring estimator was designed
against the *measured* width-saturation mechanism, demonstrated that it escapes
that collapse synthetically, and was **rejected**: its BAM gain is concentrated
entirely in duct-4 while ducts 1–3 fall to zero, and 4TU AUC did not improve
(0.4452 → 0.4216, bootstrap ΔAUC interval spanning zero). An earlier claim of
improved SNR and noise behaviour was **withdrawn** — it had been measured on
pure Gaussian noise, and on real radargrams the candidate fires 3.5×–17× more.

Two practices from that experiment are now load-bearing for any future one:

1. **Bit-identical baseline reproduction.** The baseline arm must reproduce the
   frozen artifacts to full precision through the new code path. This is what
   caught a traversal bug that had silently scored 123 of 125 activities and
   produced a plausible wrong answer (AUC 0.4429 vs a true 0.4452).
2. **Pre-registered calibration**, never tuned against benchmark truth.

## What blocks localisation

Not effort — evidence. 4TU publishes no trench coordinates, so no candidate can
be matched to a utility. BAM's absolute origin is unverified. No dataset held
has an established vertical relationship: the GPR time axis starts at
instrument time-zero, not the ground surface, and no source declares a vertical
datum. The backend states this itself when asked to resolve a 3D scene, which
is why `scene_3d` is unavailable for every dataset and why the workspace draws
no subsurface geometry.

Detection scoring does not depend on any of this and is unaffected. A blocked
localisation gate does not make the detection numbers invalid, and the
detection numbers do not make the gate any less blocked.
