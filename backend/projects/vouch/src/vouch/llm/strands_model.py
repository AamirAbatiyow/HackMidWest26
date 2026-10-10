"""Strands model provider for Akamai hosted inference (OpenAI-compatible).

Quirks handled here:
* the endpoint rejects an empty ``tools: []`` list → dropped when no tools are offered;
* ``max_tokens`` defaults to ~1024 (service default is 512, max 4096);
* non-streaming by default (latency is already 0.3–1.4 s; no ``stream_options`` needed).

Rate limiting and usage accounting live in the shared HTTP client (``AkamaiInference``),
so they also cover ``structured_output`` calls that bypass agent hooks.
"""

from __future__ import annotations

from typing import Any

from strands.models.openai import OpenAIModel

from ..config import Settings
from .client import AkamaiInference


class AkamaiStrandsModel(OpenAIModel):
    def __init__(
        self,
        inference: AkamaiInference,
        *,
        settings: Settings | None = None,
        stream: bool = False,
        **params: Any,
    ) -> None:
        s = settings or inference.settings
        model_params = {"max_tokens": s.llm_max_tokens, "temperature": 0.0, **params}
        super().__init__(
            client=inference.async_client(), model_id=s.akamai_chat_model, params=model_params, stream=stream
        )
        self.inference = inference

    def format_request(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        request = super().format_request(*args, **kwargs)
        if not request.get("tools"):
            request.pop("tools", None)
            request.pop("tool_choice", None)
        return request
