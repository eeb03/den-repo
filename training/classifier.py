"""
Multinomial logistic regression (softmax classifier), trained via plain
gradient descent — numpy only, no sklearn/torch dependency. Genuinely
trained on whatever feature matrix it's given (synthetic_gpr.py's output,
initially); produces real class probabilities from real learned weights,
not fabricated confidence numbers.

This is intentionally simple (a linear classifier over hand-crafted
features, not a deep network) — appropriate for a Phase-0 pipeline
proof-of-concept on a small feature space, and it keeps the model fully
inspectable (weights per feature per class are directly interpretable).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)  # numerical stability
    exp = np.exp(z)
    return exp / exp.sum(axis=1, keepdims=True)


def _one_hot(y_idx: np.ndarray, n_classes: int) -> np.ndarray:
    out = np.zeros((len(y_idx), n_classes))
    out[np.arange(len(y_idx)), y_idx] = 1
    return out


class SoftmaxClassifier:
    def __init__(self, classes: list[str]):
        self.classes = classes
        self.n_classes = len(classes)
        self.weights: np.ndarray | None = None  # (n_features+1, n_classes), last row = bias
        self.feature_mean: np.ndarray | None = None
        self.feature_std: np.ndarray | None = None

    def _standardize(self, X: np.ndarray) -> np.ndarray:
        return (X - self.feature_mean) / self.feature_std

    def fit(
        self, X: np.ndarray, y: list[str], lr: float = 0.5, epochs: int = 500,
        l2: float = 0.001, val_split: float = 0.2, seed: int = 0,
    ) -> dict:
        rng = np.random.default_rng(seed)
        n = len(y)
        idx = rng.permutation(n)
        n_val = int(n * val_split)
        val_idx, train_idx = idx[:n_val], idx[n_val:]

        y_idx = np.array([self.classes.index(label) for label in y])

        self.feature_mean = X[train_idx].mean(axis=0)
        self.feature_std = X[train_idx].std(axis=0)
        self.feature_std[self.feature_std == 0] = 1.0

        X_std = self._standardize(X)
        X_bias = np.hstack([X_std, np.ones((len(X_std), 1))])
        n_features = X_bias.shape[1]

        self.weights = rng.normal(0, 0.01, (n_features, self.n_classes))

        y_onehot = _one_hot(y_idx, self.n_classes)
        train_losses, val_accuracies = [], []

        for epoch in range(epochs):
            logits = X_bias[train_idx] @ self.weights
            probs = _softmax(logits)
            grad = X_bias[train_idx].T @ (probs - y_onehot[train_idx]) / len(train_idx)
            grad += l2 * self.weights  # L2 regularization
            self.weights -= lr * grad

            if epoch % 50 == 0 or epoch == epochs - 1:
                train_loss = -np.mean(np.sum(y_onehot[train_idx] * np.log(probs + 1e-12), axis=1))
                train_losses.append(float(train_loss))
                if n_val > 0:
                    val_preds = self.predict(X[val_idx])
                    val_acc = float(np.mean([p == y[i] for p, i in zip(val_preds, val_idx)]))
                    val_accuracies.append(val_acc)

        final_train_preds = self.predict(X[train_idx])
        train_accuracy = float(np.mean([p == y[i] for p, i in zip(final_train_preds, train_idx)]))
        val_accuracy = val_accuracies[-1] if val_accuracies else None

        return {
            "train_accuracy": train_accuracy,
            "val_accuracy": val_accuracy,
            "train_loss_curve": train_losses,
            "val_accuracy_curve": val_accuracies,
            "n_train": len(train_idx),
            "n_val": len(val_idx),
        }

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X_std = self._standardize(X)
        X_bias = np.hstack([X_std, np.ones((len(X_std), 1))])
        return _softmax(X_bias @ self.weights)

    def predict(self, X: np.ndarray) -> list[str]:
        probs = self.predict_proba(X)
        return [self.classes[i] for i in np.argmax(probs, axis=1)]

    def predict_one_with_proba(self, x: np.ndarray) -> dict:
        probs = self.predict_proba(x.reshape(1, -1))[0]
        ranked = sorted(zip(self.classes, probs), key=lambda t: -t[1])
        return {"predicted_class": ranked[0][0], "probabilities": {c: float(p) for c, p in ranked}}

    def save(self, path: str | Path) -> None:
        data = {
            "classes": self.classes,
            "weights": self.weights.tolist(),
            "feature_mean": self.feature_mean.tolist(),
            "feature_std": self.feature_std.tolist(),
        }
        Path(path).write_text(json.dumps(data))

    @classmethod
    def load(cls, path: str | Path) -> "SoftmaxClassifier":
        data = json.loads(Path(path).read_text())
        clf = cls(data["classes"])
        clf.weights = np.array(data["weights"])
        clf.feature_mean = np.array(data["feature_mean"])
        clf.feature_std = np.array(data["feature_std"])
        return clf
