"""
PVL-V1 L1 STOP diagnosis (descriptive, post hoc, after the frozen selection
returned no admissible configuration). Reports W by CCD-V1 Arm D class and the
tracks near each duct at the most permissive grid point. Selects nothing.

    python -m scripts.pvl_v1_l1_diagnosis > artifacts/pvl_v1/l1_stop_diagnosis.json
"""
import json, collections, numpy as np
from scripts.pvl_v1 import apply, OUT, L1_SCANS
from scripts.ccd_v1_stage1 import objects
cands={f"{s}_{c}": json.loads((OUT/f"candidates_{s}_{c}.json").read_text()) for s,c in L1_SCANS}
out={}
# W distribution by Arm D class
for k,cs in cands.items():
    by=collections.defaultdict(list)
    for c in cs: by[c.get("armd_class")].append(c["W"])
    out[k]={cl:{"n":len(w),"W_q25_50_75":[round(float(np.percentile(w,q)),2) for q in (25,50,75)]} for cl,w in by.items()}
cfg={"G":5,"dx":0.5,"dt":0.5,"L":2,"W":3}
tr=apply(cands,cfg)
diag={}
for k,rows in tr.items():
    diag[k]={"labels":dict(collections.Counter(r["label"] for r in rows))}
for o in objects("Pk266"):
    rows=[r for r in tr["Pk266_1_5_GHz_Rot00"] if abs(r["x_med"]-o["x"])<=100]
    obj_c=[c for c in cands["Pk266_1_5_GHz_Rot00"] if c.get("armd_object")==o["id"]]
    diag[o["id"]]={"n_object_candidates":len(obj_c),"object_cand_lines":len({c["line"] for c in obj_c}),
       "object_cand_W_median":round(float(np.median([c["W"] for c in obj_c])),2) if obj_c else None,
       "tracks_near":[{"label":r["label"],"n_lines":r["n_lines"],"L":round(r["L"],2),"W":round(r["W_med"],2),"s":r["s"] and round(r["s"],2),"t":round(r["t_med"],2)} for r in sorted(rows,key=lambda r:-r["n_lines"])[:4]]}
print(json.dumps({"W_by_class":out,"permissive":diag},indent=1))
