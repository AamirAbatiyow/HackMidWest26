# groundtruth

Photo-proof construction milestone payments: verify site evidence against milestones before releasing funds.

Status: **skeleton** — health checks, wiring and placeholders only. Fill in `PLAN.md` first.

| Service | Command | Port |
|---|---|---|
| API (what the frontend calls) | `make run-groundtruth` | 8102 |
| Model inference (called by agents as a fixed tool) | `make serve-groundtruth` | 8202 |
| Train baseline model | `make train-groundtruth` | – |

Check: `curl localhost:8102/health` · API docs at `http://localhost:8102/docs`.

## Layout

```
groundtruth/
  main.py              FastAPI app (create_app from hm_api_common) + /v1 routes for the frontend
  config.py            settings, env prefix GROUNDTRUTH_
  agents/__init__.py   build_agent(): Strands agent wiring (model, tools, approval hook)
  tools/__init__.py    agent tools; `predict` calls the inference service over HTTP
  models/train.py      training entrypoint -> artifacts/models/<name>/<version>/
  services/inference.py FastAPI inference service: /predict (+ LIME explanation)
tests/                 smoke tests (run by `make test`)
```

## Concept notes
- The Akamai endpoint has **no image input**: photo checks need our own vision model (torch, `make setup-ml`) in the inference service, or Bedrock multimodal as a fallback.
- Uploads: `ObjectStore().presigned_put_url(...)` lets the frontend/phone upload photos straight to Object Storage.
- Milestone money maps to `SettlementAdapter.hold()` / `release()` (escrow-style); keep a human approval before `release`.

## TODO
- [ ] Define the demo moment in PLAN.md
- [ ] Replace synthetic placeholder data in `models/train.py`
- [ ] Write the system prompt + tools in `agents/` and `tools/`
- [ ] Add `/v1/...` endpoints the frontend needs (document request/response shapes here)
