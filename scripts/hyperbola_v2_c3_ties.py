"""
C3 follow-up (docs/hyperbola-v2-experiment.md §11): for every cell where the fast
stack picks a different v_hat from the original on the 20 C3 lines, the original
raw coherence at both velocities, to show whether the two are exact float ties.
Post hoc; run after `hyperbola_v2_runner equivalence`, adds to equivalence.json.
"""
import json, numpy as np
from simulation.hyperbola_v2_runner import *
from benchmark.hyperbola_stack import hyperbola_stack
from benchmark.hyperbola_stack_fast import hyperbola_stack_fast
import inspect, textwrap, benchmark.hyperbola_stack as hs

# The original's per-velocity raw coherence c (before the line-wide median/MAD
# normalisation), from its own source: the loop body with the argmax replaced by
# returning c for the one velocity. Comparing z from single-velocity runs is
# wrong, because the normalisation then changes.
_src = textwrap.dedent(inspect.getsource(hs.hyperbola_stack))
_src = _src.replace("def hyperbola_stack(", "def raw_c(", 1)
_src = _src.replace("        ok = (count >= MIN_TRACES) & after_t0", "        return c", 1)
_ns = dict(vars(hs)); exec(_src, _ns); raw_c = _ns["raw_c"]
eq = json.load(open(OUT / "equivalence.json"))
sel = {sid: (k, sid, m) for k, sid, m in scenes({"s0": {"train", "val", "test"}})[:20]}
out = []
for r in eq["rows"]:
    if not r["v_hat_mismatches"]:
        continue
    key, sid, meta = sel[r["sid"]]
    line = condition_line(load_line(CORPORA[key] / sid), PRIMARY_CONDITION)
    f = float(meta["centre_frequency_hz"]); tz = estimate_time_zero(line.traces, line.dt_s, line.time_offset_s)
    bg = BACKGROUNDS[PRIMARY_ARM](line)
    a = (bg, line.midpoint_x_m, line.dt_s, line.time_offset_s, tz, f)
    z0, v0 = hyperbola_stack(*a, **STACK_CFG); z1, v1 = hyperbola_stack_fast(*a, **STACK_CFG)
    m = (z0 > 1) & np.isfinite(z0) & (v0 != v1)
    for s, t in zip(*np.nonzero(m)):
        za = raw_c(*a, velocities=[float(v0[s, t])], **STACK_CFG)[s, t]
        zb = raw_c(*a, velocities=[float(v1[s, t])], **STACK_CFG)[s, t]
        out.append({"sid": sid, "z": float(z0[s, t]), "v_orig": float(v0[s, t]), "v_fast": float(v1[s, t]),
                    "c_at_v_orig": float(za), "c_at_v_fast": float(zb), "rel_gap": float(abs(za - zb) / abs(za))})
print(json.dumps({"mismatches": len(out), "max_rel_gap": max(o["rel_gap"] for o in out)}, indent=1))
eq["v_hat_mismatch_tie_check"] = {"method": "raw coherence c of the original (pre-normalisation) at each of the two velocities; relative gap",
                                  "max_rel_gap": max(o["rel_gap"] for o in out), "cells": out}
(OUT / "equivalence.json").write_text(json.dumps(eq, indent=1))
