# Latency and Cost

This document breaks down Vouch's infrastructure cost, per-invoice marginal cost, latency instrumentation, and the fraud-loss math that justifies the spend.

## Infrastructure Cost (Akamai Cloud)

From `backend/infra/terraform/akamai/` with deployed instance types:

| Resource | Type | Hourly | Monthly (730h) | Purpose |
|----------|------|--------|----------------|---------|
| App Linode | g6-standard-2 | $0.036 | ~$26 | API server, Strands graph |
| Model Linode | g6-standard-2 | $0.036 | ~$26 | VouchNet + LIME inference |
| Decider Linode | g6-standard-6 | $0.144 | ~$105 | Strands Decider 2B (6 vCPU, 16 GB) |
| Managed Postgres | g6-nanode-1 | $0.024 | ~$18 | pgvector, audit trail |
| NodeBalancer | — | $0.015 | ~$11 | TLS termination, health checks |
| **Total** | | **~$0.255** | **~$186** | |

Object Storage is pay-per-use and negligible at demo scale (a few cents per GB-month).

**The full stack runs for about $6.12/day or $186/month.**

## Per-Invoice Marginal Cost

The demo processes six invoices with about six LLM calls total. On the deployed stack:

| Path | Model calls | Cost | Notes |
|------|-------------|------|-------|
| Deterministic (obvious PDF) | 0 | ~$0.00 | Code routes, no inference |
| Decider-routed (ambiguous) | 2 Decider questions | ~$0.00 | CPU-only, no per-call fee |
| LLM intake + investigation | 2–4 chat calls | workshop-provided | Akamai hosted inference was provided for the hackathon; no per-token billing during the event |

The Strands Decider 2B runs on a dedicated Linode, so Decider calls cost nothing beyond the fixed infrastructure. The hosted inference (`hackathon-chat`) was workshop-provided with no per-token charges.

**Marginal cost per invoice: effectively zero for deterministic and Decider paths. The LLM path would incur token costs on a pay-per-use provider; actual pricing depends on the provider and model.**

## Latency Instrumentation

Vouch instruments latency at multiple levels:

- **Per-node timing** in the Strands graph (`pipeline.py`): each `StageNode` records wall-clock milliseconds
- **Per-run waterfall** at `GET /v1/latency`: shows the last run's step-by-step breakdown
- **Rolling p50/p95** via `timing.py`: ring buffer per step, exposed at `/v1/latency`
- **Decider latency**: the Decider server reports `latency_ms` in each response; the client records it
- **Frontend Network page**: visualizes tier RTT, pipeline waterfall, and inference latency

### Local Measurements

Running the six-invoice demo locally (offline LLM mode, CPU-only, 2026-10-11):

| Node | p50 | p95 | Notes |
|------|-----|-----|-------|
| intake | 1 ms | 11 ms | Parse, extract |
| resolve | 4 ms | 6 ms | Vendor matching |
| sender | 2 ms | 2 ms | SPF/DKIM checks |
| kernel | 1 ms | 2 ms | Amount/duplicate/split detection |
| score | 1,245 ms | 3,158 ms | VouchNet + LIME (cold-start overhead) |
| investigate | 0 ms | 1 ms | Skipped in offline mode |
| policy | 0 ms | 0 ms | Cedar evaluation |
| funding | 0 ms | 0 ms | Funding plan |
| explain | 0 ms | 0 ms | Skipped in offline mode |
| fast_pay | 0 ms | 6 ms | Settlement routing |

*Measured locally on CPU, 3 runs (18 invoices total). The `score` node dominates due to PyTorch model loading and LIME explanation generation; this would be faster on GPU or with a warm model server.*

### Deployed Latency

The deployed stack has `/v1/latency` instrumented but no production traffic yet. When traffic flows, the endpoint reports rolling p50/p95 for each pipeline step, inference tier, Postgres, and Object Storage.

## Fraud-Loss Context

### Occupational/Internal Fraud (ACFE 2024)

The [ACFE 2024 Report to the Nations](https://www.acfe.com/-/media/files/acfe/pdfs/rttn/2024/2024-report-to-the-nations.pdf) covers occupational fraud (internal bad actors):

- A typical organization loses **5% of revenue to fraud** each year
- Median loss per case: **$145,000** overall
- Median loss for organizations with **fewer than 100 employees: $141,000**
- Median fraud duration: **12 months** before detection
- Small businesses see disproportionately more **billing, check, and payment tampering** schemes

### External Payments Fraud (AFP 2025, 2026)

The [AFP 2025 Payments Fraud and Control Survey](https://www.financialprofessionals.org/about/learn-more/press-releases/Details/survey-79-percent-of-organizations-were-victims-of-attempted-or-actual-payments-fraud-activity-in-2024) (covering 2024, 521 respondents) covers external payments fraud:

- **79%** of organizations experienced attempted or actual payments fraud
- **Business email compromise (BEC)** was the top attack avenue at **63%**
- **Vendor impersonation: 45%** (up 11 percentage points from prior year)
- **36%** of organizations lost money to BEC
- Only **22%** of organizations recovered 75%+ of lost funds in 2024 (down from 41% in 2023)

The [AFP 2026 Payments Fraud and Control Survey](https://www.financialprofessionals.org/about/learn-more/press-releases/Details/over-75-percent-of-us-firms-experienced-payments-fraud-in-2025-while-ai-adoption-for-fraud-mitigation-lags) (covering 2025):

- **76%** experienced attempted or actual payments fraud
- **74%** were affected by BEC
- **48%** of organizations under $1B revenue reported financial losses
- Only **17%** currently use AI to fight payments fraud

### Cost Justification

Simple arithmetic (not a guarantee of outcomes):

- Full Vouch infrastructure: **$186/month = $2,232/year**
- Median fraud loss for firms under 100 employees (ACFE 2024): **$141,000**
- $141,000 ÷ $2,232 = **~63 years of infrastructure**

**Preventing a single median-loss case pays for about 63 years of running the full stack.**

This does not account for:
- The multiplier effect (LexisNexis 2026: every $1 of fraud costs ~$5.13 in total impact, already cited in the main README)
- Reputational damage and vendor relationship harm
- Time spent investigating and recovering (median 12-month fraud duration per ACFE)

The comparison is directional: fraud prevention infrastructure is cheap relative to a single successful attack.

## One Sentence for Narration

> The full stack runs for about $186/month—preventing one median $141,000 small-business fraud case (ACFE 2024) would pay for over 60 years of infrastructure.
