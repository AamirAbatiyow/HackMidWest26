# PROJECTNAME

PROJECTDESCRIPTION

Status: **skeleton** — health checks, wiring and placeholders only. Fill in `PLAN.md` first.

| Service | Command | Port |
|---|---|---|
| API (what the frontend calls) | `make run-PROJECTNAME` | PROJECTPORT |
| Model inference (called by agents as a fixed tool) | `make serve-PROJECTNAME` | PROJECTINFERPORT |
| Train baseline model | `make train-PROJECTNAME` | – |

Check: `curl localhost:PROJECTPORT/health` · API docs at `http://localhost:PROJECTPORT/docs`.

## Layout

```
PROJECTNAME/
  main.py              FastAPI app (create_app from hm_api_common) + /v1 routes for the frontend
  config.py            settings, env prefix PROJECTENVPREFIX_
  agents/__init__.py   build_agent(): Strands agent wiring (model, tools, approval hook)
  tools/__init__.py    agent tools; `predict` calls the inference service over HTTP
  models/train.py      training entrypoint -> artifacts/models/<name>/<version>/
  services/inference.py FastAPI inference service: /predict (+ LIME explanation)
tests/                 smoke tests (run by `make test`)
```

## TODO
- [ ] Define the demo moment in PLAN.md
- [ ] Replace synthetic placeholder data in `models/train.py`
- [ ] Write the system prompt + tools in `agents/` and `tools/`
- [ ] Add `/v1/...` endpoints the frontend needs (document request/response shapes here)
