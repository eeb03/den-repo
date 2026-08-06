"""
Phase-0 training/classification endpoints. Read training/synthetic_gpr.py's
module docstring before treating this as more than a pipeline proof of
concept -- it's trained on simplified-physics synthetic data only, not
validated against real field data.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

import numpy as np
from scipy import ndimage

from training.synthetic_gpr import generate_dataset, generate_patch, extract_features, CLASSES, FEATURE_NAMES
from training.classifier import SoftmaxClassifier
from training.spatial_shapes import (
    CLASSES as SPATIAL_CLASSES, FEATURE_NAMES as SPATIAL_FEATURE_NAMES,
    generate_dataset as generate_spatial_dataset, extract_cluster_shape_features,
)
from configs.settings import settings
from database.session import get_db
from database.models import Dataset
from database.records_store import load_records
from preprocessing.spatial_grid import build_grid_for_records
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

MODEL_PATH = settings.data_root.parent / "models" / "gpr_classifier_phase0.json"
SPATIAL_MODEL_PATH = settings.data_root.parent / "models" / "spatial_shape_classifier_phase0.json"


class TrainRequest(BaseModel):
    n_per_class: int = 300
    epochs: int = 500
    learning_rate: float = 0.5
    seed: int = 1


@router.post("/synthetic/train")
def train_synthetic_classifier(req: TrainRequest):
    """
    Generates a fresh synthetic dataset, trains the classifier, and reports
    REAL metrics — training accuracy, validation accuracy during training,
    AND accuracy on a completely separate held-out test batch generated
    with a different random seed (so it's not just re-testing on training
    noise realizations). Saves the trained model for /classify to use.
    """
    X, y = generate_dataset(n_per_class=req.n_per_class, seed=req.seed)

    clf = SoftmaxClassifier(CLASSES)
    fit_result = clf.fit(X, y, lr=req.learning_rate, epochs=req.epochs, val_split=0.25, seed=req.seed)

    X_test, y_test = generate_dataset(n_per_class=max(50, req.n_per_class // 4), seed=req.seed + 9999)
    test_preds = clf.predict(X_test)
    held_out_test_accuracy = float(np.mean([p == t for p, t in zip(test_preds, y_test)]))

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    clf.save(MODEL_PATH)

    logger.info(f"Trained synthetic classifier: val_acc={fit_result['val_accuracy']:.3f}, held_out_test_acc={held_out_test_accuracy:.3f}")

    return {
        "warning": "Trained on simplified-physics SYNTHETIC data only. Not validated against real field data. See training/synthetic_gpr.py docstring.",
        "classes": CLASSES,
        "n_samples_total": len(y),
        "chance_level_accuracy": round(1 / len(CLASSES), 4),
        "train_accuracy": fit_result["train_accuracy"],
        "val_accuracy": fit_result["val_accuracy"],
        "held_out_test_accuracy": held_out_test_accuracy,
        "train_loss_curve": fit_result["train_loss_curve"],
        "val_accuracy_curve": fit_result["val_accuracy_curve"],
        "model_saved_to": str(MODEL_PATH),
    }


@router.get("/model_info")
def get_model_info():
    if not MODEL_PATH.exists():
        raise HTTPException(status_code=404, detail="No trained model yet. POST /api/training/synthetic/train first.")
    clf = SoftmaxClassifier.load(MODEL_PATH)
    return {
        "classes": clf.classes,
        "feature_names": FEATURE_NAMES,
        "trained_on": "simplified-physics synthetic data (Phase 0)",
        "warning": "Not validated against real field data.",
    }


class ClassifyPatchRequest(BaseModel):
    patch: list[list[float]]  # a small B-scan window: n_traces rows x n_samples columns


@router.post("/classify")
def classify_patch(req: ClassifyPatchRequest):
    """
    Classifies a B-scan patch (n_traces x n_samples amplitude window) using
    the trained Phase-0 model. Returns real probabilities from the actual
    trained weights -- not fabricated. Only meaningful for genuine
    multi-sample trace data (e.g. a window cut from a SEG-Y survey); a
    single-value depth-slice CSV point doesn't have the shape structure
    (hyperbola/planar/diffuse) these features depend on.
    """
    if not MODEL_PATH.exists():
        raise HTTPException(status_code=404, detail="No trained model yet. POST /api/training/synthetic/train first.")

    patch = np.array(req.patch)
    if patch.ndim != 2 or patch.shape[0] < 4 or patch.shape[1] < 4:
        raise HTTPException(status_code=400, detail="patch must be a 2D array with at least 4 traces and 4 samples.")

    clf = SoftmaxClassifier.load(MODEL_PATH)
    feats = extract_features(patch)
    x = np.array([feats[name] for name in FEATURE_NAMES])
    result = clf.predict_one_with_proba(x)

    return {
        "warning": "Model trained on simplified-physics synthetic data only. Treat as a pipeline demo, not a field-validated detector.",
        "predicted_class": result["predicted_class"],
        "probabilities": result["probabilities"],
        "extracted_features": feats,
    }


@router.get("/synthetic/example_patch")
def get_example_patch(class_name: str = "pipe", seed: int = 0):
    """Returns one freshly-generated synthetic patch for a given class -- useful for testing /classify or inspecting what the generator actually produces."""
    if class_name not in CLASSES:
        raise HTTPException(status_code=400, detail=f"Unknown class '{class_name}'. Options: {CLASSES}")
    rng = np.random.default_rng(seed)
    patch = generate_patch(class_name, rng=rng)
    return {"class_name": class_name, "patch": patch.tolist(), "shape": list(patch.shape)}


# ─────────────────────────────────────────────────────────────────────────
# Spatial-shape classifier: classifies anomaly CLUSTERS in a lat/lon
# anomaly grid (works on real ingested single-value depth-slice data,
# e.g. after running preprocessing_mode=local_anomaly) -- as opposed to
# the trace classifier above, which needs multi-sample traces we don't
# have ingested yet.
# ─────────────────────────────────────────────────────────────────────────

class TrainSpatialRequest(BaseModel):
    n_per_class: int = 200
    epochs: int = 500
    learning_rate: float = 0.5
    seed: int = 1


@router.post("/spatial/train")
def train_spatial_classifier(req: TrainSpatialRequest):
    """Same idea as /synthetic/train, but for the 2D spatial-shape classifier used by /detect_objects."""
    X, y = generate_spatial_dataset(n_per_class=req.n_per_class, seed=req.seed)

    clf = SoftmaxClassifier(SPATIAL_CLASSES)
    fit_result = clf.fit(X, y, lr=req.learning_rate, epochs=req.epochs, val_split=0.25, seed=req.seed)

    X_test, y_test = generate_spatial_dataset(n_per_class=max(40, req.n_per_class // 4), seed=req.seed + 9999)
    test_preds = clf.predict(X_test)
    held_out_test_accuracy = float(np.mean([p == t for p, t in zip(test_preds, y_test)]))

    SPATIAL_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    clf.save(SPATIAL_MODEL_PATH)

    logger.info(f"Trained spatial-shape classifier: val_acc={fit_result['val_accuracy']:.3f}, held_out_test_acc={held_out_test_accuracy:.3f}")

    return {
        "warning": "Trained on simplified-physics SYNTHETIC data only. Not validated against real field data.",
        "classes": SPATIAL_CLASSES,
        "n_samples_total": len(y),
        "chance_level_accuracy": round(1 / len(SPATIAL_CLASSES), 4),
        "train_accuracy": fit_result["train_accuracy"],
        "val_accuracy": fit_result["val_accuracy"],
        "held_out_test_accuracy": held_out_test_accuracy,
        "model_saved_to": str(SPATIAL_MODEL_PATH),
    }


def _explain_prediction(predicted_class: str, feats: dict) -> str:
    """Plain-language explanation from the actual interpretable features that drove the prediction -- not a canned string."""
    parts = []
    if feats["elongation"] > 0.85:
        parts.append(f"strongly elongated shape (score {feats['elongation']:.2f})")
    elif feats["elongation"] < 0.6:
        parts.append(f"compact, roughly round shape (elongation score {feats['elongation']:.2f})")
    else:
        parts.append(f"moderately elongated shape (score {feats['elongation']:.2f})")

    if feats["area"] > 150:
        parts.append(f"large extent ({feats['area']:.0f} grid cells)")
    elif feats["area"] < 15:
        parts.append(f"small extent ({feats['area']:.0f} grid cells)")
    else:
        parts.append(f"moderate extent ({feats['area']:.0f} grid cells)")

    parts.append(f"mean anomaly magnitude {feats['mean_magnitude']:.2f}")

    return f"Classified as {predicted_class} based on: " + "; ".join(parts) + "."


@router.get("/{dataset_id}/detect_objects")
def detect_objects(
    dataset_id: str,
    threshold: float = 2.0,
    depth: float | None = None,
    db=Depends(get_db),
):
    """
    Finds connected clusters of high-magnitude anomaly cells in a dataset's
    stored grid (run preprocessing_mode=local_anomaly first for this to be
    meaningful) and classifies each cluster's SHAPE using the spatial
    classifier. Returns real lat/lon locations, real extracted shape
    features, and real predicted probabilities from the trained model --
    with the same synthetic-only caveat as every other classifier here.

    threshold: minimum |signal| for a cell to count as anomalous (z-score
    units if local_anomaly preprocessing was used).
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    records = load_records(dataset_id)
    if not records:
        raise HTTPException(status_code=404, detail="No stored records found for this dataset")

    if not SPATIAL_MODEL_PATH.exists():
        raise HTTPException(status_code=404, detail="No trained spatial classifier yet. POST /api/training/spatial/train first.")

    grid, lat_centers, lon_centers, used_depth = build_grid_for_records(records, depth=depth, field="signal")
    mask = np.abs(np.nan_to_num(grid, nan=0.0)) > threshold

    labeled, n_clusters = ndimage.label(mask)
    if n_clusters == 0:
        return {
            "dataset_id": dataset_id, "depth": used_depth, "threshold": threshold,
            "detected_objects": [], "note": "No clusters exceeded the threshold at this depth.",
        }

    clf = SoftmaxClassifier.load(SPATIAL_MODEL_PATH)
    detected = []
    for cluster_id in range(1, n_clusters + 1):
        cluster_mask = labeled == cluster_id
        feats = extract_cluster_shape_features(cluster_mask, grid)
        if feats is None:
            continue

        x = np.array([feats[name] for name in SPATIAL_FEATURE_NAMES])
        result = clf.predict_one_with_proba(x)

        row_idx = int(round(feats["centroid_row"]))
        col_idx = int(round(feats["centroid_col"]))
        row_idx = max(0, min(len(lat_centers) - 1, row_idx))
        col_idx = max(0, min(len(lon_centers) - 1, col_idx))

        detected.append({
            "predicted_class": result["predicted_class"],
            "probabilities": result["probabilities"],
            "explanation": _explain_prediction(result["predicted_class"], feats),
            "latitude": float(lat_centers[row_idx]),
            "longitude": float(lon_centers[col_idx]),
            "shape_features": {k: v for k, v in feats.items() if k not in ("centroid_row", "centroid_col")},
        })

    detected.sort(key=lambda d: -d["shape_features"]["mean_magnitude"])

    return {
        "warning": "Classifier trained on simplified-physics synthetic shapes only. Treat as a pipeline demo.",
        "dataset_id": dataset_id,
        "depth": used_depth,
        "threshold": threshold,
        "cluster_count": len(detected),
        "detected_objects": detected,
    }
