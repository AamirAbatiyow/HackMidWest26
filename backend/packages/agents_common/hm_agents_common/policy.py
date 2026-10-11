"""Cedar-style authorization: default deny, any matching `forbid` beats any matching `permit`.

Rules match principal/action/resource with glob patterns plus an optional `when` condition.
Use `PolicyHook` (hm_agents_common.approval) to enforce a PolicySet on every Strands tool call, and
surface `Decision.reasons` in the UI/demo so judges can see *why* an action was blocked.

    policy = PolicySet([
        permit(action="tool:*", description="agents may call tools by default"),
        forbid(action="tool:send_payment", when=lambda r: r.context.get("amount", 0) > 10_000,
               description="payments over $10k need a human"),
    ])
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Literal


@dataclass(frozen=True)
class PolicyRequest:
    principal: str
    action: str
    resource: str = "*"
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Rule:
    effect: Literal["permit", "forbid"]
    principal: str = "*"
    action: str = "*"
    resource: str = "*"
    when: Callable[[PolicyRequest], bool] | None = None
    description: str = ""

    def matches(self, req: PolicyRequest) -> bool:
        if not (
            fnmatchcase(req.principal, self.principal)
            and fnmatchcase(req.action, self.action)
            and fnmatchcase(req.resource, self.resource)
        ):
            return False
        if self.when is None:
            return True
        try:
            return bool(self.when(req))
        except Exception:
            # A broken condition on a forbid rule must fail closed.
            return self.effect == "forbid"

    def label(self) -> str:
        return self.description or f"{self.effect} {self.principal} {self.action} {self.resource}"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reasons: list[str]

    def __bool__(self) -> bool:
        return self.allowed


def permit(**kwargs: Any) -> Rule:
    return Rule(effect="permit", **kwargs)


def forbid(**kwargs: Any) -> Rule:
    return Rule(effect="forbid", **kwargs)


class PolicySet:
    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules = list(rules or [])

    def add(self, rule: Rule) -> PolicySet:
        self.rules.append(rule)
        return self

    def evaluate(self, req: PolicyRequest) -> Decision:
        matched = [r for r in self.rules if r.matches(req)]
        forbids = [r.label() for r in matched if r.effect == "forbid"]
        if forbids:
            return Decision(False, forbids)
        permits = [r.label() for r in matched if r.effect == "permit"]
        if permits:
            return Decision(True, permits)
        return Decision(False, ["no matching permit (default deny)"])

    def is_allowed(self, principal: str, action: str, resource: str = "*", **context: Any) -> bool:
        return self.evaluate(PolicyRequest(principal, action, resource, context)).allowed
