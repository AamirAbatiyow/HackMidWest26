"""Binary classification metrics in pure numpy (no sklearn needed at serve time)."""

from __future__ import annotations

from typing import Any

import numpy as np


def roc_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    y_true = np.asarray(y_true)
    pos, neg = int(y_true.sum()), int(len(y_true) - y_true.sum())
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(y_score, kind="mergesort")
    ranks = np.empty(len(y_score))
    sorted_scores = np.asarray(y_score)[order]
    i = 0
    while i < len(sorted_scores):  # average ranks for ties
        j = i
        while j + 1 < len(sorted_scores) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[y_true == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def average_precision(y_true: np.ndarray, y_score: np.ndarray) -> float:
    order = np.argsort(-np.asarray(y_score), kind="mergesort")
    y = np.asarray(y_true)[order]
    if y.sum() == 0:
        return float("nan")
    precision_at_hits = np.cumsum(y) / np.arange(1, len(y) + 1)
    return float((precision_at_hits * y).sum() / y.sum())


def precision_at_k(y_true: np.ndarray, y_score: np.ndarray, k: int) -> float:
    """Of the top-k most suspicious items, what fraction are truly positive (review-queue quality)."""
    top = np.argsort(-np.asarray(y_score), kind="mergesort")[:k]
    return float(np.asarray(y_true)[top].mean()) if k > 0 else float("nan")


def classification_report(y_true: np.ndarray, y_score: np.ndarray, threshold: float = 0.5) -> dict[str, Any]:
    y_true = np.asarray(y_true).astype(int)
    y_pred = (np.asarray(y_score) >= threshold).astype(int)
    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": threshold,
        "accuracy": (tp + tn) / len(y_true) if len(y_true) else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "roc_auc": roc_auc(y_true, y_score),
        "pr_auc": average_precision(y_true, y_score),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "support": {"positive": int(y_true.sum()), "negative": int(len(y_true) - y_true.sum())},
    }


def best_threshold(y_true: np.ndarray, y_score: np.ndarray, metric: str = "f1") -> float:
    candidates = np.unique(np.round(np.asarray(y_score), 4))
    scores = [classification_report(y_true, y_score, float(t))[metric] for t in candidates]
    return float(candidates[int(np.argmax(scores))]) if len(candidates) else 0.5
