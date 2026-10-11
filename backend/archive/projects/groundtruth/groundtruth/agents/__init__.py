"""Strands agents for groundtruth. Requires the `agents` extra (`make setup-agents`).

Patterns to reach for (see .cursor/rules/strands.mdc):
- single agent + tools (start here)
- agents-as-tools: wrap a specialist agent in a @tool and give it to an orchestrator
- strands.multiagent.GraphBuilder for a fixed pipeline, Swarm for open-ended handoffs
"""

from typing import Any

SYSTEM_PROMPT = """TODO: You are the groundtruth assistant. Photo-proof construction milestone payments: verify site evidence against milestones before releasing funds.
Use the `predict` tool for model scores; never invent numbers. Be concise."""


def build_agent(session_id: str | None = None, **kwargs: Any) -> Any:
    from groundtruth.tools import get_tools
    from hm_agents_common.approval import ApprovalHook
    from hm_agents_common.model import make_agent

    return make_agent(
        name="groundtruth",
        system_prompt=SYSTEM_PROMPT,
        tools=get_tools(),
        session_id=session_id,
        # TODO: list the tools that must pause for a human (e.g. anything that moves money).
        hooks=[ApprovalHook(tools=set())],
        **kwargs,
    )
