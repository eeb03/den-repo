"""
Benchmark evaluation for Subterra.

Holds the BAM concrete GPR benchmark: the first dataset Subterra has with
TARGET ground truth -- the identity, geometry and position of things in a
medium, as opposed to where the instrument was.

Scope of this package, deliberately narrow:

    DETECTION scoring and FALSE-ALARM scoring only.

Localisation scoring is BLOCKED and enforced in code (`benchmark.gates`),
because the benchmark's absolute coordinate origin is corroborated but not
declared by any source. See `docs/external-gpr-benchmark-acquisition.md` §9.
"""
