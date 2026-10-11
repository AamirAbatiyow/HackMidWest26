"""untangle model inference service (`make serve-untangle`), deployed as its own container.

Loads the latest model bundle from the registry (written by models/train.py). Agents call it through
the fixed `predict` tool; the frontend may call it directly for charts.
"""

from typing import Any

import numpy as np
from pydantic import BaseModel

from hm_api_common import create_app, run
from hm_core.errors import ConfigError, ValidationFailedError
from hm_ml_common import ModelRegistry
from untangle import __version__
from untangle.config import get_settings

settings = get_settings()
_state: dict[str, Any] = {}


def reset() -> None:
    _state.clear()


def get_bundle() -> dict[str, Any]:
    if "bundle" not in _state:
        registry = ModelRegistry()
        version = registry.latest(settings.model_name)
        if version is None:
            raise ConfigError("no trained model yet: run `make train-untangle`")
        _state["bundle"] = registry.load(settings.model_name, version)
        _state["version"] = version
    return _state["bundle"]


def model_loaded() -> bool:
    get_bundle()
    return True


class PredictRequest(BaseModel):
    features: dict[str, float]
    explain: bool = False


class PredictResponse(BaseModel):
    label: str
    score: float
    threshold: float
    model_version: str
    explanation: dict[str, Any] | None = None


app = create_app("untangle-inference", __version__, readiness_checks={"model": model_loaded})


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest) -> PredictResponse:
    bundle = get_bundle()
    names: list[str] = bundle["feature_names"]
    missing = [n for n in names if n not in req.features]
    if missing:
        raise ValidationFailedError("missing features", details={"missing": missing, "expected": names})
    x = np.array([[req.features[n] for n in names]], dtype=float)
    score = float(bundle["model"].predict_proba(x)[0, 1])
    threshold = float(bundle.get("threshold", 0.5))
    explanation = None
    if req.explain:
        from hm_ml_common.explain import TabularExplainer

        explainer = TabularExplainer(bundle["background"], names, bundle["class_names"])
        explanation = explainer.explain(x[0], bundle["model"].predict_proba, num_samples=500).model_dump()
    return PredictResponse(
        label=bundle["class_names"][int(score >= threshold)],
        score=score,
        threshold=threshold,
        model_version=_state["version"],
        explanation=explanation,
    )


def main() -> None:
    run("untangle.services.inference:app", port=settings.inference_port)


if __name__ == "__main__":
    main()
