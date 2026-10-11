# Add an agent tool to a project

1. In `projects/<name>/<name>/tools/__init__.py`, add a plain typed function with a docstring that has an `Args:` section (Strands builds the tool schema from it). Return small JSON-serializable data.
2. Register it in `get_tools()`. If it moves money or is irreversible, add its name to `ApprovalHook(tools={...})` in `agents/__init__.py` and/or a `forbid` rule.
3. Use shared clients: settlement via `hm_settlement.get_adapter()`, storage via `hm_storage`, HTTP via `httpx` with a timeout.
4. Add a test in `projects/<name>/tests/` that drives the tool through `ScriptedModel([{"tool": "<fn>", "input": {...}}, "done"])`.
5. `make lint && make test`.
