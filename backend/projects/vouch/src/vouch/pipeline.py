"""The payment graph, built with the Strands multi-agent Graph.

    intake -> resolve -> sender -> kernel -> score -> investigate -> policy -> funding -> explain
     (LLM)     (det)     (det)     (det)    (model)     (LLM)        (det)     (det)      (LLM)
           -> fast_pay -> settle
              (ledger)   (ledger)

- `resolve` (vendor resolution: known / new / uncertain) and `sender` (SPF/DKIM/DMARC, lookalike
  domains, reply-to) are deterministic and run *before* any detector or LLM sees the card.

- Every node is a `MultiAgentBase` executor sharing one `Run` through `invocation_state["run"]`; LLM nodes
  create their own Strands agents (structured output) inside the node.
- `OwnerApprovalHook` fires on `BeforeNodeCallEvent` for `settle` and raises a Strands interrupt; the graph
  stops with status INTERRUPTED and resumes when the owner answers (POST /v1/runs/{id}/approve).
- A second, two-node graph (`policy -> settle`) is used for later settlements after holds are resolved, so
  every movement of money passes the same approval interrupt and policy re-check.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import Callable
from typing import Any

from strands.agent.agent_result import AgentResult
from strands.hooks import BeforeNodeCallEvent, HookProvider, HookRegistry
from strands.multiagent import GraphBuilder
from strands.multiagent.base import MultiAgentBase, MultiAgentResult, NodeResult, Status
from strands.telemetry.metrics import EventLoopMetrics

from vouch.engine import VouchEngine, Run
from hm_agents_common.approval import approval_responses, normalize_approval

APPROVAL_INTERRUPT = "owner_approval"
LLM_NODES = {"intake", "investigate", "explain"}


class StageNode(MultiAgentBase):
    """Graph node that runs one deterministic or LLM-backed stage of the vouch pipeline."""

    def __init__(self, node_id: str, fn: Callable[[Run], None], service: VouchEngine):
        super().__init__()
        self.id = node_id
        self.fn = fn
        self.service = service

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        run: Run = (invocation_state or {})["run"]
        stats = self.service.llm.stats
        before = (stats.input_tokens, stats.output_tokens, stats.calls)
        run.emit("node_start", node=self.id)
        t0 = time.perf_counter()
        await asyncio.to_thread(self.fn, run)
        ms = int((time.perf_counter() - t0) * 1000)
        run.node_ms[self.id] = run.node_ms.get(self.id, 0) + ms
        self.service.time(f"node:{self.id}", ms)
        usage = {
            "inputTokens": stats.input_tokens - before[0],
            "outputTokens": stats.output_tokens - before[1],
            "totalTokens": stats.input_tokens - before[0] + stats.output_tokens - before[1],
        }
        run.emit(
            "node_done", node=self.id, ms=ms, llm_calls=stats.calls - before[2], tokens=usage["totalTokens"]
        )
        self.service.changed(run)
        text = f"{self.id} done in {ms} ms"
        agent_result = AgentResult(
            stop_reason="end_turn",
            message={"role": "assistant", "content": [{"text": text}]},
            metrics=EventLoopMetrics(),
            state={},
        )
        node_result = NodeResult(
            result=agent_result,
            execution_time=ms,
            status=Status.COMPLETED,
            accumulated_usage=usage,
            execution_count=1,
        )  # type: ignore[arg-type]
        return MultiAgentResult(
            status=Status.COMPLETED,
            results={self.id: node_result},
            execution_time=ms,
            accumulated_usage=usage,
            execution_count=1,
        )  # type: ignore[arg-type]


def strict_approval(response: Any) -> tuple[bool, str]:
    """Money moves only on an unambiguous yes: `true`, an approve word, or {"approved": true}.
    (A truthy string such as {"approved": "false"} is a decline.)"""
    if isinstance(response, dict):
        return response.get("approved") is True, str(response.get("note", ""))
    if isinstance(response, bool | str):
        return normalize_approval(response)
    return False, ""


class OwnerApprovalHook(HookProvider):
    """Interrupt before the `settle` node so the business owner approves the batch (human in the loop).

    The interrupt reason carries the kernel's batch summary. The response may be `true`, `"approve"`, or
    `{"approved": true, "card_ids": [...], "approver": "...", "note": "..."}`. Anything else is a decline.
    """

    def __init__(self, service: VouchEngine):
        self.service = service

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeNodeCallEvent, self._before_node)

    def _before_node(self, event: BeforeNodeCallEvent) -> None:
        if event.node_id != "settle":
            return
        run: Run = (event.invocation_state or {})["run"]
        summary = self.service.approval_summary(run)
        if summary is None:
            run.approval = {"approved": False, "reason": "nothing waiting for approval"}
            return
        response = event.interrupt(APPROVAL_INTERRUPT, reason=summary)
        approved, note = strict_approval(response)
        extra = response if isinstance(response, dict) else {}
        run.approval = {
            "approved": approved,
            "note": note,
            "card_ids": extra.get("card_ids"),
            "approver": extra.get("approver", "owner"),
        }
        run.emit("owner_decision", approved=approved, card_ids=extra.get("card_ids"))


def build_graph(service: VouchEngine, stages: list[str] | None = None) -> Any:
    fns: dict[str, Callable[[Run], None]] = {
        "intake": service.intake,
        "resolve": service.resolve_vendors,
        "sender": service.sender_check,
        "kernel": service.kernel,
        "score": service.score,
        "investigate": service.investigate,
        "policy": service.decide,
        "funding": service.fund,
        "explain": service.explain,
        "fast_pay": service.fast_pay,
        "settle": service.settle,
    }
    order = stages or list(fns)
    builder = GraphBuilder()
    for node_id in order:
        builder.add_node(StageNode(node_id, fns[node_id], service), node_id)
    for a, b in itertools.pairwise(order):
        builder.add_edge(a, b)
    builder.set_entry_point(order[0])
    builder.set_hook_providers([OwnerApprovalHook(service)])
    builder.set_execution_timeout(600)
    builder.set_max_node_executions(len(order) * 2)
    return builder.build()


def _after(service: VouchEngine, run: Run, result: Any) -> Run:
    if result.status == Status.INTERRUPTED and result.interrupts:
        intr = result.interrupts[0]
        run.pending = {"interrupt_id": intr.id, "name": intr.name, "reason": intr.reason}
        run.status = "awaiting_approval"
        run.emit("awaiting_approval", interrupt_id=intr.id, total_cents=intr.reason.get("total_cents"))
    else:
        run.pending = None
        run.status = "completed" if result.status == Status.COMPLETED else "failed"
        run.emit("run_" + run.status)
    for card in run.card_list():
        service.build_facts(card)
    service.changed(run)
    return run


STAGES = [
    "intake",
    "resolve",
    "sender",
    "kernel",
    "score",
    "investigate",
    "policy",
    "funding",
    "explain",
    "fast_pay",
    "settle",
]


def execute(service: VouchEngine, run: Run) -> Run:
    """Run the full graph until it completes or stops at the owner-approval interrupt."""
    run.status = "running"
    run.graph = build_graph(service)
    try:
        result = run.graph(
            f"Process {len(run.submissions)} invoice(s) for run {run.id}", invocation_state={"run": run}
        )
    except Exception as exc:
        run.status, run.error = "failed", str(exc)
        run.emit("run_failed", error=str(exc))
        raise
    return _after(service, run, result)


def approve(service: VouchEngine, run: Run, decision: Any) -> Run:
    """Answer the owner-approval interrupt. Starts a settlement graph if nothing is pending."""
    if run.pending is None or run.graph is None:
        run.graph = build_graph(service, ["policy", "funding", "settle"])
        result = run.graph(f"Settle approved cards for run {run.id}", invocation_state={"run": run})
        _after(service, run, result)
        if run.pending is None:
            return run
    run.status = "running"
    result = run.graph(
        approval_responses({run.pending["interrupt_id"]: decision}), invocation_state={"run": run}
    )
    return _after(service, run, result)
