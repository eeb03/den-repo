"""
Detector validation: controlled synthetic targets, null models, and
false-alarm analysis for the GPR anomaly pipeline.

This package MEASURES the detector. It never modifies it. Nothing here is
imported by preprocessing, interpretation, or any ingest path -- the
dependency arrow points one way, so a validation experiment cannot
accidentally change a scientific result.

Why it exists: the platform's key detector findings previously lived only
in commit messages and prose. A scientific claim that cannot be re-run is
not reproducible, and "the detector is insensitive to targets wider than
its ring exclusion" is exactly the kind of claim that must survive future
refactors as an executable test rather than a remembered fact.

SCIENTIFIC FRAMING (do not weaken when extending):
- Synthetic results are ALGORITHM validation, never field validation. A
  target this module injects is a known input to a known filter; it says
  nothing about what is in the ground.
- A null model establishes what the detector produces from data with the
  structure of interest destroyed. Exceeding a null is evidence that
  structure exists, NOT evidence of a physical object.
- No function here returns, produces, or implies ground truth.
"""
