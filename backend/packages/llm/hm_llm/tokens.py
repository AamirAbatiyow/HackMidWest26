"""Cheap token estimates and context trimming for a 32k-context / 4096-output endpoint.

Uses a conservative chars-per-token heuristic (no tokenizer dependency). The safety margin
absorbs estimation error and tool/JSON-schema overhead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

CHARS_PER_TOKEN = 3.5
PER_MESSAGE_OVERHEAD = 4


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            _content_text(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content
        )
    return str(content)


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    return 2 + sum(PER_MESSAGE_OVERHEAD + estimate_tokens(_content_text(m.get("content"))) for m in messages)


def truncate_text(text: str, max_tokens: int, marker: str = "\n…[truncated]") -> str:
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    if len(text) <= max_chars:
        return text
    return text[: max(max_chars - len(marker), 0)] + marker


@dataclass(frozen=True)
class TokenBudget:
    max_context: int = 32_000
    max_output: int = 4_096
    safety_margin: float = 0.10

    def clamp_output(self, requested: int | None = None) -> int:
        return max(1, min(requested or self.max_output, self.max_output))

    def input_budget(self, max_output: int | None = None) -> int:
        return int(self.max_context * (1 - self.safety_margin)) - self.clamp_output(max_output)

    def fits(self, messages: list[dict[str, Any]], max_output: int | None = None) -> bool:
        return estimate_message_tokens(messages) <= self.input_budget(max_output)

    def trim(self, messages: list[dict[str, Any]], max_output: int | None = None) -> list[dict[str, Any]]:
        """Keep system messages and the newest turns that fit; truncate the last message if needed."""
        budget = self.input_budget(max_output)
        system = [m for m in messages if m.get("role") == "system"]
        rest = [m for m in messages if m.get("role") != "system"]
        used = estimate_message_tokens(system)
        kept: list[dict[str, Any]] = []
        for msg in reversed(rest):
            cost = PER_MESSAGE_OVERHEAD + estimate_tokens(_content_text(msg.get("content")))
            if used + cost > budget and kept:
                break
            kept.append(msg)
            used += cost
        kept.reverse()
        if kept and used > budget:
            last = dict(kept[-1])
            overflow = used - budget
            text = _content_text(last.get("content"))
            last["content"] = truncate_text(text, max(estimate_tokens(text) - overflow, 0))
            kept[-1] = last
        return system + kept
