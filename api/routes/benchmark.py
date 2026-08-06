"""
Benchmark endpoints. Phase 1 provides real metric computation given
predictions + ground truth (precision/recall/F1/depth error) so the
platform is useful for evaluation immediately. Wiring this up to actually
*run* a PyTorch/TF/ONNX model against a dataset is a Phase 2 item that
plugs into the same `/score` computation below.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

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
def score_predictions(req: BenchmarkScoreRequest, db: Session = Depends(get_db)):
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
def list_runs(db: Session = Depends(get_db)):
    runs = db.query(BenchmarkRun).all()
    return [
        {"id": r.id, "model_name": r.model_name, "dataset_id": r.dataset_id, "metrics": r.metrics}
        for r in runs
    ]
