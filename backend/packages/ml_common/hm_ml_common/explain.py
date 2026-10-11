"""LIME wrappers that return JSON-serializable explanations (for APIs and as agent tool output).

Requires the `explain` extra (lime + scikit-learn).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
from pydantic import BaseModel

PredictProba = Callable[[np.ndarray], np.ndarray]


class FeatureContribution(BaseModel):
    feature: str  # LIME rule, e.g. "amount > 0.67"
    weight: float  # signed contribution toward `explained_class`


class Explanation(BaseModel):
    explained_class: str
    probabilities: dict[str, float]
    contributions: list[FeatureContribution]
    intercept: float | None = None
    method: str = "lime"

    def top(self, n: int = 3) -> list[FeatureContribution]:
        return sorted(self.contributions, key=lambda c: abs(c.weight), reverse=True)[:n]

    def to_text(self, n: int = 5) -> str:
        """Compact summary for an LLM prompt or a judge-facing UI string."""
        probs = ", ".join(f"{k}={v:.2f}" for k, v in self.probabilities.items())
        parts = [f"{c.feature} ({'+' if c.weight >= 0 else '-'}{abs(c.weight):.3f})" for c in self.top(n)]
        return f"Predicted {self.explained_class} [{probs}]. Top factors: " + "; ".join(parts)


class TabularExplainer:
    def __init__(
        self,
        training_data: np.ndarray,
        feature_names: Sequence[str],
        class_names: Sequence[str] = ("negative", "positive"),
        categorical_features: Sequence[int] | None = None,
        seed: int = 0,
    ) -> None:
        from lime.lime_tabular import LimeTabularExplainer

        self.class_names = list(class_names)
        self._explainer = LimeTabularExplainer(
            np.asarray(training_data),
            feature_names=list(feature_names),
            class_names=self.class_names,
            categorical_features=list(categorical_features or []),
            mode="classification",
            discretize_continuous=True,
            random_state=seed,
        )

    def explain(
        self,
        instance: np.ndarray,
        predict_proba: PredictProba,
        num_features: int = 8,
        num_samples: int = 1000,
        label: int | None = None,
    ) -> Explanation:
        instance = np.asarray(instance, dtype=float).ravel()
        probs = np.asarray(predict_proba(instance.reshape(1, -1)))[0]
        label = int(np.argmax(probs)) if label is None else label
        exp = self._explainer.explain_instance(
            instance, predict_proba, labels=(label,), num_features=num_features, num_samples=num_samples
        )
        return Explanation(
            explained_class=self.class_names[label],
            probabilities={name: float(p) for name, p in zip(self.class_names, probs, strict=False)},
            contributions=[
                FeatureContribution(feature=f, weight=float(w)) for f, w in exp.as_list(label=label)
            ],
            intercept=float(exp.intercept[label]) if exp.intercept is not None else None,
        )


class TextExplainer:
    """For text classifiers (e.g. transaction descriptions -> business/personal)."""

    def __init__(self, class_names: Sequence[str] = ("negative", "positive"), seed: int = 0) -> None:
        from lime.lime_text import LimeTextExplainer

        self.class_names = list(class_names)
        self._explainer = LimeTextExplainer(class_names=self.class_names, random_state=seed)

    def explain(
        self,
        text: str,
        predict_proba: Callable[[list[str]], np.ndarray],
        num_features: int = 8,
        num_samples: int = 500,
    ) -> Explanation:
        probs = np.asarray(predict_proba([text]))[0]
        label = int(np.argmax(probs))
        exp = self._explainer.explain_instance(
            text, predict_proba, labels=(label,), num_features=num_features, num_samples=num_samples
        )
        return Explanation(
            explained_class=self.class_names[label],
            probabilities={name: float(p) for name, p in zip(self.class_names, probs, strict=False)},
            contributions=[
                FeatureContribution(feature=f, weight=float(w)) for f, w in exp.as_list(label=label)
            ],
        )
