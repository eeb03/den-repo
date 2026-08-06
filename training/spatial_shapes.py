"""
Phase-0 synthetic 2D SPATIAL shape generator, for classifying anomaly
CLUSTERS found in a lat/lon anomaly grid (e.g. preprocess_spatial_grid_
anomaly's output) — as opposed to synthetic_gpr.py, which classifies the
1D shape of a single multi-sample trace over time/depth.

This is the classifier that's actually usable on data we have today: a
Zenodo depth-slice CSV has no multi-sample traces to feed synthetic_gpr's
classifier, but it DOES have a 2D anomaly grid this one can classify
clusters within.

Same honesty caveat as synthetic_gpr.py: simplified synthetic shapes, not
validated against real labeled field detections. Verified internally
consistent (elongated shapes really do get high elongation scores; round
blobs really do get low elongation; etc.) via direct testing, not just
assumed correct.
"""
from __future__ import annotations

import numpy as np

CLASSES = ["pipe", "cable", "rock", "void", "concrete", "unknown"]

FEATURE_NAMES = ["area", "elongation", "compactness", "mean_magnitude", "aspect_extent"]


def _elongated_line(grid_size: int, length: float, width: float, magnitude: float, rng: np.random.Generator) -> np.ndarray:
    """A thin, long linear feature -- pipe or cable, seen from above."""
    grid = np.zeros((grid_size, grid_size))
    cy, cx = grid_size / 2, grid_size / 2
    angle = rng.uniform(0, np.pi)
    t = np.linspace(-length / 2, length / 2, int(length * 3))
    for ti in t:
        y = cy + ti * np.sin(angle)
        x = cx + ti * np.cos(angle)
        for dy in range(-int(width), int(width) + 1):
            for dx in range(-int(width), int(width) + 1):
                yi, xi = int(round(y + dy)), int(round(x + dx))
                if 0 <= yi < grid_size and 0 <= xi < grid_size and dy**2 + dx**2 <= width**2:
                    grid[yi, xi] = magnitude
    return grid


def _round_blob(grid_size: int, radius: float, magnitude: float, rng: np.random.Generator) -> np.ndarray:
    """A compact, roughly circular feature -- a void or cavity, seen from above."""
    grid = np.zeros((grid_size, grid_size))
    cy, cx = grid_size / 2 + rng.uniform(-2, 2), grid_size / 2 + rng.uniform(-2, 2)
    yy, xx = np.mgrid[0:grid_size, 0:grid_size]
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    grid[r < radius] = magnitude
    return grid


def _irregular_blob(grid_size: int, n_blobs: int, radius: float, magnitude: float, rng: np.random.Generator) -> np.ndarray:
    """Several overlapping irregular sub-blobs -- rock, heterogeneous and patchy."""
    grid = np.zeros((grid_size, grid_size))
    cy, cx = grid_size / 2, grid_size / 2
    yy, xx = np.mgrid[0:grid_size, 0:grid_size]
    for _ in range(n_blobs):
        by = cy + rng.uniform(-radius, radius)
        bx = cx + rng.uniform(-radius, radius)
        br = radius * rng.uniform(0.3, 0.7)
        r = np.sqrt((yy - by) ** 2 + (xx - bx) ** 2)
        grid[r < br] = magnitude * rng.uniform(0.6, 1.0)
    return grid


def _large_flat_region(grid_size: int, extent: float, magnitude: float, rng: np.random.Generator) -> np.ndarray:
    """A large, roughly rectangular region -- a foundation or slab, seen from above."""
    grid = np.zeros((grid_size, grid_size))
    cy, cx = grid_size / 2, grid_size / 2
    h, w = extent * rng.uniform(0.7, 1.0), extent * rng.uniform(0.7, 1.0)
    y0, y1 = int(cy - h / 2), int(cy + h / 2)
    x0, x1 = int(cx - w / 2), int(cx + w / 2)
    grid[max(0, y0):min(grid_size, y1), max(0, x0):min(grid_size, x1)] = magnitude
    return grid


def generate_cluster_grid(class_name: str, grid_size: int = 40, rng: np.random.Generator | None = None) -> np.ndarray:
    """Generates one labeled synthetic anomaly-cluster grid (background zeros + one feature + noise)."""
    rng = rng or np.random.default_rng()
    noise_level = 0.1

    if class_name == "pipe":
        grid = _elongated_line(grid_size, length=rng.uniform(12, 25), width=rng.uniform(1.0, 1.8), magnitude=rng.uniform(3, 5), rng=rng)
    elif class_name == "cable":
        grid = _elongated_line(grid_size, length=rng.uniform(10, 22), width=rng.uniform(0.5, 1.0), magnitude=rng.uniform(2, 3.5), rng=rng)
    elif class_name == "void":
        grid = _round_blob(grid_size, radius=rng.uniform(2.5, 5), magnitude=rng.uniform(4, 6), rng=rng)
    elif class_name == "rock":
        grid = _irregular_blob(grid_size, n_blobs=rng.integers(3, 7), radius=rng.uniform(4, 8), magnitude=rng.uniform(2, 4), rng=rng)
    elif class_name == "concrete":
        grid = _large_flat_region(grid_size, extent=rng.uniform(15, 28), magnitude=rng.uniform(3, 5), rng=rng)
    elif class_name == "unknown":
        # small, ambiguous, low-magnitude blob -- just above noise floor, no clear shape
        grid = _round_blob(grid_size, radius=rng.uniform(1, 2.5), magnitude=rng.uniform(1.5, 2.5), rng=rng)
    else:
        raise ValueError(f"Unknown class '{class_name}'. Options: {CLASSES}")

    grid = grid + rng.normal(0, noise_level, (grid_size, grid_size))
    return grid


def extract_cluster_shape_features(mask: np.ndarray, grid: np.ndarray) -> dict:
    """
    Shape features for the single largest connected cluster in `mask`
    (boolean array). Uses PCA on cluster pixel coordinates for elongation
    (ratio of the two principal-axis variances), bounding-box fill ratio
    for compactness, and real signal magnitude for confidence weighting.
    """
    from scipy import ndimage

    labeled, n = ndimage.label(mask)
    if n == 0:
        return None
    sizes = ndimage.sum(mask, labeled, range(1, n + 1))
    largest_label = int(np.argmax(sizes)) + 1
    ys, xs = np.where(labeled == largest_label)
    area = len(ys)
    if area < 3:
        return None

    coords = np.column_stack([ys, xs]).astype(float)
    coords -= coords.mean(axis=0)
    cov = np.cov(coords.T)
    eigvals = np.sort(np.linalg.eigvalsh(cov))[::-1]
    eigvals = np.clip(eigvals, 0, None)  # guard tiny negative eigenvalues from float error
    # Bounded ratio (range (0.5, 1.0]) rather than eigvals[0]/eigvals[1]:
    # for a near-perfectly-thin line, the minor eigenvalue can be
    # pathologically close to zero from floating-point near-degeneracy,
    # which sends an unbounded ratio to absurd values (verified: a 1px-wide
    # line produced elongation=2.6 billion with the unbounded formula).
    elongation = float(eigvals[0] / (eigvals[0] + eigvals[1] + 1e-9))

    bbox_h = ys.max() - ys.min() + 1
    bbox_w = xs.max() - xs.min() + 1
    bbox_area = bbox_h * bbox_w
    compactness = float(area / bbox_area)
    aspect_extent = float(max(bbox_h, bbox_w))
    mean_magnitude = float(np.mean(np.abs(grid[ys, xs])))

    return {
        "area": float(area), "elongation": elongation, "compactness": compactness,
        "mean_magnitude": mean_magnitude, "aspect_extent": aspect_extent,
        "centroid_row": float(ys.mean()), "centroid_col": float(xs.mean()),
    }


def generate_dataset(n_per_class: int = 200, seed: int = 42) -> tuple[np.ndarray, list[str]]:
    rng = np.random.default_rng(seed)
    X, y = [], []
    for class_name in CLASSES:
        for _ in range(n_per_class):
            grid = generate_cluster_grid(class_name, rng=rng)
            mask = np.abs(grid) > 1.0
            feats = extract_cluster_shape_features(mask, grid)
            if feats is None:
                continue
            X.append([feats[name] for name in FEATURE_NAMES])
            y.append(class_name)
    return np.array(X), y
