"""Structured output helpers.

- With a Strands agent: `structured_call(agent, MyModel, prompt)` (native `structured_output_model`).
- With a raw OpenAI-compatible call: `json_schema_response_format(MyModel)` -> `response_format=...`,
  then `parse_json_output(text, MyModel)` which tolerates code fences and leading prose.
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def json_schema_response_format(
    model: type[BaseModel], name: str | None = None, strict: bool = False
) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name or model.__name__,
            "schema": model.model_json_schema(),
            "strict": strict,
        },
    }


def _extract_json(text: str) -> Any:
    text = text.strip()
    if fenced := _FENCE.search(text):
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON object found in model output")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start : end + 1])


def parse_json_output(text: str, model: type[T]) -> T:
    try:
        return model.model_validate(_extract_json(text))
    except (ValueError, ValidationError) as exc:
        raise ValueError(f"could not parse {model.__name__} from model output: {exc}") from exc


def structured_call(agent: Any, output_model: type[T], prompt: str | list[Any], **kwargs: Any) -> T:
    """Run a Strands agent and return its validated structured output (raises if missing)."""
    result = agent(prompt, structured_output_model=output_model, **kwargs)
    output = getattr(result, "structured_output", None)
    if output is None:
        raise ValueError(
            f"agent returned no structured output (stop_reason={getattr(result, 'stop_reason', '?')})"
        )
    return output
