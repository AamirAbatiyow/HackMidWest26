# Add an agent (or multi-agent step) to a project

1. Put it in `projects/<name>/<name>/agents/` as a `build_<role>_agent(**kwargs)` using `hm_agents_common.model.make_agent` (never raw `Agent(model=OpenAIModel(...))`, which would bypass the 60 rpm limiter).
2. System prompt: role, what tools to use when, output format. Use `structured_output_model=<PydanticModel>` for anything the API returns.
3. Composition, in order of preference: one agent with more tools → agents-as-tools (`@tool` wrapping a specialist) → `GraphBuilder` (fixed flow) → `Swarm` (open handoffs).
4. Human approval via `ApprovalHook`; expose `pending_approvals(result)` from the API and resume with `approval_responses(...)`.
5. Test offline with `ScriptedModel`; count expected LLM calls per request and keep it low (each tool loop = 1 request).
