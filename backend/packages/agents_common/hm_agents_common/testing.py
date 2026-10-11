"""Offline Strands model for tests and demo rehearsals without burning the 60 rpm budget.

model = ScriptedModel([
    {"tool": "lookup_invoice", "input": {"invoice_id": "inv_1"}},   # turn 1: call a tool
    "Invoice inv_1 looks fine.",                                     # turn 2: final answer
])
agent = make_agent(name="t", system_prompt="...", tools=[lookup_invoice], model=model)
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterable
from typing import Any

from strands.models.model import Model

Turn = str | dict[str, Any]


class ScriptedModel(Model):
    def __init__(self, turns: list[Turn], repeat_last: bool = True) -> None:
        self.turns = list(turns)
        self.repeat_last = repeat_last
        self.calls: list[list[dict[str, Any]]] = []
        self._config: dict[str, Any] = {"model_id": "scripted"}

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return self._config

    def _next_turn(self) -> Turn:
        idx = len(self.calls) - 1
        if idx < len(self.turns):
            return self.turns[idx]
        if self.repeat_last and self.turns:
            return self.turns[-1]
        raise IndexError("ScriptedModel ran out of turns")

    async def stream(
        self, messages: Any, tool_specs: Any = None, system_prompt: Any = None, **kwargs: Any
    ) -> AsyncIterable[Any]:  # type: ignore[override]
        self.calls.append(list(messages))
        turn = self._next_turn()
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(turn, dict) and "tool" in turn:
            tool_use = {"name": turn["tool"], "toolUseId": turn.get("id", f"tooluse_{uuid.uuid4().hex[:12]}")}
            yield {"contentBlockStart": {"start": {"toolUse": tool_use}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(turn.get("input", {}))}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": str(turn)}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                "metrics": {"latencyMs": 0},
            }
        }

    async def structured_output(  # type: ignore[override]
        self, output_model: Any, prompt: Any, system_prompt: Any = None, **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        raise NotImplementedError("script a tool call to the structured-output tool instead")
        yield {}
