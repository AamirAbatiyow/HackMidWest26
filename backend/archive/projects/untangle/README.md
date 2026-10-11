# untangle

Business vs personal transaction classification with explanations a bookkeeper can trust.

Status: **skeleton** — health checks, wiring and placeholders only. Fill in `PLAN.md` first.

| Service | Command | Port |
|---|---|---|
| API (what the frontend calls) | `make run-untangle` | 8104 |
| Model inference (called by agents as a fixed tool) | `make serve-untangle` | 8204 |
| Train baseline model | `make train-untangle` | – |

Check: `curl localhost:8104/health` · API docs at `http://localhost:8104/docs`.

## Layout

```
untangle/
  main.py              FastAPI app (create_app from hm_api_common) + /v1 routes for the frontend
  config.py            settings, env prefix UNTANGLE_
  agents/__init__.py   build_agent(): Strands agent wiring (model, tools, approval hook)
  tools/__init__.py    agent tools; `predict` calls the inference service over HTTP
  models/train.py      training entrypoint -> artifacts/models/<name>/<version>/
  services/inference.py FastAPI inference service: /predict (+ LIME explanation)
tests/                 smoke tests (run by `make test`)
```

## Concept notes
- Transaction descriptions are text: `hm_ml_common.explain.TextExplainer` explains a text classifier word by word.
- Use the LLM only for ambiguous cases (low model confidence) to save requests; batch with structured output.
- Human review queue: low-confidence items go to a person via `ApprovalHook` or a plain API endpoint.

## TODO
- [ ] Define the demo moment in PLAN.md
- [ ] Replace synthetic placeholder data in `models/train.py`
- [ ] Write the system prompt + tools in `agents/` and `tools/`
- [ ] Add `/v1/...` endpoints the frontend needs (document request/response shapes here)
