# vouch: a payment trust layer for irreversible payouts

Heartland Provisions, a Kansas City food wholesaler, pays vendors in four countries with stablecoin payouts.
They settle in seconds and cost almost nothing, but **they cannot be pulled back**. Vouch sits between
"an invoice arrived" and "money left" and decides what is safe to send:

- **Honest vendors get paid faster.** Verified small vendors go through a fast-pay lane. Everyone else gets
  a pay-now or schedule recommendation from a deterministic cash and discount planner.
- **Bad actors get stopped before an irreversible payout.** This covers account takeover / BEC bank swaps,
  insider duplicates and split invoices, and fake-vendor rings.
- **Nothing is ever auto-denied.** A risky card goes on HOLD with a plain-English reason and a next step:
  confirm the bank change by calling the number on file, owner review, or a vendor appeal.

Backend only. The frontend lives in a separate repo and calls this API (CORS is set with `CORS_ALLOW_ORIGINS`).

## Run it

```bash
make setup-all            # base + torch (CPU) + Strands + xrpl-py
make train-vouch       # ~3 s on CPU -> artifacts/models/vouch-risk/<version>/ + MODEL_CARD.md
make dev-vouch         # inference :8201 + API :8101 (or run serve-vouch / run-vouch in two shells)

curl -X POST 'localhost:8101/v1/demo/seed'          # scripted 6-invoice scenario, stops at owner approval
curl localhost:8101/v1/cards | jq '.[] | {id, vendor, lane, status, risk_class, legitimacy, explanation}'
curl -X POST localhost:8101/v1/runs/<run.id>/approve -H 'content-type: application/json' -d '{"approved": true}'
```

- OpenAPI docs: `http://localhost:8101/docs`.
- No servers needed: `make demo-vouch` runs the same scenario in-process and prints the cards.
- `make redteam-vouch` runs the attack suite.
- See [`docs/DEMO.md`](../../docs/DEMO.md) for the 3-minute live script.

**Degrades gracefully.** Every heavy piece has a fallback, so `make setup && make run-vouch` works on a
clean machine:

| Missing | What happens |
|---|---|
| Inference service | Vouch scores in-process from the trained model. |
| Trained model or torch | A labelled `heuristic-fallback` scorer is used. |
| LLM key | Template text built from kernel facts replaces the LLM output. |
| XRPL wallet | The mock ledger is used. |

`GET /v1/info` reports which scorer, LLM mode, and settlement adapter are active.

### XRPL testnet (real tx ids)
```bash
make xrpl-wallets         # funds two faucet wallets, writes SETTLEMENT_ADAPTER=xrpl + seed + destination into .env
```
Restart the API afterwards.

- Approved cards settle as **one atomic XRPL `Batch`** (all-or-nothing, up to 8 payments per batch).
- Fast-pay cards settle as single payments.
- Each card's `receipt` shows `tx_id`, `batch_tx_id`, and an explorer URL.
- Amounts are scaled for the faucet with `XRPL_XRP_PER_USD=0.0001`, so $8,240.00 is paid as 0.824 XRP.
- The memo carries an idempotency key, so a replayed invoice never pays twice.

### Live LLM (Akamai inference, Bedrock fallback)
Set `AKAMAI_INFERENCE_BASE_URL`, `AKAMAI_INFERENCE_API_KEY`, and `AKAMAI_INFERENCE_MODEL` in `.env`. You can
also set `BEDROCK_MODEL_ID` plus AWS credentials; with both configured, `LLM_PROVIDER=auto` falls back to
Bedrock.

- `VOUCH_LLM_MODE=offline` forces templates.
- The demo makes about 6 LLM calls in total, and the shared 60 rpm limiter is attached as a Strands hook.
- `GET /v1/netz` shows LLM calls, tokens, p50/p95 latency, per-node timings, and the provider.

## How a payment moves (Strands `Graph`)

```
intake ─▶ kernel ─▶ score ─▶ investigate ─▶ policy ─▶ funding ─▶ explain ─▶ fast_pay ─▶ [owner interrupt] ─▶ settle
 (LLM)    (det.)   (model)      (LLM)        (det.)    (det.)     (LLM)      (det.)                          (det.)
```

| Node | What it does |
|---|---|
| **intake** | Strands agent with structured output (`IntakeExtraction`). Runs only for raw or PDF text. The LLM may only *quote* the source: each quote must appear verbatim in the invoice text and must agree with the deterministic regex parser, otherwise it is discarded. An amount found only by the LLM is marked `amount_origin=llm`, and policy blocks paying it. Instructions aimed at the payment system are captured as `suspicious_instructions`, never obeyed. |
| **kernel** | `kernel.py`, integer cents only. Strict money parsing (rejects `$9,9OO.00` homoglyphs and sub-cent amounts), duplicate and split detection, bank-change windows, credit-note allocation, line-item reconciliation, batch totals. |
| **score** | Own PyTorch model, `VouchNet`. Entity embeddings, an autoencoder anomaly score, per-class heads (`ato_bec`, `insider`, `fake_vendor`), a legitimacy head, and vendor-graph ring features. Served by the inference service with LIME on the dominant head. See [`MODEL_CARD.md`](MODEL_CARD.md). |
| **investigate** | One investigator per flagged card (ATO/BEC, insider, or fake-vendor prompt). Uses read-only evidence tools: `vendor_profile`, `payment_history`, `bank_change_log`, `linked_vendors`. Capped at 8 calls per run, and it has no payment tool. Its text must pass the provenance check, otherwise a template is used. |
| **policy** | Cedar-style **default-deny** `PolicySet`. Forbid rules: unknown vendor, amount not from the kernel (LLM or missing), unconfirmed bank change, over the single or batch limit, duplicate, split, shared bank or tax id (ring), prompt injection, line items that don't add up, owner hold, unresolved high risk. Fast pay requires legitimacy ≥ 0.85, risk < 0.30, amount ≤ $2,500, a verified vendor, and no flags. |
| **funding** | Deterministic recommender over a cash-forecast stub. Order: fast pay, then open early-pay discounts (for example 2/10), then cards due within 2 days, then everything else scheduled for the day before its due date. Shortfalls are reported. |
| **explain** | One LLM call per 8 cards. It *rephrases* a fact sheet; every number in its output must be a kernel or model fact (`provenance.py`). Text that claims "paid" before settlement is rejected. If either check fails, the deterministic template is used. |
| **owner approval** | A `BeforeNodeCallEvent` hook raises a Strands **interrupt** before `settle`. The graph stops `INTERRUPTED` and resumes on `POST /v1/runs/{id}/approve`. Only `approved: true` (or an explicit approve word) counts; anything ambiguous declines. |
| **settle** | Re-checks policy per card and for the whole batch at settle time, then pays through `hm_settlement` (XRPL testnet, mock, or the Arc stub). |

Hooks on every agent:

- the rate limiter;
- a stats/tracing hook (model latency and tokens);
- OpenTelemetry spans for agents, model calls, and tools: set `OTEL_EXPORTER_OTLP_ENDPOINT` or `OTEL_CONSOLE_EXPORTER=true`.

## API (`/v1`)

**Submit**

| Method | Path | What it does |
|---|---|---|
| POST | `/invoices` | JSON invoices (`invoices: [...]`, `wait`). Each item may carry `text` (PDF text), `amount` as a string, or `amount_cents`. |
| POST | `/invoices/text` | One raw invoice text. |
| POST | `/demo/seed` | Vendor master (250 synthetic vendors plus 6 story vendors) and the 6-invoice scenario; `?run=false` loads without running. |

**Runs**

| Method | Path | What it does |
|---|---|---|
| GET | `/runs`, `/runs/{id}` | Status (`running`, `awaiting_approval`, `completed`, `failed`), pending approval, lanes, settlements. |
| GET | `/runs/{id}/events?after=`, `/runs/{id}/stream` | Node-by-node events by polling, or as SSE. |
| POST | `/runs/{id}/approve` | Resume the interrupt: `{"approved": true, "card_ids": [...]}`. |
| POST | `/runs/{id}/settle` | Batch-settle any READY cards later. |

**Cards**

| Method | Path | What it does |
|---|---|---|
| GET | `/cards?run_id&lane&status` | Card summaries: lane, status, risk class, risk, legitimacy, anomaly, LIME, policy reasons and required actions, funding, explanation, tx. |
| GET | `/cards/{id}` | The full `PaymentCard`: invoice, vendor, kernel checks and flags, features, all scores (incl. ring score), investigation, policy, funding, fact sheet, receipt, timeline. |
| POST | `/cards/{id}/approve` | Pay one card. |
| POST | `/cards/{id}/hold`, `/cards/{id}/release-hold` | Place or release a manual hold. |
| POST | `/cards/{id}/confirm-bank` | `phone_called` must be the number already on file. |
| POST | `/cards/{id}/resolve`, `/cards/{id}/override-limit` | Owner resolves a flag or overrides a limit. |
| POST | `/cards/{id}/appeal` | Vendor appeal. |

**Other**

| Method | Path | What it does |
|---|---|---|
| GET | `/vendors`, `/vendors/{id}`; PUT `/vendors/{id}` | Vendor master, including linked vendors (ring graph). |
| GET | `/cash` | Cash forecast and pay-now / schedule recommendations. |
| GET | `/netz` (alias `/stats`) | LLM calls, tokens, latency, node timings, provider, rate-limit headroom. |
| GET | `/redteam`; POST `/redteam/run` | Adversarial suite results (18 attacks). |
| GET | `/model`, `/info` | Model metadata, held-out metrics, active scorer, LLM mode, adapter. |

Inference service (`:8201`): `POST /score` (batch, ModelScores + LIME), `GET /model`, `/ready`.

## Data and model
- `synth.py` generates a seeded payables world. Honest archetypes: regular, new-small, confirmed bank
  change, seasonal spike, shared business-park address. Bad actors: ATO/BEC (invoice bank swap,
  vendor-master change), insider (duplicate, split, creep, no PO, by two specific clerks), and fake vendors
  (rings sharing bank, tax id, phone, or address, plus "careful" fakes). Realism overlaps are deliberate:
  honest vendors write "urgent" and use VOIP and billing platforms, and some attackers are quiet.
- `dataset.py` builds training rows through **the same kernel, graph, and feature code used at serving
  time**.
- Held-out test is a separate world (seed 99) with unseen vendors and rings. Current numbers:

| Metric | Value |
|---|---|
| Per-class precision/recall | ≥ 0.93 |
| Bad-actor invoices held | 94.9% |
| Honest invoices held (false-positive rate) | 1.1% |

See [`MODEL_CARD.md`](MODEL_CARD.md) for the caveats.

## Tests (`make test`)
- **Kernel:** money parsing, homoglyphs, duplicates and splits, credits.
- **Provenance and policy:** default-deny, fast-pay gates, funding order.
- **Synthetic data and features:** determinism, graph ring detection.
- **End to end with a scripted LLM** (Strands `ScriptedModel`): the happy path, the attack path, resolving
  a hold then settling, decline, offline mode, and ambiguous approvals.
- **Red-team suite:** all 18 attacks must be blocked.
- **API flow.**
- **Model training and inference with LIME** (skipped without torch).

## Layout
```
vouch/
  config.py          VOUCH_* settings (limits in cents, scorer/LLM mode, owner/business names)
  domain.py          Vendor, Invoice, ModelScores, PolicyOutcome, Resolution, enums
  kernel.py          integer-cents money kernel, text parser, duplicate/split/bank checks, FactSheet
  provenance.py      number extraction + "every number must be a known fact" check
  identity.py        tax-id checksum, VOIP prefixes, virtual addresses (stand-ins for real lookups)
  synth.py           seeded synthetic world with bad-actor and honest-but-unusual archetypes
  graph_features.py  vendor attribute graph, components, message passing (ring signal)
  features.py        feature vector shared by training and serving
  dataset.py         rows for training/eval
  models/net.py      VouchNet (embeddings + trunk + heads + autoencoder)
  models/train.py    training, held-out evaluation with the real policy, MODEL_CARD.md
  scorer.py          http -> local -> heuristic scorers, LIME
  services/inference.py  model inference service
  policy.py          Cedar-style default-deny rules
  funding.py         cash forecast + pay-now/schedule recommender
  llm.py             LLM runtime (live/offline/scripted), stats hook, rate-limit hook
  agents/            Pydantic output models + prompts (intake, investigators, explainer)
  tools/             read-only evidence tools for investigators
  cards.py           PaymentCard (what the frontend renders)
  service.py         stages, resolutions, settlement
  pipeline.py        Strands Graph, owner-approval interrupt, resume
  demo.py            Dana's 6-invoice story; `python -m vouch.demo`
  redteam.py         adversarial suite; `python -m vouch.redteam`
  main.py            FastAPI API
```

## Stubs and limits
- The API state is in memory. Restart the API to reset the demo; settlement idempotency is per process.
- Identity checks (tax id checksum, VOIP prefixes, virtual addresses) stand in for TIN-match,
  carrier-lookup, and address-verification APIs.
- The cash forecast is a fixed stub (opening balance, receivables, committed outflows).
- The Arc (USDC) adapter is an optional stub; XRPL testnet is the working chain path.
- Synthetic data only; see the model card.
