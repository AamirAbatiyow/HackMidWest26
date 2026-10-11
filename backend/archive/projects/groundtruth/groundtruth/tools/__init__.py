"""Agent tools. Plain functions here; `get_tools()` wraps them for Strands lazily."""

from typing import Any

import httpx

from groundtruth.config import get_settings


def predict(features: dict[str, float], explain: bool = True) -> dict[str, Any]:
    """Score a record with the trained groundtruth model and return the label, score and top factors.

    Args:
        features: Mapping of feature name to numeric value.
        explain: Include a LIME explanation of the score.
    """
    resp = httpx.post(
        f"{get_settings().inference_url}/predict", json={"features": features, "explain": explain}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def get_tools() -> list[Any]:
    from strands import tool

    # TODO: add settlement (hm_settlement.get_adapter()), storage, or MCP tools as the concept needs.
    return [tool(predict)]
