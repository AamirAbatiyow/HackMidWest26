import asyncio

import httpx
import pytest

from hm_core.errors import ConfigError, RateLimitedError
from hm_llm import (
    LLMSettings,
    RateLimitedTransport,
    RateLimiter,
    TokenBudget,
    chat,
    estimate_message_tokens,
    make_openai_client,
    parse_retry_after,
    retry_with_backoff,
)
from hm_llm import clients as clients_mod


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def settings(**overrides) -> LLMSettings:
    base = dict(
        akamai_inference_base_url="https://inference.test/v1",
        akamai_inference_api_key="test-key-" + str(id(overrides)),
        akamai_inference_model="test-model",
        llm_provider="auto",
        bedrock_model_id="",
    )
    base.update(overrides)
    return LLMSettings(_env_file=None, **base)


def completion(text="hi"):
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }


# --- rate limiter ---------------------------------------------------------------------------


def test_limiter_sliding_window():
    clock = FakeClock()
    lim = RateLimiter(3, period=60, clock=clock)
    assert all(lim.try_acquire() for _ in range(3))
    assert not lim.try_acquire()
    assert lim.remaining == 0
    clock.t = 59.9
    assert not lim.try_acquire()
    clock.t = 60.0
    assert lim.try_acquire()


def test_limiter_timeout_raises():
    lim = RateLimiter(1, period=60)
    lim.acquire()
    with pytest.raises(RateLimitedError):
        lim.acquire(timeout=0.05)


def test_limiter_blocks_then_releases():
    lim = RateLimiter(2, period=0.2)
    import time

    start = time.monotonic()
    for _ in range(4):
        lim.acquire()
    assert time.monotonic() - start >= 0.19


async def test_limiter_async_concurrent():
    lim = RateLimiter(5, period=0.2)
    loop = asyncio.get_running_loop()
    start = loop.time()
    await asyncio.gather(*(lim.acquire_async() for _ in range(10)))
    assert loop.time() - start >= 0.19


# --- retry ----------------------------------------------------------------------------------


class Http429(Exception):
    status_code = 429
    retry_after = 0.0


class Http400(Exception):
    status_code = 400


def test_retry_recovers_from_429():
    calls = {"n": 0}
    sleeps = []

    @retry_with_backoff(max_attempts=4, sleep=sleeps.append)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise Http429()
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3 and sleeps == [0.0, 0.0]


def test_retry_does_not_retry_4xx():
    calls = {"n": 0}

    @retry_with_backoff(max_attempts=4, sleep=lambda _: None)
    def bad():
        calls["n"] += 1
        raise Http400()

    with pytest.raises(Http400):
        bad()
    assert calls["n"] == 1


async def test_retry_async_gives_up():
    calls = {"n": 0}

    async def no_sleep(_):
        return None

    @retry_with_backoff(max_attempts=3, sleep=no_sleep)
    async def always_429():
        calls["n"] += 1
        raise Http429()

    with pytest.raises(Http429):
        await always_429()
    assert calls["n"] == 3


def test_parse_retry_after():
    assert parse_retry_after("2") == 2.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("garbage") is None
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


# --- transport + client ---------------------------------------------------------------------


def test_transport_retries_429_then_succeeds():
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"ok": True})

    sleeps = []
    transport = RateLimitedTransport(RateLimiter(60), inner=httpx.MockTransport(handler), sleep=sleeps.append)
    with httpx.Client(transport=transport) as client:
        assert client.get("https://x.test/").json() == {"ok": True}
    assert len(seen) == 2 and sleeps == [0.0]


def test_chat_via_akamai_with_mock_server():
    s = settings()
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": "slow down"})
        return httpx.Response(200, json=completion("hello"))

    client = make_openai_client(s, transport=httpx.MockTransport(handler))
    result = chat([{"role": "user", "content": "hi"}], settings=s, client=client)
    assert result.text == "hello" and result.provider == "akamai"
    assert len(calls) == 2
    assert calls[0].headers["authorization"].startswith("Bearer test-key-")


def test_chat_falls_back_to_bedrock(monkeypatch):
    s = settings(bedrock_model_id="anthropic.test")
    client = make_openai_client(s, transport=httpx.MockTransport(lambda r: httpx.Response(400, json={})))
    monkeypatch.setattr(
        clients_mod, "_bedrock_chat", lambda *a, **k: clients_mod.ChatResult("from bedrock", "bedrock", "m")
    )
    result = chat([{"role": "user", "content": "hi"}], settings=s, client=client)
    assert result.provider == "bedrock"


def test_provider_resolution():
    assert settings().resolve_provider() == "akamai"
    assert settings(akamai_inference_api_key="", bedrock_model_id="x").resolve_provider() == "bedrock"
    with pytest.raises(ConfigError):
        settings(akamai_inference_api_key="").resolve_provider()


# --- token budget ---------------------------------------------------------------------------


def test_token_budget_trim_keeps_system_and_latest():
    budget = TokenBudget(max_context=1000, max_output=200, safety_margin=0.1)
    msgs = [{"role": "system", "content": "rules"}] + [
        {"role": "user", "content": f"msg {i} " + "x" * 700} for i in range(10)
    ]
    assert not budget.fits(msgs)
    trimmed = budget.trim(msgs)
    assert trimmed[0]["role"] == "system"
    assert trimmed[-1]["content"].startswith("msg 9")
    assert budget.fits(trimmed)
    assert budget.clamp_output(10_000) == 200


def test_token_budget_truncates_single_huge_message():
    budget = TokenBudget(max_context=1000, max_output=200)
    trimmed = budget.trim([{"role": "user", "content": "y" * 20_000}])
    assert len(trimmed) == 1 and trimmed[0]["content"].endswith("[truncated]")
    assert estimate_message_tokens(trimmed) <= budget.input_budget()
