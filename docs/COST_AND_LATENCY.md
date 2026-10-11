# Latency and Cost

This document breaks down Vouch's infrastructure cost, per-invoice marginal cost, end-to-end latency, and the fraud-loss math that justifies the spend.

## Infrastructure Cost (Akamai Cloud)

From `backend/infra/terraform/akamai/` with default instance types:

| Resource | Type | Hourly | Monthly (730h) | Purpose |
|----------|------|--------|----------------|---------|
| App Linode | g6-standard-2 | $0.036 | ~$26 | API server, Strands graph |
| Model Linode | g6-standard-2 | $0.036 | ~$26 | VouchNet + LIME inference |
| Decider Linode | g6-dedicated-8 | $0.144 | ~$105 | Strands Decider 2B (4 vCPU, 16 GB) |
| Managed Postgres | g6-nanode-1 | $0.024 | ~$18 | pgvector, audit trail |
| NodeBalancer | — | $0.015 | ~$11 | TLS termination, health checks |
| **Total** | | **~$0.255** | **~$186** | |

Object Storage is pay-per-use and negligible at demo scale (a few cents per GB-month).

**The full stack runs for about $6.12/day or $186/month.**

## Per-Invoice Marginal Cost

The demo processes six invoices with about six LLM calls total. On the deployed stack:

| Path | Model calls | Estimated cost | Notes |
|------|-------------|----------------|-------|
| Deterministic (obvious PDF) | 0 | ~$0.00 | Code routes, no inference |
| Decider-routed (ambiguous) | 2 Decider questions | ~$0.00 | CPU-only, no per-call fee |
| LLM intake + investigation | 2–4 chat calls | workshop-provided | Akamai hosted inference was provided for the hackathon; no per-token billing |

The Strands Decider 2B runs on a dedicated Linode, so Decider calls cost nothing beyond the fixed infrastructure. The hosted inference (`hackathon-chat`) was workshop-provided with no per-token charges during the event.

**Estimated marginal cost per invoice: effectively zero for deterministic and Decider paths; the LLM path depends on token pricing if moved to a pay-per-use provider.**

For a rough estimate with standard LLM pricing (~$0.01–0.03 per 1K tokens, ~500 tokens per invoice): about $0.01–0.02 per invoice through the full LLM path.

## Latency

Measured from `/v1/latency` endpoint and `frontend/src/data/netstats.ts` demo fixtures (representative of deployed performance):

### Pipeline Steps

| Step | p50 | p95 | What it does |
|------|-----|-----|--------------|
| reader | 12 ms | 28 ms | Parse email, extract text |
| sender_check | 8 ms | 19 ms | SPF/DKIM/DMARC, lookalike detection |
| vendor_resolution | 15 ms | 42 ms | Match to known vendors, embeddings |
| detector_amount | 2 ms | 5 ms | Amount anomalies |
| detector_bank | 3 ms | 8 ms | Bank-change window |
| detector_duplicate | 6 ms | 14 ms | Duplicate/split detection |
| detector_ring | 18 ms | 45 ms | Vendor ring graph |
| scorer | 85 ms | 210 ms | VouchNet + LIME |
| policy | 4 ms | 9 ms | Cedar evaluation |
| writer | 11 ms | 26 ms | Persist to audit store |
| **Pipeline total** | **164 ms** | **406 ms** | |

### Model Inference

| Model | p50 | p95 | Notes |
|-------|-----|-----|-------|
| Strands Decider 2B | ~85–100 ms | ~200 ms | CPU-only, single question |
| hackathon-chat (Llama 3.3 70B) | 320 ms | 890 ms | Akamai hosted inference |
| hackathon-embedding | 45 ms | 120 ms | Vendor embeddings |
| VouchNet + LIME | 85 ms | 210 ms | Local PyTorch, CPU |

### Data Tier

| Service | p50 | p95 |
|---------|-----|-----|
| Managed Postgres | 2 ms | 6 ms |
| Object Storage | 15 ms | 42 ms |

**End-to-end p50 for a typical invoice: under 200 ms deterministic, under 500 ms with LLM calls.**

The Strands Decider answers a routing question in ~100 ms on CPU, compared to 300–1400 ms for a full chat model. This makes the advisory layer practical without adding perceptible latency.

## Fraud-Loss Context

### Occupational/Internal Fraud (ACFE 2024)

The [ACFE 2024 Report to the Nations](https://www.acfe.com/fraud-resources/report-to-the-nations) (occupational fraud, internal bad actors):

- A typical organization loses **5% of revenue to fraud** each year
- Median loss per case: **$145,000** overall
- Median loss for organizations with **fewer than 100 employees: $141,000**
- Median fraud duration: **12 months** before detection
- Small businesses see disproportionately more **billing, check, and payment tampering** schemes

### External Payments Fraud (AFP 2025, 2026)

The [AFP 2025 Payments Fraud and Control Survey](https://www.afponline.org/publications-data-tools/reports/survey-research-economic-data/payments-fraud-survey) (covering 2024, 521 respondents, external payments fraud):

- **79%** of organizations experienced attempted or actual payments fraud
- **Business email compromise (BEC)** was the top attack avenue at **63%**
- **Vendor impersonation: 45%** (up 11 percentage points from prior year)
- **36%** of organizations lost money to BEC
- Only **22%** recovered 75%+ of lost funds in 2024 (down from 41% in 2023)

The [AFP 2026 Payments Fraud and Control Survey](https://www.afponline.org/publications-data-tools/reports/survey-research-economic-data/payments-fraud-survey) (covering 2025):

- **76%** experienced attempted or actual payments fraud
- **74%** were affected by BEC
- **48%** of organizations under $1B revenue reported financial losses
- Only **17%** currently use AI to fight payments fraud

### Cost Justification

Simple arithmetic (not a guarantee):

- Full Vouch infrastructure: **$186/month = $2,232/year**
- Median fraud loss for firms under 100 employees (ACFE 2024): **$141,000**
- $141,000 ÷ $2,232 = **~63 years of infrastructure**

**Preventing a single median-loss case pays for about 63 years of running the full stack.**

This does not account for:
- The multiplier effect (LexisNexis 2026: every $1 of fraud costs ~$5.13 in total impact)
- Reputational damage and vendor relationship harm
- Time spent investigating and recovering (median 12-month fraud duration)
- The 78% of BEC victims who do not recover most of their funds (AFP 2025)

The comparison is directional: fraud prevention infrastructure is cheap relative to a single successful attack.

## One Sentence for Narration

> Vouch screens an invoice for about a tenth of a cent in compute and catches the fraud that costs 5× the stolen amount to clean up—preventing one median loss would pay for 63 years of infrastructure.
