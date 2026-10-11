"""Risk scoring with LIME explanations.

`get_scorer()` picks, in order (VOUCH_SCORER=auto): the inference service over HTTP, the in-process
torch bundle from the model registry, and finally a transparent heuristic so the demo never stalls.
Every result says which scorer produced it.
"""

from __future__ import annotations

import logging
import re
from typing import Any, ClassVar, Protocol

import httpx
import numpy as np

from vouch.config import Settings, get_settings
from vouch.domain import RISK_CLASSES, ModelScores
from vouch.features import FEATURE_LABELS, NUMERIC_FEATURES

log = logging.getLogger(__name__)
BINARY_FEATURES = {
    n
    for n in NUMERIC_FEATURES
    if n
    not in {
        "amount_log",
        "amount_vs_history",
        "amount_creep",
        "vendor_age_log",
        "history_count_log",
        "urgency_terms",
        "identity_suspicion",
        "shared_bank",
        "shared_tax_id",
        "shared_phone",
        "shared_address",
        "shared_email_domain",
        "component_size_log",
        "component_new_share",
        "neighbour_suspicion",
    }
}
_RULE = re.compile(
    r"^(?:(?P<lo>-?[\d.]+)\s*<\s*)?(?P<name>[a-z_]+)\s*(?P<op><=|<|>=|>)?\s*(?P<hi>-?[\d.]+)?$"
)


class Scorer(Protocol):
    name: str

    def score(self, items: list[dict[str, Any]], explain: bool = True) -> list[ModelScores]: ...


def _humanize(rule: str, weight: float, instance: dict[str, float]) -> dict[str, Any]:
    m = _RULE.match(rule.strip())
    name = m.group("name") if m else rule
    label = FEATURE_LABELS.get(name, name)
    value = instance.get(name)
    if name in BINARY_FEATURES and value is not None:
        text = f"{label}: {'yes' if value >= 0.5 else 'no'}"
    else:
        text = f"{label} ({rule})"
    return {
        "feature": name,
        "label": text,
        "rule": rule,
        "weight": round(float(weight), 4),
        "value": None if value is None else round(float(value), 4),
    }


def _pick_class(risk: dict[str, float]) -> str:
    top = max(risk, key=risk.get)
    return top if risk[top] >= 0.5 else "legitimacy"


class LocalScorer:
    name = "local-torch"

    def __init__(self, bundle: Any, version: str, lime_samples: int = 400):
        self.bundle = bundle
        self.version = version
        self.lime_samples = lime_samples
        self._explainer: Any = None

    @classmethod
    def from_registry(cls, settings: Settings | None = None) -> LocalScorer | None:
        from hm_ml_common import ModelRegistry

        s = settings or get_settings()
        registry = ModelRegistry(s.model_registry_dir)
        version = registry.latest(s.model_name)
        if version is None:
            return None
        try:
            from vouch.models.net import Bundle
        except ImportError:
            log.warning("torch not installed; cannot load %s", s.model_name)
            return None
        return cls(Bundle(registry.load(s.model_name, version)), version, s.lime_samples)

    def _lime(
        self, x: np.ndarray, cats: np.ndarray, head: str, instance: dict[str, float]
    ) -> list[dict[str, Any]]:
        from hm_ml_common.explain import TabularExplainer

        if self._explainer is None:
            self._explainer = TabularExplainer(
                self.bundle.background, NUMERIC_FEATURES, ["no", "yes"], seed=0
            )

        def proba(z: np.ndarray) -> np.ndarray:
            p = self.bundle.predict(z, np.repeat(cats, len(z), axis=0))[head]
            return np.stack([1 - p, p], axis=1)

        exp = self._explainer.explain(x, proba, num_features=6, num_samples=self.lime_samples, label=1)
        return [_humanize(c.feature, c.weight, instance) for c in exp.top(6)]

    def score(self, items: list[dict[str, Any]], explain: bool = True) -> list[ModelScores]:
        if not items:
            return []
        x = np.array([[it["features"][n] for n in NUMERIC_FEATURES] for it in items], dtype=np.float32)
        cats = self.bundle.encode_cats([it.get("categorical", {}) for it in items])
        out = self.bundle.predict(x, cats)
        results = []
        for i, it in enumerate(items):
            risk = {c.value: round(float(out[c.value][i]), 4) for c in RISK_CLASSES}
            head = _pick_class(risk)
            lime = self._lime(x[i], cats[i : i + 1], head, it["features"]) if explain else []
            results.append(
                ModelScores(
                    risk=risk,
                    anomaly=round(float(out["anomaly"][i]), 4),
                    legitimacy=round(float(out["legitimacy"][i]), 4),
                    ring_score=_ring(it["features"]),
                    top_class=max(risk, key=risk.get) if head != "legitimacy" else "honest",
                    model_version=self.version,
                    scorer=self.name,
                    lime=lime,
                    lime_class=head,
                )
            )
        return results


def _ring(f: dict[str, float]) -> float:
    linked = (
        f.get("shared_bank", 0)
        + f.get("shared_tax_id", 0)
        + 0.5 * (f.get("shared_phone", 0) + f.get("shared_address", 0))
    )
    return round(min(1.0, 0.35 * linked + 0.4 * f.get("neighbour_suspicion", 0) * (linked > 0)), 4)


class HeuristicScorer:
    """Transparent fallback when no trained model is available. Clearly labelled in every result."""

    name = "heuristic-fallback"
    WEIGHTS: ClassVar[dict[str, dict[str, float]]] = {
        "ato_bec": {
            "bank_mismatch": 2.5,
            "bank_change_unconfirmed": 2.5,
            "remit_email_mismatch": 1.2,
            "contact_change_recent": 1.0,
            "urgency_terms": 0.5,
            "foreign_bank": 0.8,
            "injection_text": 1.0,
        },
        "insider": {
            "duplicate_suspect": 2.5,
            "split_suspect": 2.5,
            "amount_creep": 1.5,
            "near_approval_limit": 0.8,
            "has_po": -1.0,
            "delivery_confirmed": -1.0,
        },
        "fake_vendor": {
            "tax_id_invalid": 1.5,
            "phone_voip": 0.8,
            "address_virtual": 0.8,
            "new_vendor": 0.6,
            "shared_bank": 1.5,
            "shared_tax_id": 1.5,
            "shared_phone": 0.8,
            "neighbour_suspicion": 1.5,
            "oob_verified": -1.5,
        },
    }
    BIAS = -2.5

    def score(self, items: list[dict[str, Any]], explain: bool = True) -> list[ModelScores]:
        results = []
        for it in items:
            f = it["features"]
            risk, contribs = {}, {}
            for cls, weights in self.WEIGHTS.items():
                parts = {k: w * f.get(k, 0.0) for k, w in weights.items()}
                risk[cls] = round(float(1 / (1 + np.exp(-(self.BIAS + sum(parts.values()))))), 4)
                contribs[cls] = parts
            top = max(risk, key=risk.get)
            legit = round(
                max(0.0, 1 - max(risk.values())) * (0.7 + 0.3 * min(f.get("history_count_log", 0) / 2, 1)), 4
            )
            head = _pick_class(risk)
            parts = contribs[top] if head != "legitimacy" else {k: -v for k, v in contribs[top].items()}
            lime = (
                [_humanize(k, v, f) for k, v in sorted(parts.items(), key=lambda kv: -abs(kv[1]))[:6] if v]
                if explain
                else []
            )
            results.append(
                ModelScores(
                    risk=risk,
                    anomaly=round(float(f.get("identity_suspicion", 0)), 4),
                    legitimacy=legit,
                    ring_score=_ring(f),
                    top_class=top if head != "legitimacy" else "honest",
                    model_version="heuristic-v1",
                    scorer=self.name,
                    lime=lime,
                    lime_class=head,
                )
            )
        return results


class HttpScorer:
    name = "inference-service"

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def score(self, items: list[dict[str, Any]], explain: bool = True) -> list[ModelScores]:
        resp = httpx.post(
            f"{self.base_url}/score", json={"items": items, "explain": explain}, timeout=self.timeout
        )
        resp.raise_for_status()
        return [ModelScores(**r) for r in resp.json()["results"]]

    def ready(self) -> bool:
        try:
            return httpx.get(f"{self.base_url}/ready", timeout=0.5).status_code == 200
        except httpx.HTTPError:
            return False


_cache: dict[str, Any] = {}


def reset_scorer_cache() -> None:
    _cache.clear()


def get_scorer(settings: Settings | None = None) -> Scorer:
    s = settings or get_settings()
    mode = s.scorer
    if mode in ("auto", "http"):
        http = HttpScorer(s.inference_url)
        if http.ready():
            return http
        if mode == "http":
            log.warning("inference service at %s not ready; falling back", s.inference_url)
    if mode in ("auto", "local", "http"):
        if "local" not in _cache:
            _cache["local"] = LocalScorer.from_registry(s)
        if _cache["local"] is not None:
            return _cache["local"]
    return HeuristicScorer()
