"""vouch model inference service (`make serve-vouch`), deployed as its own container.

Loads the latest VouchNet bundle from the registry (written by `make train-vouch`) and returns
per-class risk, anomaly, legitimacy and LIME factors for a batch of invoices.
"""

from typing import Any

from pydantic import BaseModel, Field

from vouch import __version__
from vouch.config import get_settings
from vouch.domain import ModelScores
from vouch.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from hm_api_common import create_app, run
from hm_core.errors import ConfigError, ValidationFailedError
from hm_ml_common import ModelRegistry

settings = get_settings()
_state: dict[str, Any] = {}


def reset() -> None:
    _state.clear()


def get_scorer() -> Any:
    if "scorer" not in _state:
        from vouch.scorer import LocalScorer

        scorer = LocalScorer.from_registry(settings)
        if scorer is None:
            raise ConfigError(
                "no trained model yet (or torch missing): run `make setup-all && make train-vouch`"
            )
        _state["scorer"] = scorer
    return _state["scorer"]


def model_loaded() -> bool:
    get_scorer()
    return True


class ScoreItem(BaseModel):
    features: dict[str, float]
    categorical: dict[str, str] = Field(default_factory=dict)


class ScoreRequest(BaseModel):
    items: list[ScoreItem]
    explain: bool = True


class ScoreResponse(BaseModel):
    results: list[ModelScores]


app = create_app("vouch-inference", __version__, readiness_checks={"model": model_loaded})


@app.post("/score", response_model=ScoreResponse)
def score(req: ScoreRequest) -> ScoreResponse:
    scorer = get_scorer()
    for item in req.items:
        missing = [n for n in NUMERIC_FEATURES if n not in item.features]
        if missing:
            raise ValidationFailedError("missing features", details={"missing": missing})
    results = scorer.score([i.model_dump() for i in req.items], explain=req.explain)
    return ScoreResponse(results=results)


@app.get("/model")
def model_info() -> dict[str, Any]:
    scorer = get_scorer()
    meta = ModelRegistry(settings.model_registry_dir).meta(settings.model_name, scorer.version)
    return {
        "name": settings.model_name,
        "version": scorer.version,
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "metrics": meta.get("metrics", {}),
    }


def main() -> None:
    run("vouch.services.inference:app", port=settings.inference_port)


if __name__ == "__main__":
    main()
