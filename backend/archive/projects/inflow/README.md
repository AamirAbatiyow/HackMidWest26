# inflow

Negotiating agents for receivables: agents propose and negotiate payment terms with payers within policy limits.

Status: **skeleton** — health checks, wiring and placeholders only. Fill in `PLAN.md` first.

| Service | Command | Port |
|---|---|---|
| API (what the frontend calls) | `make run-inflow` | 8103 |
| Model inference (called by agents as a fixed tool) | `make serve-inflow` | 8203 |
| Train baseline model | `make train-inflow` | – |

Check: `curl localhost:8103/health` · API docs at `http://localhost:8103/docs`.

## Layout

```
inflow/
  main.py              FastAPI app (create_app from hm_api_common) + /v1 routes for the frontend
  config.py            settings, env prefix INFLOW_
  agents/__init__.py   build_agent(): Strands agent wiring (model, tools, approval hook)
  tools/__init__.py    agent tools; `predict` calls the inference service over HTTP
  models/train.py      training entrypoint -> artifacts/models/<name>/<version>/
  services/inference.py FastAPI inference service: /predict (+ LIME explanation)
tests/                 smoke tests (run by `make test`)
```

## Concept notes
- Two-sided negotiation fits a Strands `Swarm` or agents-as-tools; A2A (`a2a` extra) if each side runs as its own service.
- Negotiation bounds (max discount, min installment) belong in a `PolicySet`, so out-of-policy offers are blocked with a visible reason.
- Every negotiation turn costs LLM requests: cap rounds and rehearse with `ScriptedModel` to stay under 60 rpm.

## TODO
- [ ] Define the demo moment in PLAN.md
- [ ] Replace synthetic placeholder data in `models/train.py`
- [ ] Write the system prompt + tools in `agents/` and `tools/`
- [ ] Add `/v1/...` endpoints the frontend needs (document request/response shapes here)
