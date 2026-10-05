# GPR regression baseline: is byte-exact output the contract?

**Date:** 2026-10-05 · **Status:** proposal **implemented** (second commit below); the investigation is kept for the record.

## What fails

Four assertions fail, the processed grid and the anomaly z-grid digests for INGV SEG-Y lines `C1T_7,5_0001` and `_0002`. They compare `sha256(float64 bytes)` of each grid against digests captured on 2026-08-06.

## What was established

| Check | Result |
|---|---|
| Fails at the commit that introduced the test (`084f61d`)? | **Yes**, the same 4 failures, so this is not a code change since then |
| Related to the IDS signed-int16 fix? | **No**: the data are SEG-Y, and the fix touches only `.dt` decoding |
| Deterministic in the current environment? | **Yes**: identical digests on repeated runs |
| Raw grid, record fields, metadata, axes | **pass**, byte-exact |
| z-grid std / max abs (6 dp) | **identical**: 0.904066 / 4.273256 and 0.845445 / 4.361468 |
| Cells with abs(z) ≥ 3 | **identical**: 121 and 73 |
| Candidate counts, trace ranges, depth ranges, peak-value digests | **pass**, byte-exact |
| Environment | numpy 2.1.1 / scipy 1.14.1 (pinned, unchanged), reinstalled 2026-09-29 on a newer macOS, BLAS/LAPACK = Apple Accelerate |

**Conclusion:** the processed and z grids differ from the captured baseline only below the precision that any downstream quantity resolves. That is last-bit floating-point variation from the rebuilt numeric stack, not a behavioural change.

## Is byte-exactness the intended contract?

The test docstring states its purpose: prove the M1 ingestion refactor "changed nothing numerically or behaviourally", with "no tolerances". That is a sound **same-machine refactor guard**. Exact float digests cannot also be a **cross-environment** contract: summation order, SIMD paths and BLAS builds legitimately change the last bits. The scientific contract that matters is numerical equivalence of the processed signal plus exact equality of discrete outputs (candidates, counts, ranges). Those still hold.

## Original proposal (now implemented, see below)

1. Keep the **exact** assertions for discrete and integer outputs, raw decoded samples and record fields. These are environment-independent and still pass.
2. For float grids, store the reference arrays (`.npz`, about 0.5 MB per line) captured from the pre-M1 tree. Compare with `np.testing.assert_allclose(rtol=1e-12, atol=1e-9 * max|ref|)` and report the worst element.
3. Record an **environment fingerprint** (numpy/scipy versions, BLAS vendor, platform) next to the digests. Run the exact digest check only when the fingerprint matches; otherwise run the tolerance check and print which mode ran.
4. Never regenerate the references from current code to make a test pass. A reference changes only through a reviewed commit that states why.

It was implemented as its own commit, separate from the BAM gate commits.

## Implemented (2026-10-05)

- **Pre-M1 code and HEAD are byte-identical** in the current environment: all four grid digests match between `4b9ff0e` and HEAD. Changing `VECLIB_MAXIMUM_THREADS` or disabling numpy's dispatched SIMD features does not change a bit. The August digests therefore came from a numeric stack that can no longer be reproduced.
- **Measured sensitivity:** perturbing every raw sample by about 1 ULP (3 trials per line) moves the processed grid by at most **2.0e-15 of its scale** and the z-grid by at most **7.5e-14 absolute**. The finite mask and candidate counts are unchanged.
- **Reference arrays** from `4b9ff0e` are in `tests/fixtures/regression/c1t_reference_grids.npz`, with the capture environment fingerprint and sha256 in the `.json`.
- **The test now asserts:**
  - shape, dtype and finite mask exactly;
  - finite values within **1e-12 × max|ref|** (processed) and **1e-11 absolute** (z), about 500× the measured ULP sensitivity;
  - z std / max abs / cells ≥ 3 exactly to 6 dp, and candidate counts, ranges and peaks exactly (unchanged tests);
  - byte identity whenever the environment fingerprint equals the capture fingerprint.
- **Self-test:** a 1e-9 relative drift, or a single changed NaN cell, fails; identity passes.
- The August digests are kept in the file, labelled historical, and no longer asserted.
