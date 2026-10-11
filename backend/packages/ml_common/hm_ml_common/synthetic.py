"""Synthetic tabular data helpers for bootstrapping models before real data exists.

Projects should write their own domain generator (e.g. invoices with injected fraud patterns) on top of
these primitives and save outputs to data/processed/ with a note in data/DATA.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Dataset:
    X: np.ndarray
    y: np.ndarray
    feature_names: list[str]
    class_names: list[str] = field(default_factory=lambda: ["negative", "positive"])

    def __len__(self) -> int:
        return len(self.y)


def make_classification_data(
    n_samples: int = 2000,
    n_features: int = 8,
    positive_rate: float = 0.1,
    n_informative: int = 4,
    signal: float = 1.5,
    seed: int = 0,
    feature_names: list[str] | None = None,
) -> Dataset:
    """Imbalanced binary data: positives are shifted by `signal` on the first `n_informative` features."""
    rng = np.random.default_rng(seed)
    y = (rng.random(n_samples) < positive_rate).astype(np.int64)
    X = rng.normal(size=(n_samples, n_features))
    shift = np.zeros(n_features)
    shift[: min(n_informative, n_features)] = signal
    X[y == 1] += shift
    names = feature_names or [f"f{i}" for i in range(n_features)]
    if len(names) != n_features:
        raise ValueError("feature_names length must equal n_features")
    return Dataset(X.astype(np.float32), y, names)


def add_label_noise(y: np.ndarray, rate: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    flip = rng.random(len(y)) < rate
    out = y.copy()
    out[flip] = 1 - out[flip]
    return out


def train_val_test_split(
    X: np.ndarray, y: np.ndarray, val: float = 0.15, test: float = 0.15, seed: int = 0, stratify: bool = True
) -> tuple[tuple[np.ndarray, np.ndarray], ...]:
    """Returns ((X_train, y_train), (X_val, y_val), (X_test, y_test))."""
    rng = np.random.default_rng(seed)
    groups = [np.flatnonzero(y == c) for c in np.unique(y)] if stratify else [np.arange(len(y))]
    train_idx, val_idx, test_idx = [], [], []
    for idx in groups:
        idx = rng.permutation(idx)
        n_test, n_val = round(len(idx) * test), round(len(idx) * val)
        test_idx.append(idx[:n_test])
        val_idx.append(idx[n_test : n_test + n_val])
        train_idx.append(idx[n_test + n_val :])
    parts = [rng.permutation(np.concatenate(p)) for p in (train_idx, val_idx, test_idx)]
    return tuple((X[p], y[p]) for p in parts)
