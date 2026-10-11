"""Client for a Strands Decider server (``strands-decider serve <checkpoint> --device cpu --port 8099``).

The wire shape below was verified against the upstream repository
(``src/strands_decider/schema.py`` and ``server.py``, github.com/strands-labs/strands-decider):

    POST {url}/v1/systemone
    {"state": <str | dict | list>, "model": "<informational; the server answers as the checkpoint it loaded>",
     "questions": {"<name>": {"type": "choice", "instructions": "...", "criteria": {"<option>": "<description>"}}}}
    -> {"model": "strands-decider-2B-qwen3.5-v1-2610",
        "answers": {"<name>": {"type": "choice", "choice": "<option>", "probabilities": {...}, "confidence": 0.0-1.0}},
        "usage": {"input_tokens": 86, "output_tokens": 1}, "latency_ms": 489.01}
    GET {url}/health -> {"status": "ok", "model": ..., "checkpoint": ..., "base_model": ..., "device": ..., ...}

``noul`` answers carry ``{"type": "noul", "noul": P(true)}`` and ``score`` answers carry
``{"type": "score", "score", "legend", "probabilities", "confidence"}``; ``choice`` confidence is the
normalised max probability ``(N * p_max - 1) / (N - 1)``. A caller error (too many options, malformed
question) is HTTP 422.

Every answer is parsed into a strict Pydantic model (``extra="forbid"``, confidence in [0, 1]); anything
else is rejected and the caller falls back. Requests are strictly sequential (one lock per client): on
CPU a question costs about 1.6 s and the server owns one model, so parallel calls only queue up.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_MODEL = "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610"
DEFAULT_URL = "http://127.0.0.1:8099"
SERVE_HINT = f"strands-decider serve {DEFAULT_MODEL} --device cpu --host 127.0.0.1 --port 8099"

Content = str | dict[str, Any] | list[Any]


class DeciderUnavailable(RuntimeError):
    """The server is down, unreachable or timed out: skip it and fall back (never fail the intake)."""


class DeciderRejected(ValueError):
    """The server answered, but not with a well-formed answer we are willing to act on."""


# --------------------------------------------------------------------------------- wire models ----


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChoiceAnswer(_Strict):
    type: Literal["choice"] = "choice"
    choice: str
    probabilities: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)


class NoulAnswer(_Strict):
    type: Literal["noul"] = "noul"
    noul: float = Field(ge=0.0, le=1.0)


class ScoreAnswer(_Strict):
    type: Literal["score"] = "score"
    score: float
    legend: dict[str, str]
    probabilities: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)


Answer = ChoiceAnswer | NoulAnswer | ScoreAnswer


class Usage(_Strict):
    input_tokens: int = 0
    output_tokens: int = 0


class SystemOneResponse(_Strict):
    model: str
    answers: dict[str, Answer]
    usage: Usage = Field(default_factory=Usage)
    latency_ms: float | None = None


def parse_response(payload: Any) -> SystemOneResponse:
    """Strict parse of a ``/v1/systemone`` body; raises ``DeciderRejected`` for anything off-shape."""
    try:
        return SystemOneResponse.model_validate(payload)
    except ValidationError as exc:
        raise DeciderRejected(f"malformed decider response: {exc.errors()[:3]}") from exc


# ----------------------------------------------------------------------------- question builders ----


def choice(instructions: str, criteria: Mapping[str, str]) -> dict[str, Any]:
    """Pick one of N named options; the option names are defined by the request, not the weights."""
    if len(criteria) < 2:
        raise ValueError("choice needs at least two options")
    return {"type": "choice", "instructions": instructions, "criteria": dict(criteria)}


def noul(instructions: str, criteria: Mapping[str, str] | None = None) -> dict[str, Any]:
    q: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if criteria:
        q["criteria"] = dict(criteria)
    return q


def score(instructions: str, levels: list[str]) -> dict[str, Any]:
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


# ------------------------------------------------------------------------------------- clients ----


class DeciderClient(Protocol):
    name: str

    def ask(self, state: Content, questions: Mapping[str, dict[str, Any]]) -> SystemOneResponse: ...

    def health(self) -> dict[str, Any]: ...


class HttpDeciderClient:
    """Synchronous httpx client; one request at a time."""

    name = "strands-decider"

    def __init__(
        self,
        url: str = DEFAULT_URL,
        timeout_s: float = 20.0,
        model: str = DEFAULT_MODEL,
        *,
        transport: httpx.BaseTransport | None = None,  # tests inject an httpx.MockTransport
    ) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self.model = model
        self.calls = 0
        self.input_tokens = 0
        self.last_latency_ms: float | None = None
        self._lock = threading.Lock()
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=min(3.0, timeout_s)), transport=transport
        )

    def ask(self, state: Content, questions: Mapping[str, dict[str, Any]]) -> SystemOneResponse:
        body = {"state": state, "model": self.model, "questions": dict(questions)}
        with self._lock:
            try:
                r = self._client.post(f"{self.url}/v1/systemone", json=body)
            except httpx.TimeoutException as exc:
                raise DeciderUnavailable(
                    f"decider timed out after {self.timeout_s:.0f}s at {self.url}"
                ) from exc
            except httpx.HTTPError as exc:
                raise DeciderUnavailable(
                    f"no decider at {self.url} ({exc}); start one with: {SERVE_HINT}"
                ) from exc
        if r.status_code >= 500:
            raise DeciderUnavailable(f"decider HTTP {r.status_code} at {self.url}")
        if r.status_code >= 400:
            raise DeciderRejected(f"decider HTTP {r.status_code}: {r.text[:200]}")
        try:
            payload = r.json()
        except json.JSONDecodeError as exc:
            raise DeciderRejected("decider returned non-JSON") from exc
        parsed = parse_response(payload)
        self.calls += 1
        self.input_tokens += parsed.usage.input_tokens
        self.last_latency_ms = parsed.latency_ms
        return parsed

    def health(self) -> dict[str, Any]:
        try:
            r = self._client.get(f"{self.url}/health", timeout=5.0)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise DeciderUnavailable(f"no decider at {self.url} ({exc})") from exc
        if not isinstance(data, dict):
            raise DeciderUnavailable(f"unexpected health body from {self.url}")
        return data


class FakeDeciderClient:
    """Scripted stand-in for tests and CI (never downloads the 4.5 GB model).

    ``answers`` maps a question name to either a raw answer dict (parsed strictly, so a test can feed a
    malformed one) or a callable ``(state, question) -> dict``. Unscripted choice questions get the first
    option at zero confidence. ``fail`` makes every call raise (``DeciderUnavailable`` by default).
    """

    name = "fake-decider"

    def __init__(
        self,
        answers: Mapping[str, dict[str, Any] | Callable[[Content, dict[str, Any]], dict[str, Any]]]
        | None = None,
        *,
        fail: Exception | None = None,
        latency_ms: float = 0.0,
        model: str = "fake-decider-2B",
        sleep_s: float = 0.0,
    ) -> None:
        self.answers = dict(answers or {})
        self.fail = fail
        self.latency_ms = latency_ms
        self.model = model
        self.sleep_s = sleep_s
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def ask(self, state: Content, questions: Mapping[str, dict[str, Any]]) -> SystemOneResponse:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.sleep_s:
                time.sleep(self.sleep_s)
            self.calls.append({"state": state, "questions": dict(questions), "at": time.monotonic()})
            if self.fail is not None:
                raise self.fail
            answers: dict[str, Any] = {}
            for name, q in questions.items():
                scripted = self.answers.get(name)
                if callable(scripted):
                    answers[name] = scripted(state, q)
                elif scripted is not None:
                    answers[name] = dict(scripted)
                else:
                    answers[name] = default_answer(q)
            return parse_response(
                {
                    "model": self.model,
                    "answers": answers,
                    "usage": {"input_tokens": len(str(state)) // 4, "output_tokens": 1},
                    "latency_ms": self.latency_ms,
                }
            )
        finally:
            with self._lock:
                self.active -= 1

    def health(self) -> dict[str, Any]:
        if self.fail is not None:
            raise DeciderUnavailable(str(self.fail))
        return {
            "status": "ok",
            "model": self.model,
            "checkpoint": self.model,
            "device": "fake",
            "base_model": "fake",
        }


def default_answer(question: dict[str, Any]) -> dict[str, Any]:
    kind = question.get("type")
    if kind == "choice":
        options = list(question["criteria"])
        n = len(options)
        return {
            "type": "choice",
            "choice": options[0],
            "probabilities": {o: 1.0 / n for o in options},
            "confidence": 0.0,
        }
    if kind == "noul":
        return {"type": "noul", "noul": 0.5}
    levels = list(question.get("criteria", []))
    return {
        "type": "score",
        "score": (len(levels) - 1) / 2,
        "legend": {str(i): lv for i, lv in enumerate(levels)},
        "probabilities": {str(i): 1.0 / max(1, len(levels)) for i in range(len(levels))},
        "confidence": 0.0,
    }


def choice_answer(option: str, confidence: float, options: list[str]) -> dict[str, Any]:
    """Convenience for tests: a well-formed choice answer putting ``confidence`` worth of mass on ``option``."""
    n = len(options)
    p_max = (confidence * (n - 1) + 1) / n if n > 1 else 1.0
    rest = (1 - p_max) / (n - 1) if n > 1 else 0.0
    return {
        "type": "choice",
        "choice": option,
        "probabilities": {o: (p_max if o == option else rest) for o in options},
        "confidence": confidence,
    }


__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_URL",
    "SERVE_HINT",
    "Answer",
    "ChoiceAnswer",
    "DeciderClient",
    "DeciderRejected",
    "DeciderUnavailable",
    "FakeDeciderClient",
    "HttpDeciderClient",
    "NoulAnswer",
    "ScoreAnswer",
    "SystemOneResponse",
    "choice",
    "choice_answer",
    "default_answer",
    "noul",
    "parse_response",
    "score",
]
