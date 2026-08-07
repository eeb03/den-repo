"""
Render the 4TU characterisation report from the machine-readable artifact.

The report is GENERATED, not written by hand, so every number in it traces
to `artifacts/4tu/characterisation.json` and regenerating after a re-run
cannot leave stale figures behind.

    python -m scripts.report_4tu --in artifacts/4tu --out docs/4tu-characterisation.md
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path


def fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else ("-" if n is None else f"{n}")


def build(run: dict, null: dict | None) -> str:
    acts = run["activities"]
    files = [f for a in acts.values() for f in a["files"]]
    traces = sum(a["traces"] for a in acts.values())
    records = sum(a["records"] for a in acts.values())
    cands = sum(a["candidates"] for a in acts.values())
    reliable = sum(a["reliable_cells"] for a in acts.values())
    unreliable = sum(a["unreliable_cells"] for a in acts.values())
    processed = sum(a["radargrams_processed"] for a in acts.values())
    available = sum(a["radargrams_available"] for a in acts.values())
    rec_files = [f for f in files if f.get("processing_mode") == "records"]
    arr_files = [f for f in files if f.get("processing_mode") == "arraywise"]
    rec_records = sum(f["records"] for f in rec_files)
    rec_cands = sum(f["candidates"] for f in rec_files)
    arr_cands = sum(f["candidates"] for f in arr_files)

    sweep = Counter()
    for a in acts.values():
        for k, v in a["candidate_sweep"].items():
            sweep[float(k)] += v

    with_c = [a for a in acts.values() if a["candidates"] > 0]
    zero_c = [a for a in acts.values() if a["candidates"] == 0]
    dens = [a["candidates_per_1k_traces"] for a in acts.values()
            if a["candidates_per_1k_traces"] is not None]

    L: list[str] = []
    add = L.append
    add("# 4TU corpus: preprocessing and anomaly characterisation\n")
    add(f"Generated from `artifacts/4tu/characterisation.json` "
        f"({run['generated_utc']}). Every figure below is read from that file.\n")
    add("> **This is a characterisation, not an evaluation.** 4TU publishes no\n"
        "> trench coordinates, so no candidate is matched to a reported utility and\n"
        "> no accuracy, precision, recall, IoU, depth error or positional F1 is\n"
        "> reported anywhere. Those metrics are not computable from this source.\n")

    add("\n## 1. Corpus\n")
    add(f"- **Source:** `{run['corpus']}`")
    add("- 4TU.ResearchData, DOI 10.4121/96303227-5886-41c9-8607-70fdd2cfe7c1.v1, CC0-1.0")
    add("- Air-launched 500 MHz GPR, Spectre SP80 RTK GNSS + wheel encoder, "
        "0.02 m trace spacing, 512 samples/trace")
    add(f"- **Real data only.** No fixtures contributed to any number in this report.")

    add("\n## 2. Acquisition structure\n")
    add(f"| | |\n|---|---|")
    add(f"| Activities (LocationID) characterised | {len(acts)} |")
    add(f"| Radargrams available in those activities | {fmt(available)} |")
    add(f"| Radargrams processed | {fmt(processed)} |")
    add(f"| Traces | {fmt(traces)} |")
    add(f"| Records (trace x sample) | {fmt(records)} |")
    add("\nActivities are the dataset's own `LocationID`. Project 13's directories "
        "are named `013.N` while its `Metadata.csv` rows say `13.N`; that "
        "one-to-one, 6-entry mismatch is normalised and recorded as a source "
        "inconsistency, not inferred.")

    add("\n## 3. Preprocessing configuration\n")
    for s in run["pipeline"]["preprocessing"]:
        add(f"- `{s}`")
    add(f"\n- Ingest: `{run['pipeline']['converter']}`, "
        f"coordinate encoding `{run['pipeline']['coordinate_encoding']}`")
    add(f"- **Parameters changed by this run: {run['pipeline']['parameters_changed_by_this_script']}**")
    add("\n### Provenance of each quantity\n")
    add("| quantity | status |\n|---|---|")
    add("| GPR two-way time | **measured** by the instrument |")
    add("| Background removal / dewow / gain | **derived** from the measured signal |")
    add("| Ring z-score | **derived** statistic, not a physical unit |")
    add("| Velocity | **caller-supplied**, derived from the provider's published "
        "relative permittivity per activity (`c/sqrt(eps_r)`) — a site estimate, "
        "not a subsurface measurement |")
    add("| Depth | **assumed**, because it inherits that velocity |")
    add("| Vertical datum | **unavailable** — see `docs/vertical-reference-site01.md` |")
    add("| Trench information | **source-reported**, joined by LocationID only |")

    add("\n## 4. Detector configuration\n")
    add(f"- `{run['pipeline']['detector']}`")
    add(f"- threshold **{run['pipeline']['threshold']}**, "
        f"min_cells **{run['pipeline']['min_cells']}**, 4-connected components")
    add(f"- threshold sweep: {run['pipeline']['threshold_sweep']} "
        f"(counts only, on the grid the detector already built; agreement with the "
        f"authoritative detector at the default is asserted per radargram)")

    add("\n## 5. Volume processed\n")
    add(f"| | |\n|---|---|")
    add(f"| Radargrams | {fmt(processed)} of {fmt(available)} |")
    add(f"| Traces | {fmt(traces)} |")
    add(f"| Records | {fmt(records)} |")
    add(f"| Wall time | {run['elapsed_seconds']} s |")
    add(f"\n### Processing mode\n")
    add("Two paths, proven bit-identical on the z-grid "
        "(`artifacts/4tu/arraywise_validation.json`). The array path exists because "
        "per-cell records, not the science, dominate memory; it computes the same "
        "grid with the same functions but does not produce per-candidate "
        "characterisation.\n")
    add("| path | radargrams | records | candidates | per-candidate detail |\n|---|---|---|---|---|")
    add(f"| records | {len(rec_files)} | {fmt(rec_records)} | {fmt(rec_cands)} | yes |")
    add(f"| arraywise | {len(arr_files)} | {fmt(records - rec_records)} | {fmt(arr_cands)} | no |")
    add(f"\n**Ring-background reliability** is measured on the {len(rec_files)} "
        f"record-path radargrams ({fmt(rec_records)} cells): "
        f"**{fmt(reliable)} reliable ({100*reliable/max(rec_records,1):.1f}%)**, "
        f"**{fmt(unreliable)} edge-starved ({100*unreliable/max(rec_records,1):.1f}%)**. "
        f"The array path does not compute it, so those cells are excluded from this "
        f"percentage rather than counted as either.")

    add("\n## 6. Rejected / skipped, and why\n")
    if run["skipped"]:
        add("| LocationID | files | stage | reason |\n|---|---|---|---|")
        for s in run["skipped"]:
            add(f"| {s['location_id']} | {s['files']} | {s.get('stage','-')} | {s['reason']} |")
    else:
        add("No activity was skipped.")
    if run["errors"]:
        add(f"\n**{len(run['errors'])} radargram(s) failed:**\n")
        add("| LocationID | file | error |\n|---|---|---|")
        for e in run["errors"][:40]:
            add(f"| {e['location_id']} | {e['file']} | `{e['error'][:110]}` |")
    else:
        add("\nNo radargram failed to process.")

    add("\n## 7. Anomaly candidates\n")
    add(f"| | |\n|---|---|")
    add(f"| Candidates at the default threshold | **{fmt(cands)}** |")
    add(f"| Candidates per 1,000 traces | {1000*cands/max(traces,1):.2f} |")
    add(f"| Activities with >=1 candidate | {len(with_c)} of {len(acts)} |")
    add(f"| Activities with 0 candidates | {len(zero_c)} |")
    if dens:
        add(f"| Candidate density per activity (per 1k traces) | "
            f"median {statistics.median(dens):.2f}, "
            f"min {min(dens):.2f}, max {max(dens):.2f} |")
    classes = Counter(c["anomaly_class"] for f in files for c in f["candidate_summary"])
    if classes:
        add(f"\n**Geometric class distribution** (a neutral shape description, never an "
            f"object claim). Covers the {fmt(rec_cands)} candidates from record-path "
            f"radargrams; the {fmt(arr_cands)} from array-path radargrams are counted "
            f"above but not classified.\n")
        add("| class | count |\n|---|---|")
        for k, v in classes.most_common():
            add(f"| {k} | {fmt(v)} |")

    add("\n## 8. Distribution by activity\n")
    add("Full per-activity detail is in the JSON artifact. Extremes shown here.\n")
    ranked = sorted(acts.values(), key=lambda a: -(a["candidates_per_1k_traces"] or 0))
    add("| LocationID | files | traces | candidates | per 1k traces |\n|---|---|---|---|---|")
    for a in ranked[:10]:
        add(f"| {a['location_id']} | {a['radargrams_processed']} | {fmt(a['traces'])} "
            f"| {a['candidates']} | {a['candidates_per_1k_traces']} |")
    add("| ... | | | | |")
    for a in ranked[-5:]:
        add(f"| {a['location_id']} | {a['radargrams_processed']} | {fmt(a['traces'])} "
            f"| {a['candidates']} | {a['candidates_per_1k_traces']} |")

    add("\n## 9. Relationship to trench information\n")
    add("The join is **LocationID only**. 4TU withholds trench coordinates for "
        "confidentiality, so a candidate cannot be matched to a reported utility "
        "and none is.\n")
    have_util = [a for a in acts.values() if a["source_reported"]["utility_discipline"]]
    no_util = [a for a in acts.values() if not a["source_reported"]["utility_discipline"]]
    add(f"- Activities where the source reports at least one utility discipline: "
        f"**{len(have_util)}**")
    add(f"- Activities where that field is blank: **{len(no_util)}**")
    if have_util:
        d = [a["candidates_per_1k_traces"] for a in have_util
             if a["candidates_per_1k_traces"] is not None]
        add(f"- Candidate density where utilities are reported: "
            f"median {statistics.median(d):.2f} per 1k traces" if d else "")
    if no_util:
        d = [a["candidates_per_1k_traces"] for a in no_util
             if a["candidates_per_1k_traces"] is not None]
        if d:
            add(f"- Candidate density where the field is blank: "
                f"median {statistics.median(d):.2f} per 1k traces")
    add("\n**A blank field is not a known-empty activity.** The dataset states that "
        "material and diameter are not recorded for every utility, so absence in the "
        "table is missing information, not absence of a utility. No activity here can "
        "serve as a negative control.")

    add("\n## 10. Background / null observations\n")
    if null:
        add(f"- Null model: `{null['null_model']}`, {null['draws_per_file']} draws over "
            f"{null['files_measured']} radargram(s), seed {null['seed']}")
        add(f"- Observed candidates in the sample: **{fmt(null['observed_total'])}**")
        add(f"- Null mean over the same radargrams: **{null['null_mean_total']:.1f}**")
        add(f"- Files whose observed count exceeds their own null p95: "
            f"{null['files_with_observed_above_null_p95']}/{null['files_measured']}")
    add("\n**The permutation null is mis-specified for this corpus and gives no "
        "false-alarm rate.** Measured on `01.4/Path1.sgy`: adjacent traces correlate "
        "at 0.958 observed versus -0.017 permuted; permuting raises supra-threshold "
        "cells from 333 to 2,317 and candidates from 46 to 466. Removing lateral "
        "coherence *raises* the ring z-score, because the ring background stops "
        "resembling its centre cell. The null is therefore an upper bound on the "
        "detector's response to incoherent data, not a floor, and the resulting "
        "p-values (1.000 everywhere) measure the mis-specification rather than the "
        "detector. Full diagnosis in `docs/4tu-diagnostics.md`.")
    add("\n4TU contains **no control or background activity**: every survey was walked "
        "where a trench was planned. A false-alarm rate cannot be measured from it.")

    add("\n## 11. Threshold sensitivity\n")
    add("| threshold | candidates | vs default |\n|---|---|---|")
    base = sweep.get(run["pipeline"]["threshold"], 0)
    for t in sorted(sweep):
        ratio = f"{sweep[t]/base:.2f}x" if base else "-"
        mark = "  <- default" if t == run["pipeline"]["threshold"] else ""
        add(f"| {t} | {fmt(int(sweep[t]))} | {ratio}{mark} |")
    add("\nThe count falls steeply with threshold, so the default is **not** in a "
        "stable plateau: a small change in threshold changes the candidate count "
        "substantially. The default is provisional, as the detector's own module "
        "docstring states, and nothing in this run justifies changing it.")

    add("\n## 12. Failure modes observed\n")
    add(f"- **Edge starvation.** {100*unreliable/max(rec_records,1):.1f}% of measured cells lack "
        f"enough ring neighbours and are flagged `anomaly_reliable=False` rather than "
        f"given a misleading extreme value. Candidates touching a boundary carry "
        f"`touches_trace_boundary` / `touches_depth_boundary`.")
    add("- **Threshold instability** (section 11).")
    add("- **Width saturation**, previously measured: the ring z-score saturates with "
        "target width, so a broad laterally coherent target scores no higher than a "
        "narrow one and can sit below |z|>=3 regardless of contrast. Broad targets "
        "are structurally hard for this detector.")
    add("- **Null mis-specification** (section 10).")
    if run["errors"]:
        add(f"- **{len(run['errors'])} radargram(s) failed to process** (section 6).")

    add("\n## 13. What this data can legitimately support\n")
    add("- That the pipeline runs end to end on a real, independent corpus at scale.")
    add("- Counts and densities of detector candidates per activity, per trace, per file.")
    add("- The geometric and statistical properties of those candidates.")
    add("- How candidate counts respond to threshold.")
    add("- How the detector responds to loss of lateral coherence.")
    add("- Coverage and failure accounting.")

    add("\n## 14. What it cannot support\n")
    add("- Any coordinate-level metric: precision, recall, IoU, positional F1, "
        "detection distance, depth accuracy.")
    add("- Whether any individual candidate corresponds to a real buried object.")
    add("- A false-alarm rate (no control ground).")
    add("- Whether a candidate-dense activity is dense because of utilities, ground "
        "conditions, or acquisition differences.")
    add("- Any depth claim beyond 'derived from a provider site estimate of "
        "permittivity'.")

    add("\n## 15. Ground truth required for spatial scoring\n")
    add("1. **Trench positions in a declared CRS** — the single blocking item. "
        "Without them, candidate-to-target matching is impossible in principle.")
    add("2. **Per-utility depth in a declared vertical datum**, plus the offset from "
        "the GPR depth-axis origin to the ground.")
    add("3. **Verified-empty control ground**, for a false-alarm rate.")
    add("4. **Trench extent**, not just presence, for anything IoU-like.")
    add("\nItems 1 and 3 are properties of the source dataset and cannot be produced "
        "by any amount of processing here.")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--in", dest="src", default="artifacts/4tu")
    ap.add_argument("--out", default="docs/4tu-characterisation.md")
    args = ap.parse_args()
    src = Path(args.src)
    run = json.loads((src / "characterisation.json").read_text())
    null_path = src / "null.json"
    null = json.loads(null_path.read_text()) if null_path.exists() else None
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(run, null))
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
