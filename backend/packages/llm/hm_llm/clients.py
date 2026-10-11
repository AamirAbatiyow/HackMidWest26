"""Client factories for Akamai hosted inference (OpenAI-compatible) with Bedrock fallback.

All Akamai traffic in a process goes through one shared limiter (default 60 rpm per key).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
import openai

from hm_core.errors import ConfigError, UpstreamError
from hm_llm.ratelimit import RateLimiter, get_shared_limiter, limiter_key
from hm_llm.settings import LLMSettings, get_llm_settings
from hm_llm.tokens import TokenBudget
from hm_llm.transport import AsyncRateLimitedTransport, RateLimitedTransport

log = logging.getLogger(__name__)


def akamai_limiter(settings: LLMSettings | None = None) -> RateLimiter:
    s = settings or get_llm_settings()
    key = limiter_key(s.akamai_inference_base_url, s.akamai_inference_api_key.get_secret_value())
    return get_shared_limiter(key, s.llm_requests_per_minute)


def token_budget(settings: LLMSettings | None = None) -> TokenBudget:
    s = settings or get_llm_settings()
    return TokenBudget(max_context=s.llm_max_context_tokens, max_output=s.llm_max_output_tokens)


def _require_akamai(s: LLMSettings) -> None:
    if not s.akamai_configured:
        raise ConfigError("Akamai inference not configured (AKAMAI_INFERENCE_BASE_URL/API_KEY/MODEL)")


def make_openai_client(
    settings: LLMSettings | None = None, transport: httpx.BaseTransport | None = None
) -> openai.OpenAI:
    s = settings or get_llm_settings()
    _require_akamai(s)
    http_client = httpx.Client(
        transport=RateLimitedTransport(akamai_limiter(s), inner=transport, max_retries=s.llm_max_retries),
        timeout=s.llm_timeout_seconds,
    )
    return openai.OpenAI(
        base_url=s.akamai_inference_base_url,
        api_key=s.akamai_inference_api_key.get_secret_value(),
        http_client=http_client,
        max_retries=0,
    )


def make_async_openai_client(
    settings: LLMSettings | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> openai.AsyncOpenAI:
    s = settings or get_llm_settings()
    _require_akamai(s)
    http_client = httpx.AsyncClient(
        transport=AsyncRateLimitedTransport(
            akamai_limiter(s), inner=transport, max_retries=s.llm_max_retries
        ),
        timeout=s.llm_timeout_seconds,
    )
    return openai.AsyncOpenAI(
        base_url=s.akamai_inference_base_url,
        api_key=s.akamai_inference_api_key.get_secret_value(),
        http_client=http_client,
        max_retries=0,
    )


def make_bedrock_runtime(settings: LLMSettings | None = None) -> Any:
    import boto3

    s = settings or get_llm_settings()
    return boto3.client("bedrock-runtime", region_name=s.aws_region)


@dataclass
class ChatResult:
    text: str
    provider: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)


def _akamai_chat(
    s: LLMSettings,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    client: Any,
    **kw: Any,
) -> ChatResult:
    client = client or make_openai_client(s)
    resp = client.chat.completions.create(
        model=s.akamai_inference_model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        **kw,
    )
    usage = resp.usage.model_dump() if resp.usage else {}
    return ChatResult(resp.choices[0].message.content or "", "akamai", s.akamai_inference_model, usage)


def _bedrock_chat(
    s: LLMSettings, messages: list[dict[str, Any]], max_tokens: int, temperature: float
) -> ChatResult:
    if not s.bedrock_configured:
        raise ConfigError("BEDROCK_MODEL_ID not set")
    system = [{"text": m["content"]} for m in messages if m["role"] == "system"]
    convo = [
        {"role": m["role"], "content": [{"text": m["content"]}]} for m in messages if m["role"] != "system"
    ]
    resp = make_bedrock_runtime(s).converse(
        modelId=s.bedrock_model_id,
        messages=convo,
        system=system,
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
    )
    text = "".join(part.get("text", "") for part in resp["output"]["message"]["content"])
    return ChatResult(text, "bedrock", s.bedrock_model_id, resp.get("usage", {}))


def chat(
    messages: list[dict[str, Any]],
    *,
    settings: LLMSettings | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    client: Any = None,
    **kwargs: Any,
) -> ChatResult:
    """One-shot chat completion (no agent loop). Trims to the context budget, falls back to Bedrock.

    `kwargs` go to the OpenAI call (e.g. `response_format`, `tools`) and are ignored by the fallback.
    """
    s = settings or get_llm_settings()
    budget = token_budget(s)
    max_tokens = budget.clamp_output(max_tokens)
    temperature = s.llm_temperature if temperature is None else temperature
    messages = budget.trim(messages, max_tokens)

    provider = s.resolve_provider()
    if provider == "bedrock":
        return _bedrock_chat(s, messages, max_tokens, temperature)
    try:
        return _akamai_chat(s, messages, max_tokens, temperature, client, **kwargs)
    except (openai.OpenAIError, httpx.HTTPError) as exc:
        if s.llm_provider == "auto" and s.bedrock_configured:
            log.warning("akamai call failed (%s); falling back to bedrock", type(exc).__name__)
            return _bedrock_chat(s, messages, max_tokens, temperature)
        raise UpstreamError(f"LLM call failed: {exc}") from exc
