# Architecture

```
 Frontend (separate repo)
        │  HTTPS/JSON (CORS_ALLOW_ORIGINS)
        ▼
 ┌────────────────────────── project API  (projects/<name>/main.py, :81NN) ─────────────────────┐
 │ hm_api_common.create_app: /health /ready, request IDs, JSON errors, X-API-Key stub            │
 │                                                                                              │
 │  Strands agent(s) ── hm_agents_common.make_agent                                             │
 │     │  model: Akamai OpenAI-compatible endpoint ──(ModelRouter fallback)──► Amazon Bedrock    │
 │     │  hooks: RateLimitHook (60 rpm shared) · ApprovalHook (interrupts) · PolicyHook (Cedar)  │
 │     │  tools: predict ─────────────────────────────┐   settlement · storage · MCP servers     │
 │     │  sessions: file (dev) / Object Storage (prod)│   tracing: OpenTelemetry (optional)      │
 └─────┼──────────────────────────────────────────────┼──────────────────────────────────────────┘
       │                                              ▼
       │                           inference service (services/inference.py, :82NN, own container)
       │                           sklearn/torch model from ModelRegistry + LIME explanation
       ▼
 Postgres (+pgvector) · Valkey (optional) · Object Storage (S3 API) · Settlement adapter (mock → XRPL testnet / USDC on Arc)
```

## Why this shape
- **API and inference split**: the model is a fixed, deterministic tool. Agents reason; the model scores. Explanations (LIME) come from the model service, so the agent quotes evidence instead of inventing it.
- **One limiter per process**: every Akamai call (raw client or agent) acquires the same sliding-window limiter, and 429s back off. Run one API replica per team key.
- **Settlement behind an interface**: `mock` works today; swap `SETTLEMENT_ADAPTER=xrpl|arc` when the chain adapter is filled in. Idempotency keys are part of the contract.
- **Human approval as a first-class step**: Strands interrupts pause before money moves; the frontend shows the pending approval and resumes the run.

## Deploy targets (Akamai Cloud)
- **Fast path**: one Linode instance in a VPC running `docker compose --profile app`, fronted by a NodeBalancer, Cloud Firewall allowing SSH from admin CIDRs only.
- **K8s path**: LKE + `infra/k8s` kustomize overlay; the API Service of type LoadBalancer gets a NodeBalancer.
- Shared: Object Storage bucket (models, uploads, agent sessions), optional Managed Postgres in the VPC.

## Package map
| Package | Key entry points |
|---|---|
| `hm_core` | `HMSettings`, `AppSettings`, `configure_logging`, `AppError` subclasses |
| `hm_llm` | `make_openai_client`, `chat` (trim + fallback), `RateLimiter`, `retry_with_backoff`, `TokenBudget` |
| `hm_agents_common` | `model.make_agent`, `approval.ApprovalHook/PolicyHook/run_with_approvals`, `policy.PolicySet`, `structured.structured_call`, `tracing.setup_tracing`, `session.make_session_manager`, `mcp.*`, `testing.ScriptedModel` |
| `hm_ml_common` | `synthetic`, `metrics`, `registry.ModelRegistry`, `explain.TabularExplainer/TextExplainer`, `training.train_classifier` |
| `hm_settlement` | `SettlementAdapter`, `get_adapter`, `MockSettlementAdapter`, XRPL/Arc stubs |
| `hm_storage` | `ObjectStore`, `session_scope`, `enable_pgvector`, `get_redis` |
| `hm_api_common` | `create_app`, `require_api_key`, `run` |
