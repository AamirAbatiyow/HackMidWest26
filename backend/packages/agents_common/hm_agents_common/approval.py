"""Human-in-the-loop approval via Strands interrupts, plus policy enforcement on tool calls.

Flow over HTTP (frontend approves in its own UI):
    1. POST /runs           -> result = agent(prompt); if result.stop_reason == "interrupt":
                               return pending_approvals(result)    # [{id, name, reason}]
    2. POST /runs/{id}/approve {decisions: {interrupt_id: true|false|{"approved":..,"note":..}}}
                            -> result = agent(approval_responses(decisions))
    Keep the Agent object alive between the two calls (dict keyed by session id is fine for a demo),
    or use a session manager so interrupt state survives a restart.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from hm_agents_common.policy import PolicyRequest, PolicySet

APPROVAL_INTERRUPT = "approval"
_YES = {"y", "yes", "approve", "approved", "a", "true", "ok"}


def normalize_approval(response: Any) -> tuple[bool, str]:
    """Accepts bool, "yes"/"approve"/..., or {"approved": bool, "note": str}."""
    if isinstance(response, dict):
        return bool(response.get("approved")), str(response.get("note", ""))
    if isinstance(response, bool):
        return response, ""
    if isinstance(response, str):
        return response.strip().lower() in _YES, response
    return False, ""


class ApprovalHook(HookProvider):
    """Pause before selected tool calls and ask a human. Rejection cancels the tool with a reason."""

    def __init__(
        self,
        tools: set[str] | None = None,
        predicate: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        self.tools = tools
        self.predicate = predicate

    def needs_approval(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        if self.tools is not None and tool_name not in self.tools:
            return False
        return self.predicate(tool_name, tool_input) if self.predicate else True

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._check)

    def _check(self, event: BeforeToolCallEvent) -> None:
        name, tool_input = event.tool_use["name"], event.tool_use.get("input") or {}
        if not self.needs_approval(name, tool_input):
            return
        response = event.interrupt(
            APPROVAL_INTERRUPT,
            reason={"tool": name, "input": tool_input, "message": f"Approve call to {name}?"},
        )
        approved, note = normalize_approval(response)
        if not approved:
            event.cancel_tool = f"Human reviewer rejected {name}." + (f" Note: {note}" if note else "")


class PolicyHook(HookProvider):
    """Enforce a PolicySet on every tool call: action=`tool:<name>`, context=tool input."""

    def __init__(self, policy: PolicySet, principal: str = "agent", resource: str = "*") -> None:
        self.policy = policy
        self.principal = principal
        self.resource = resource
        self.denials: list[dict[str, Any]] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._check)

    def _check(self, event: BeforeToolCallEvent) -> None:
        name, tool_input = event.tool_use["name"], event.tool_use.get("input") or {}
        decision = self.policy.evaluate(
            PolicyRequest(self.principal, f"tool:{name}", self.resource, tool_input)
        )
        if not decision.allowed:
            self.denials.append({"tool": name, "input": tool_input, "reasons": decision.reasons})
            event.cancel_tool = f"Policy denied {name}: " + "; ".join(decision.reasons)


def pending_approvals(result: Any) -> list[dict[str, Any]]:
    """JSON-safe list of interrupts awaiting a human decision."""
    if getattr(result, "stop_reason", None) != "interrupt":
        return []
    return [{"id": i.id, "name": i.name, "reason": i.reason} for i in result.interrupts]


def approval_responses(decisions: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the content blocks that resume an interrupted agent: `agent(approval_responses({...}))`."""
    return [{"interruptResponse": {"interruptId": iid, "response": resp}} for iid, resp in decisions.items()]


def run_with_approvals(
    agent: Any, prompt: Any, decide: Callable[[dict[str, Any]], Any], max_rounds: int = 10, **kwargs: Any
) -> Any:
    """Synchronous loop for CLIs/tests: `decide(pending)` returns the human response for each interrupt."""
    result = agent(prompt, **kwargs)
    for _ in range(max_rounds):
        pending = pending_approvals(result)
        if not pending:
            return result
        result = agent(approval_responses({p["id"]: decide(p) for p in pending}))
    raise RuntimeError("too many approval rounds")
