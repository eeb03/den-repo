# Test environment

**Run the suite in Docker.** Five tests fail on a macOS host for reasons that
have nothing to do with the code under test, and one of them is a
scientific regression gate. This document records why, so the failures are
not rediscovered and — more importantly — so nobody "fixes" them by
editing a baseline.

```bash
docker build -t subterra-test .
docker run --rm \
  -v "$PWD/datasets:/app/datasets:ro" \
  -v "$PWD/artifacts:/app/artifacts:ro" \
  -e DATABASE_URL="sqlite:////tmp/test.db" \
  subterra-test \
  sh -c "pip install -q pytest httpx && python -m pytest -q"
```

Both mounts are needed for a complete run: `datasets/` and `artifacts/` are
gitignored runtime data and are excluded from the image by `.dockerignore`.
Without `artifacts/`, seven 4TU tests skip with *"characterisation has not
been run"*.

## Results

| environment | result |
|---|---|
| Docker (`python:3.12-slim`, Linux aarch64, scipy-openblas 0.3.27) | **1055 passed, 0 failed** |
| macOS host venv (Python 3.11.9, Darwin arm64, Accelerate BLAS) | 1050 passed, **5 failed** |

The five host failures are environmental. They reproduce identically on the
pristine pre-frontend commit `733eb2f`, so they are not caused by anything
recent.

## The four GPR regression digest failures

```
tests/test_gpr_regression_baseline.py::test_processed_grid_unchanged[C1T_7,5_0001]
tests/test_gpr_regression_baseline.py::test_anomaly_zscore_grid_unchanged[C1T_7,5_0001]
tests/test_gpr_regression_baseline.py::test_processed_grid_unchanged[C1T_7,5_0002]
tests/test_gpr_regression_baseline.py::test_anomaly_zscore_grid_unchanged[C1T_7,5_0002]
```

**Cause: the BLAS backend, not the code.** numpy and scipy are at the pinned
versions (2.1.1 / 1.14.1) in *both* environments. What differs is what numpy
links against:

| | BLAS |
|---|---|
| Docker / Linux | `scipy-openblas 0.3.27` |
| macOS host | Apple `Accelerate` |

The gate hashes float64 bytes with **no tolerance** — deliberately, since
"no processing parameter changed in M1, so any difference at all is a
defect". That strictness makes it sensitive to last-bit floating-point
differences between BLAS implementations.

Two details confirm the diagnosis rather than merely fitting it:

- **Only the float-math stages fail.** `record_digest` and `raw_digest` —
  the parse-level digests — pass on the host. Only `processed_digest` and
  `z_digest`, which run through the preprocessing arithmetic, diverge.
- **The divergence is deterministic.** The same "actual" digest appears on
  every host run, so this is a platform difference, not nondeterminism.

**Do not re-record these baselines from a macOS run.** Doing so would swap a
value captured in the canonical environment for one that is an artefact of
Accelerate, and would silently move the regression gate.

## The MALA casing failure

```
tests/test_mala_converter.py::test_uppercase_rad_is_found
```

`find_rad()` tries `.rad`, `.RAD`, `.Rad` in order and returns the first that
`exists()`. macOS APFS is **case-insensitive by default**, so
`Path("x.rad").exists()` returns true for a file named `X.RAD`, and the
function returns the `.rad` spelling. The test asserts `.RAD`.

The production behaviour is fine either way — the file is found and opened.
Only the asserted suffix differs, and only on a case-insensitive filesystem.

Verified directly: a probe file written as `probe.RAD` under pytest's
`tmp_path` volume is reachable as `probe.rad`.

## Causality check

When a regression gate fails it is worth being certain about what caused it.
The three arms below were run with the same interpreter, environment and
test selection:

| arm | tree | result |
|---|---|---|
| A | pristine `733eb2f`, via `git worktree` | 5 failed, 58 passed |
| B | current tree, `frontend/` moved out | 5 failed, 58 passed |
| C | current tree, `frontend/` present | 5 failed, 58 passed |

Identical failures and identical actual-vs-expected digests in all three.
`pytest.ini` sets `testpaths = tests`, so `frontend/` is never collected.
