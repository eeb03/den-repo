# Controlled-survey ground truth: `subterra.survey_truth.v1`

**Readiness branch R1(a)**, for `docs/post-pr17-acquisition-strategy-brief.md` §1.6.
- Module: `benchmark/survey_truth.py`.
- Tests: `tests/test_survey_truth.py`.
- Synthetic example: `tests/fixtures/survey_truth_example.json`. It is invented geometry, not truth for anything.
- **No detector, no production detection change, no real data.**

## What it adds, and what it reuses

A survey-truth document **embeds a `subterra.targets.v1` manifest unchanged**. That manifest is loaded by the existing `benchmark.targets.load_manifest_dict`, so every existing rule still applies:
- no radar quantity in truth;
- no operator interpretation at grade A or B;
- named depth reference surfaces;
- `EvidenceBasis` and `EvidenceGrade` from the existing vocabularies.

The document adds four things the manifest cannot carry:

| Addition | Rule enforced at load (invalid if broken) | Eligibility rule (valid but not scorable if unmet; reported) |
|---|---|---|
| `objects[]`: one entry per target, with a declared `class_group` (`linear` or `compact`) | every target has exactly one entry; the group is **declared, never inferred** from the class name | — |
| `axis`: a surveyed polyline for each linear object | required for `linear`; ≥ 2 vertices; a planar frame; the end vertices agree with the target's own segment within the combined uncertainty | vertex spacing ≤ **1.0 m**; vertex uncertainty stated and ≤ **0.02 m** |
| `verified_empty_areas[]`: polygons | simple polygon with positive area; **evidence must be excavation or recorded placement, independent of the radar**; no target or axis may lie in it or cross it | excavated to ≥ **1.5 m**; grade A or B |
| `control_points[]` | unique ids; planar frame; method and source stated | ≥ **3** points with uncertainty ≤ **0.02 m** |
| `custody` | `sealed_utc`, `sealed_by` and a statement that the truth was recorded **before any radar file was processed** | — |

**Further eligibility rules:**
- Per object: independent grade A/B evidence, and position uncertainty stated and ≤ 0.02 m.
- The thresholds are `Requirements` (defaulting to the brief's values) and are always reported with the result. A protocol can tighten them; it cannot hide them.

**Custody digest:**
- `truth_digest(doc)` is the sha256 of a canonical JSON serialisation: key order and whitespace are irrelevant, content is not.
- `load_survey_truth(path, sealed_digest=...)` refuses any document whose digest differs from the sealed one.
- The digest is what a validation protocol records before data are opened (readiness branch R1(c)).

**Valid is not eligible.** `eligibility()` lists every object and area with its reasons. It **never drops one silently**, and it gives the totals per class group and the eligible verified-empty m² that the protocol's sample-size rules are applied to.

## What it does not do

- It does **not match predictions**. That is R1(b), metric-coordinate matching.
- It does **not read or produce radar data**. The module imports no detector or preprocessing code, and a test checks this.
- It **no transform between frames**. Geographic frames are refused for planar truth, as in `benchmark.targets`.
