# AGENTS.md — rules for coding agents (and Faris at 4am)

Hackathon repo. Optimize for a working end-to-end demo by **Sun 8:00 AM CT**. Details live in `.cursor/rules/*.mdc`.

## Non-negotiables
- **No frontend here.** No HTML/JS/TS, templates, static sites or UI frameworks. The frontend is a separate repo calling our HTTP APIs.
- **Never commit secrets.** Real values go in `.env` (git-ignored). Add new variable *names* to `.env.example`. No keys in code, tests, tfvars or YAML.
- **Keep the demo path working.** Before and after each change: `make lint && make test`, and the demo flow in `docs/DEMO.md` still runs.
- **Smallest viable change.** No new frameworks, abstractions or packages unless the demo needs them. Prefer editing a project over generalizing into `packages/`.

## Layout and imports
- Shared code: `packages/<lib>/hm_<lib>/` (import `hm_core`, `hm_llm`, `hm_agents_common`, `hm_ml_common`, `hm_settlement`, `hm_storage`, `hm_api_common`).
- Concepts: `projects/<name>/<name>/` with `main.py` (API), `agents/`, `tools/`, `models/train.py`, `services/inference.py`; tests in `projects/<name>/tests/`.
- New concept: `make new-project name=<x> desc="..."`. Never copy-paste another project.
- Heavy deps are extras: `agents` (strands), `ml` (torch), `explain` (lime/sklearn), `chain` (xrpl/web3). Import them lazily inside functions in shared code; tests use `pytest.importorskip`.

## Python style
- Python 3.11+, type hints, pydantic models at API/tool boundaries, `ruff` (line 110) formats and lints.
- Config only through pydantic-settings classes (`hm_core.config.HMSettings` subclasses); no `os.environ[...]` scattered around.
- Raise `hm_core.errors.*` (`NotFoundError`, `ValidationFailedError`, `UpstreamError`, ...); `api_common` maps them to JSON.
- Use `uv` (`uv add --package <member> <dep>`), never pip.

## LLM budget (Akamai hosted inference)
- 60 requests/min per team key, 32k context, 4096 max output, tool calling + JSON schema, **no image input**.
- Always build models/agents via `hm_agents_common.model.make_agent` / `hm_llm.make_openai_client` (shared limiter + retry). Never construct raw clients.
- One agent turn can be several requests (tool loops). Keep tool outputs short; use `TokenBudget.trim` / sliding windows.
- Tests and rehearsals use `hm_agents_common.testing.ScriptedModel` — zero LLM calls.

## Strands conventions
- Start with one agent + tools; add Graph/Swarm/agents-as-tools only when the demo story needs it.
- Money-moving or irreversible tools go behind `ApprovalHook` (interrupts) and/or `PolicyHook` (Cedar-style forbid/permit).
- ML models are exposed as a fixed tool that calls the project's inference service over HTTP.
- Structured output: `structured_output_model=` / `structured_call(...)` with pydantic models.

## Done means
`make lint && make test` pass, `make run-<project>` serves `/health`, docs updated if behaviour changed (`docs/DECISIONS.md` for pivots).
