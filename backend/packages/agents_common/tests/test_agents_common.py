import pytest
from pydantic import BaseModel

from hm_agents_common import PolicySet, forbid, json_schema_response_format, parse_json_output, permit
from hm_agents_common.policy import PolicyRequest

# --- no strands required ---------------------------------------------------------------------


def payments_policy():
    return PolicySet(
        [
            permit(action="tool:*", description="tools allowed by default"),
            forbid(
                action="tool:send_payment",
                when=lambda r: r.context["amount"] > 10_000,
                description="payments over $10k need a human",
            ),
            forbid(principal="intern", action="tool:send_payment", description="interns cannot pay"),
        ]
    )


def test_policy_forbid_overrides_permit_and_default_deny():
    policy = payments_policy()
    assert policy.is_allowed("agent", "tool:send_payment", amount=50)
    decision = policy.evaluate(PolicyRequest("agent", "tool:send_payment", context={"amount": 20_000}))
    assert not decision and decision.reasons == ["payments over $10k need a human"]
    assert not policy.is_allowed("intern", "tool:send_payment", amount=1)
    assert not PolicySet().is_allowed("agent", "tool:x")


def test_policy_broken_condition_fails_closed():
    policy = PolicySet([permit(), forbid(action="pay", when=lambda r: r.context["missing"] > 1)])
    assert not policy.is_allowed("a", "pay")


class Verdict(BaseModel):
    label: str
    confidence: float


def test_parse_json_output_tolerates_fences_and_prose():
    assert parse_json_output('```json\n{"label": "fraud", "confidence": 0.9}\n```', Verdict).label == "fraud"
    assert (
        parse_json_output('Sure! {"label": "ok", "confidence": 0.1} hope that helps', Verdict).confidence
        == 0.1
    )
    with pytest.raises(ValueError):
        parse_json_output("no json here", Verdict)


def test_json_schema_response_format():
    fmt = json_schema_response_format(Verdict)
    assert fmt["json_schema"]["name"] == "Verdict"
    assert set(fmt["json_schema"]["schema"]["properties"]) == {"label", "confidence"}


# --- strands required (make setup-agents) -----------------------------------------------------


@pytest.fixture
def strands_kit():
    pytest.importorskip("strands")
    from strands import tool

    from hm_agents_common.testing import ScriptedModel

    sent = []

    @tool
    def send_payment(payee: str, amount: float) -> str:
        """Send a payment to a payee."""
        sent.append((payee, amount))
        return f"paid {payee} {amount}"

    return ScriptedModel, send_payment, sent


def test_approval_interrupt_approve_and_reject(strands_kit):
    from hm_agents_common.approval import ApprovalHook, pending_approvals, run_with_approvals
    from hm_agents_common.model import make_agent

    ScriptedModel, send_payment, sent = strands_kit
    script = [{"tool": "send_payment", "input": {"payee": "acme", "amount": 120.0}}, "done"]

    agent = make_agent(
        name="t",
        system_prompt="pay",
        tools=[send_payment],
        model=ScriptedModel(script),
        hooks=[ApprovalHook({"send_payment"})],
    )
    first = agent("pay acme")
    pending = pending_approvals(first)
    assert first.stop_reason == "interrupt" and pending[0]["reason"]["tool"] == "send_payment"

    seen = []
    result = run_with_approvals(
        make_agent(
            name="t2",
            system_prompt="pay",
            tools=[send_payment],
            model=ScriptedModel(script),
            hooks=[ApprovalHook({"send_payment"})],
        ),
        "pay acme",
        decide=lambda p: seen.append(p) or True,
    )
    assert result.stop_reason == "end_turn" and sent == [("acme", 120.0)] and len(seen) == 1

    run_with_approvals(
        make_agent(
            name="t3",
            system_prompt="pay",
            tools=[send_payment],
            model=ScriptedModel(script),
            hooks=[ApprovalHook({"send_payment"})],
        ),
        "pay acme",
        decide=lambda p: {"approved": False, "note": "wrong vendor"},
    )
    assert sent == [("acme", 120.0)]


def test_policy_hook_blocks_tool(strands_kit):
    from hm_agents_common.approval import PolicyHook
    from hm_agents_common.model import make_agent

    ScriptedModel, send_payment, sent = strands_kit
    hook = PolicyHook(payments_policy())
    model = ScriptedModel([{"tool": "send_payment", "input": {"payee": "acme", "amount": 50_000}}, "blocked"])
    make_agent(name="p", system_prompt="pay", tools=[send_payment], model=model, hooks=[hook])("pay")
    assert sent == []
    assert hook.denials[0]["reasons"] == ["payments over $10k need a human"]


def test_make_model_providers():
    pytest.importorskip("strands")
    from hm_agents_common.model import make_model
    from hm_llm import LLMSettings

    base = dict(
        akamai_inference_base_url="https://x.test/v1",
        akamai_inference_api_key="k",
        akamai_inference_model="m",
    )
    akamai = make_model(LLMSettings(_env_file=None, **base))
    assert type(akamai).__name__ == "OpenAIModel"
    assert akamai.get_config()["params"]["max_tokens"] == 4096
    routed = make_model(LLMSettings(_env_file=None, bedrock_model_id="b", **base))
    assert type(routed).__name__ in {"ModelRouter", "OpenAIModel"}
    bedrock = make_model(LLMSettings(_env_file=None, llm_provider="bedrock", bedrock_model_id="b"))
    assert type(bedrock).__name__ == "BedrockModel"


def test_file_session_manager_and_mcp_client(tmp_path):
    pytest.importorskip("strands")
    from hm_agents_common.mcp import http_mcp_client, stdio_mcp_client
    from hm_agents_common.session import make_session_manager
    from hm_agents_common.settings import AgentSettings

    mgr = make_session_manager("s1", AgentSettings(_env_file=None, session_dir=str(tmp_path)))
    assert type(mgr).__name__ == "FileSessionManager"
    assert stdio_mcp_client("echo", ["hi"]) is not None
    assert http_mcp_client("http://localhost:1/mcp") is not None
