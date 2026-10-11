"""Strands Intervention for the intake agent: ``before_tool_call`` returns ``Guide`` when the LLM's
structured output quotes an amount, date, bank account or identifier that is not grounded in the parsed
invoice text.

The check is deterministic (verbatim, whitespace- and case-insensitive containment in the source), so it
cannot be argued with and it costs nothing: the Decider is *not* called per tool call - it classifies once
per invoice and is never chained. After ``max_guides`` corrections the gate lets the call through and the
kernel's provenance check (``VouchEngine._merge_intake``) still rejects any ungrounded value, which puts the
payment on hold instead of paying an invented number.
"""

from __future__ import annotations

import re
from typing import Any

from strands.interventions import Guide, InterventionHandler, Proceed

# Fields of `IntakeExtraction` whose value must appear verbatim in the invoice text.
GROUNDED_FIELDS = (
    "amount_quote",
    "due_date_quote",
    "issue_date_quote",
    "bank_account_quote",
    "invoice_number",
    "po_number",
    "remit_email",
    "vendor_name",
)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def ungrounded_fields(arguments: dict[str, Any], source: str) -> list[tuple[str, str]]:
    """``(field, value)`` pairs whose value is not found verbatim in ``source``."""
    haystack = _squash(source)
    bad: list[tuple[str, str]] = []
    for field in GROUNDED_FIELDS:
        value = arguments.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        if _squash(value) not in haystack:
            bad.append((field, value))
    return bad


class GroundingIntervention(InterventionHandler):
    """Guide the intake agent back to quoting the document when it invents a value."""

    name = "vouch-intake-grounding"
    on_error = "continue"  # a bug in the gate must never block intake; the kernel still verifies every quote

    def __init__(
        self, source_text: str, *, max_guides: int = 2, tool_names: tuple[str, ...] = ("IntakeExtraction",)
    ):
        self.source_text = source_text
        self.max_guides = max_guides
        self.tool_names = tool_names
        self.guides = 0
        self.log: list[dict[str, Any]] = []

    def before_tool_call(self, event: Any, **kwargs: Any) -> Proceed | Guide:
        tool_use = getattr(event, "tool_use", None) or {}
        name = tool_use.get("name", "")
        if self.tool_names and name not in self.tool_names:
            return Proceed()
        arguments = tool_use.get("input") or {}
        bad = ungrounded_fields(arguments if isinstance(arguments, dict) else {}, self.source_text)
        if bad and self.guides < self.max_guides:
            self.guides += 1
            listed = "; ".join(f"{f}={v!r}" for f, v in bad[:4])
            self.log.append({"tool": name, "verdict": "guided", "fields": [f for f, _ in bad]})
            return Guide(
                feedback=(
                    f"These values are not in the invoice text: {listed}. Copy each value exactly as printed "
                    "(same characters) or leave the field empty. Never calculate or reformat."
                ),
                reason="ungrounded structured output",
            )
        self.log.append({"tool": name, "verdict": "proceeded", "fields": [f for f, _ in bad]})
        return Proceed()

    @property
    def guided(self) -> bool:
        return self.guides > 0


__all__ = ["GROUNDED_FIELDS", "GroundingIntervention", "ungrounded_fields"]
