"""
Before/after table of every scored scene's validation verdicts.

"Before" is each archived verdict in validation_history/ (v1, v2 ...), never
recomputed; "after" is the current validation.json. A scene built after a
rule change has no archived verdict under that rule, and the table says so
rather than back-filling one.

    python -m simulation.validation_report artifacts/simulation/corpus_s0
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _verdicts(v: dict) -> dict:
    if v.get("status") != "scored":
        return {}
    return {m: r["pass"] for m, r in v["methods"].items()}


def scene_rows(corpus: Path) -> list[dict]:
    rows = []
    for d in sorted(p for p in corpus.iterdir() if (p / "validation.json").exists()):
        current = json.loads((d / "validation.json").read_text())
        if current.get("status") != "scored":
            continue
        truth = json.loads((d / "truth.json").read_text())
        target = truth["targets"][0]
        history = {}
        for h in sorted((d / "validation_history").glob("validation_v*.json")) if (d / "validation_history").exists() else []:
            old = json.loads(h.read_text())
            history[f"v{old.get('analysis_version', 1)}"] = _verdicts(old)
        method = current["methods"][current["pass_basis"]]
        rows.append({
            "scene": d.name,
            "label": target["label"],
            "frequency_hz": truth["wavelet"]["centre_frequency_hz"],
            "soil_eps": truth["medium"]["relative_permittivity"],
            "history": history,
            "current_version": current["analysis_version"],
            "current": _verdicts(current),
            "scored_event": method.get("scored_event", "top"),
            "rms_ps": round(method["checks"]["hyperbola_shape"]["rms_error_s"] * 1e12),
            "top_only_rule_pass": method.get("diagnostics", {}).get("top_only_v2_rule", {}).get("pass"),
        })
    return rows


def summary(rows: list[dict]) -> dict:
    out = {"scored_scenes": len(rows)}
    for m in ("target_free_reference", "mean_trace"):
        out[f"{m}_pass_now"] = sum(r["current"].get(m) is True for r in rows)
        v2 = [r for r in rows if "v2" in r["history"]]
        out[f"{m}_pass_under_archived_v2"] = sum(r["history"]["v2"].get(m) is True for r in v2)
        out[f"{m}_changed_v2_to_now"] = [r["scene"] for r in v2
                                         if r["history"]["v2"].get(m) != r["current"].get(m)]
    out["scenes_with_archived_v2"] = sum("v2" in r["history"] for r in rows)
    out["scored_on_internal_event"] = [r["scene"] for r in rows if r["scored_event"] == "internal"]
    out["failing_now"] = [r["scene"] for r in rows if r["current"].get("target_free_reference") is False]
    return out


def main(argv: list[str] | None = None) -> int:
    corpus = Path((argv or sys.argv[1:])[0])
    rows = scene_rows(corpus)
    report = {"summary": summary(rows), "scenes": rows}
    (corpus / "validation_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
