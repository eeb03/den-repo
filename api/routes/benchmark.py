"""
Benchmark endpoints. Phase 1 provides real metric computation given
predictions + ground truth (precision/recall/F1/depth error) so the
platform is useful for evaluation immediately. Wiring this up to actually
*run* a PyTorch/TF/ONNX model against a dataset is a Phase 2 item that
plugs into the same `/score` computation below.

Separately, `/artifacts` serves the already-generated BAM and 4TU scoring
artifacts read-only, so a client can display validated results without
holding a second copy of them. See the section at the bottom of this file.
"""
import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user, visible_dataset_ids
from database.models import User
from database.session import get_db
from database.models import BenchmarkRun, gen_uuid

router = APIRouter()


class BenchmarkPrediction(BaseModel):
    predicted_label: str
    true_label: str
    predicted_depth: float | None = None
    true_depth: float | None = None
    inference_ms: float | None = None


class BenchmarkScoreRequest(BaseModel):
    model_name: str
    dataset_id: str | None = None
    predictions: list[BenchmarkPrediction]


@router.post("/score")
def score_predictions(
    req: BenchmarkScoreRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    preds = req.predictions
    n = len(preds)
    if n == 0:
        return {"error": "no predictions supplied"}

    tp = sum(1 for p in preds if p.predicted_label == p.true_label and p.true_label != "none")
    fp = sum(1 for p in preds if p.predicted_label != p.true_label and p.predicted_label != "none")
    fn = sum(1 for p in preds if p.predicted_label != p.true_label and p.true_label != "none")
    correct = sum(1 for p in preds if p.predicted_label == p.true_label)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = correct / n

    depth_errors = [
        abs(p.predicted_depth - p.true_depth)
        for p in preds
        if p.predicted_depth is not None and p.true_depth is not None
    ]
    mean_depth_error = sum(depth_errors) / len(depth_errors) if depth_errors else None

    inference_times = [p.inference_ms for p in preds if p.inference_ms is not None]
    mean_inference_ms = sum(inference_times) / len(inference_times) if inference_times else None

    metrics = {
        "classification_accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "mean_depth_error_m": round(mean_depth_error, 4) if mean_depth_error is not None else None,
        "mean_inference_ms": round(mean_inference_ms, 4) if mean_inference_ms is not None else None,
        "sample_count": n,
    }

    run = BenchmarkRun(id=gen_uuid(), model_name=req.model_name, dataset_id=req.dataset_id, metrics=metrics)
    db.add(run)
    db.commit()

    return {"benchmark_run_id": run.id, "metrics": metrics}


@router.get("/runs")
def list_runs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    runs = db.query(BenchmarkRun).all()
    return [
        {"id": r.id, "model_name": r.model_name, "dataset_id": r.dataset_id, "metrics": r.metrics}
        for r in runs
    ]


# ---------------------------------------------------------------------------
# Scoring artifacts, read-only.
#
# The validated BAM and 4TU results are written to artifacts/{bam,4tu}/*.json
# by the scoring scripts. Those files are the single source of truth for the
# reported numbers; this endpoint hands them over unchanged so a client can
# display them without transcribing figures into a second place, where they
# could drift from the evaluation that produced them.
#
# WHAT THIS DELIBERATELY DOES NOT DO. It does not score, run, aggregate,
# rescale, round, reorder, summarise or add a derived field, and it never
# writes. A missing artifact is reported as missing, never generated: the
# artifacts are regenerable by the scripts that own them, and generating one
# here would produce a result nobody asked for at a moment nobody chose.
#
# `artifacts/` is gitignored and regenerable, so "not generated yet" is a
# normal state, not an error. The list endpoint simply omits what is absent.
# ---------------------------------------------------------------------------

#: Repository root -- api/routes/benchmark.py -> api/routes -> api -> root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _artifacts_root() -> Path:
    """
    The benchmark artifacts directory.

    A function rather than a constant so tests can point it at a temporary
    directory without touching the real artifacts.
    """
    return _REPO_ROOT / "artifacts"


#: An artifact name is exactly `<group>/<stem>` -- two path segments of
#: conservative characters. A dot is allowed inside a segment (filenames like
#: `score_1_5_GHz.json` exist) but a segment may not BE a dot sequence, so
#: `..` cannot appear as a segment.
_SEGMENT = r"(?!\.+$)[A-Za-z0-9][A-Za-z0-9._-]*"
_NAME_RE = re.compile(rf"^{_SEGMENT}/{_SEGMENT}$")


def _available_artifacts() -> dict[str, Path]:
    """
    Discovers the artifacts present on disk, as `{name: path}`.

    The returned mapping IS the allowlist. Lookup by name is a dictionary
    access against paths this function produced by globbing -- caller input
    is never joined onto a filesystem path, so directory traversal is not
    merely rejected, it is unrepresentable.
    """
    root = _artifacts_root()
    if not root.is_dir():
        return {}

    found: dict[str, Path] = {}
    for group_dir in sorted(root.iterdir()):
        if not group_dir.is_dir() or group_dir.is_symlink():
            continue
        for path in sorted(group_dir.glob("*.json")):
            if not path.is_file() or path.is_symlink():
                continue
            name = f"{group_dir.name}/{path.stem}"
            if _NAME_RE.match(name):
                found[name] = path
    return found


@router.get("/artifacts", tags=["benchmark"])
def list_artifacts():
    """
    Lists the benchmark scoring artifacts currently present.

    Artifacts that have not been generated are simply absent from the list;
    that is a legitimate state and not an error.

    The per-entry fields are filesystem facts about the file (its size and
    modification time), not anything read out of or derived from the
    scientific content -- `characterisation.json` is roughly 14 MB, and a
    client deserves to know that before fetching it.
    """
    available = _available_artifacts()
    return {
        "artifacts": [
            {
                "name": name,
                "group": name.split("/", 1)[0],
                "filename": path.name,
                "size_bytes": path.stat().st_size,
            }
            for name, path in available.items()
        ],
        "count": len(available),
        "note": (
            "Read-only. Artifacts are generated by the scoring scripts under "
            "scripts/ and are regenerable; an artifact absent from this list "
            "has not been generated, and this endpoint will not generate it."
        ),
    }


@router.get("/artifacts/{name:path}", tags=["benchmark"])
def get_artifact(name: str):
    """
    Returns one artifact's JSON exactly as stored.

    The response is the file's own bytes, so key order, numeric formatting
    and whitespace are byte-identical to what the scoring script wrote. The
    content is parsed only to verify it is well-formed JSON -- which catches
    a truncated or half-written file rather than serving it as valid -- and
    the original bytes are what get returned.
    """
    if not _NAME_RE.match(name):
        raise HTTPException(
            status_code=404,
            detail=(
                f"no benchmark artifact {name!r}. A name is '<group>/<artifact>', "
                f"for example 'bam/score_1_5_GHz_Rot00'."
            ),
        )

    path = _available_artifacts().get(name)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no benchmark artifact {name!r}. It may not have been generated: "
                f"artifacts are produced by the scoring scripts under scripts/ and "
                f"are not created on request. GET /api/benchmark/artifacts lists "
                f"what is present."
            ),
        )

    raw = path.read_bytes()
    try:
        json.loads(raw)
    except json.JSONDecodeError as exc:
        # A partially written artifact must not be served as though it were
        # a complete result.
        raise HTTPException(
            status_code=500,
            detail=(
                f"benchmark artifact {name!r} is not well-formed JSON "
                f"({exc.msg} at line {exc.lineno}); it may be mid-write or "
                f"truncated. It is served verbatim or not at all."
            ),
        ) from exc

    return Response(content=raw, media_type="application/json")
