"""Strands model + agent factory wired for the Akamai endpoint limits.

- 60 rpm: `RateLimitHook` awaits the shared limiter before *every* model call (incl. retries), and the
  same limiter guards raw `hm_llm` OpenAI clients in this process.
- 429s: Strands' ModelRetryStrategy retries throttling with exponential backoff.
- 32k context / 4096 output: sliding-window conversation manager + max_tokens clamp.
- Bedrock fallback: LLM_PROVIDER=auto with both providers configured routes through Strands' ModelRouter.
"""

from __future__ import annotations

import logging
from typing import Any

from strands import Agent, ModelRetryStrategy
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.hooks import BeforeModelCallEvent, HookProvider, HookRegistry
from strands.models.model import Model

from hm_agents_common.settings import get_agent_settings
from hm_llm.clients import akamai_limiter, token_budget
from hm_llm.ratelimit import RateLimiter
from hm_llm.settings import LLMSettings, get_llm_settings

log = logging.getLogger(__name__)


class RateLimitHook(HookProvider):
    def __init__(self, limiter: RateLimiter) -> None:
        self.limiter = limiter

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, self._wait)

    async def _wait(self, event: BeforeModelCallEvent) -> None:
        await self.limiter.acquire_async()


def make_akamai_model(settings: LLMSettings | None = None, **params: Any) -> Model:
    from strands.models.openai import OpenAIModel

    s = settings or get_llm_settings()
    params.setdefault("temperature", s.llm_temperature)
    params["max_tokens"] = token_budget(s).clamp_output(params.get("max_tokens"))
    return OpenAIModel(
        client_args={
            "base_url": s.akamai_inference_base_url,
            "api_key": s.akamai_inference_api_key.get_secret_value(),
            "timeout": s.llm_timeout_seconds,
            "max_retries": 0,  # retries handled by ModelRetryStrategy, which re-checks the limiter
        },
        model_id=s.akamai_inference_model,
        params=params,
    )


def make_bedrock_model(settings: LLMSettings | None = None, **params: Any) -> Model:
    from strands.models import BedrockModel

    s = settings or get_llm_settings()
    return BedrockModel(
        model_id=s.bedrock_model_id,
        region_name=s.aws_region,
        temperature=params.get("temperature", s.llm_temperature),
        max_tokens=token_budget(s).clamp_output(params.get("max_tokens")),
    )


def make_model(settings: LLMSettings | None = None, **params: Any) -> Model:
    s = settings or get_llm_settings()
    primary = s.resolve_provider()
    if primary == "bedrock":
        return make_bedrock_model(s, **params)
    akamai = make_akamai_model(s, **params)
    if s.llm_provider == "auto" and s.bedrock_configured:
        try:
            from strands.models.routing import FallbackStrategy, ModelRouter

            return ModelRouter(models=[akamai, make_bedrock_model(s, **params)], strategy=FallbackStrategy())
        except ImportError:  # older strands without routing
            log.warning("strands ModelRouter unavailable; using Akamai without Bedrock fallback")
    return akamai


def make_agent(
    *,
    name: str,
    system_prompt: str,
    tools: list[Any] | None = None,
    model: Model | None = None,
    hooks: list[Any] | None = None,
    session_id: str | None = None,
    window_size: int | None = None,
    settings: LLMSettings | None = None,
    **agent_kwargs: Any,
) -> Agent:
    """Opinionated Agent constructor. Pass `model=ScriptedModel(...)` in tests to run offline."""
    s = settings or get_llm_settings()
    all_hooks: list[Any] = list(hooks or [])
    if model is None:
        model = make_model(s)
        if s.akamai_configured:
            all_hooks.append(RateLimitHook(akamai_limiter(s)))
    if session_id and "session_manager" not in agent_kwargs:
        from hm_agents_common.session import make_session_manager

        agent_kwargs["session_manager"] = make_session_manager(session_id)
    agent_kwargs.setdefault("callback_handler", None)
    return Agent(
        name=name,
        model=model,
        system_prompt=system_prompt,
        tools=tools or [],
        hooks=all_hooks,
        conversation_manager=SlidingWindowConversationManager(
            window_size=window_size or get_agent_settings().agent_window_size
        ),
        retry_strategy=ModelRetryStrategy(max_attempts=6, initial_delay=2, max_delay=60),
        **agent_kwargs,
    )
