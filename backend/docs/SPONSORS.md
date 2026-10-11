# Sponsor challenges — what each wants to see

Source: hackmidwest.com challenge text (fetched Sat Oct 10, 2026). Confirm details at kickoff / sponsor tables.
Overall judging (all teams, 0–10 each): value/impact/usefulness · innovative/unique · realness/completeness. Code quality is not judged; a working MVP is.

## Best FinTech App — $2,500 (the Flex challenge; TODO: confirm sponsor + any extra criteria at the Flex table)
- Criteria: *Does the project leverage FinTech? Is it unique/innovative or use FinTech creatively?*
- Show: real money-movement semantics (payables, receivables, settlement, risk), not just a chatbot about finance.
- Our hooks: settlement adapter (mock → XRPL testnet / USDC on Arc with explorer links), fraud/risk model with explanations, human approval before payout, audit trail.
- Ask Flex: which workflows they care about (AP/AR, cash flow, credit?), whether a testnet settlement impresses or distracts.

## Best Use of Strands Agents SDK (AWS) — $2,500
- Criteria: *Does the project integrate Strands Agents SDK? Unique/innovative or creative use?* Framed as "production-ready agents that reason, use tools, access data, and execute actions".
- Show visibly in the demo: tools (our ML model as a fixed tool), **interrupts** for human approval, policy checks blocking an action with a reason, structured output, and if it fits the story multi-agent (Graph / Swarm / agents-as-tools), MCP tools, A2A, OpenTelemetry traces, session persistence.
- Production-ready signals: retries/backoff, rate limiting, sessions in Object Storage, tracing, tests with `ScriptedModel`.
- Last year (2025): 27 Strands submissions, so be specific about *which* Strands features you used and why.

## Akamai Cloud — $2,500
- Challenge: a working AI-powered app on Akamai Cloud that solves a real problem and **goes beyond a basic chatbot**. $300 credits, hosted inference provided (BYOI allowed).
- Criteria (4): 1) Impact & usefulness 2) **Powered by Akamai**: Akamai Cloud resources and/or AI inference used 3) Technical execution: does it work, is it stable 4) Creativity & innovation.
- Show: hosted inference powering the agent; deployed on Linode/LKE (public NodeBalancer URL in the demo); Object Storage for models/uploads/sessions; Managed Postgres; VPC + Cloud Firewall. Say the resource list out loud.
- Endpoint limits: 60 req/min per team key, 32k context, 4096 max output, tools + JSON schema, no image input.
- Resources: Akamai "HackMidwest x Akamai Cloud Starter Kit" GitHub repo, Discord "Edge Case".

## Other challenges seen (not targeted by default)
- DevRev ($2,500): reusable skill / MCP connector in DevRev Computer on their Enterprise-Bench dataset.
- USDA AI challenge: weather-driven facility closure decisions using live NWS data (non-cash prizes).

## What Vouch shows for each challenge

Concept: VouchEngine, a payment trust layer. Details are in `projects/vouch/README.md`.

### Best FinTech (Flex)
- Real accounts-payable semantics:
  - integer-cents kernel;
  - credit notes netted against invoices;
  - 2/10 early-pay discounts;
  - a cash forecast with a pay-now or schedule recommendation;
  - duplicate and split-invoice controls under a clerk approval limit;
  - single, batch, and fast-pay limits.
- Settlement on the **XRPL testnet**:
  - Approved cards go out as one atomic `Batch` (all-or-nothing).
  - Fast-pay cards go out as single payments.
  - Tx hashes and explorer links show on the card.
  - Idempotency keys travel in the memo, so a replayed invoice never pays twice.
- Fraud classes a CFO recognizes: ATO/BEC bank swaps, insider abuse, fake-vendor rings.
- Honest-but-unusual vendors are measured. The model card reports the honest hold (false-positive) rate,
  currently 1.1%.
- A hold is never a denial. Every hold has a resolution path: call-back to the number on file, owner
  review, or a vendor appeal.

### Strands Agents SDK
- **Graph:** a Strands `Graph` of 9 nodes that mixes deterministic `MultiAgentBase` nodes (kernel, score,
  policy, funding, fast pay, settle) with LLM agents:
  - intake;
  - per-class investigators;
  - the explainer.
- **Structured output:** Pydantic models (`IntakeExtraction`, `InvestigationReport`, `Explanations`).
  Intake may only quote the source verbatim.
- **Interrupts:** an owner-approval interrupt from a `BeforeNodeCallEvent` hook before `settle`. The graph
  stops `INTERRUPTED` and resumes with the owner's response. Ambiguous responses decline.
- **Policy:** a Cedar-style default-deny `PolicySet`. Forbid rules cover unresolved high risk, unconfirmed
  bank changes, over-limit single or batch totals, LLM-originated or missing amounts, duplicates, splits,
  rings, and injection. Settle re-checks it per card and per batch.
- **Tools:** read-only evidence tools for the investigators. There is no payment tool, so a model that
  calls `send_payment` is rejected by the registry.
- **Hooks:**
  - the 60 rpm rate limiter (`BeforeModelCallEvent`);
  - latency and token stats (`/v1/netz`);
  - OpenTelemetry via `StrandsTelemetry`.
- **Tests:** `ScriptedModel` drives the end-to-end happy and attack paths plus the 18-attack red-team suite.
- **Few calls:** about 6 LLM calls for the 6-invoice demo, all with deterministic fallbacks.

### Akamai Cloud
- **Inference:** Akamai hosted inference is the LLM provider. Bedrock is the fallback with
  `LLM_PROVIDER=auto`. The shared limiter respects the 60 req/min key.
- **Hosting:** API and model inference are separate services, deployable on Linode (compose) or LKE with
  `infra/scripts/deploy_akamai.sh`. For vouch, set `INFERENCE_EXTRAS="--extra explain --extra ml"`
  for torch.
- **Storage:** model artifacts live in the local registry under `artifacts/models`, mounted into the
  containers. Syncing them to Akamai Object Storage through `hm_storage` is not wired for vouch yet.
- **Beyond a chatbot:** our own PyTorch models, LIME, ring detection, and irreversible money movement.
  The LLM only reads and rephrases, and a provenance check rejects any number it invents.

## Stacking plan
One project can enter several challenges. Target: FinTech + Strands + Akamai with one story; mention all three in the last 15 seconds of the pitch.
