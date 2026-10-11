# vouch: plan

> Keep this to one screen. Update it when scope changes; log big pivots in docs/DECISIONS.md.

## One-liner
A payment trust layer for irreversible stablecoin payouts. Honest vendors get paid faster, bad actors get
held before money leaves, and nothing is ever auto-denied.

## The 30-second demo moment
Dana's Friday batch goes in: six invoices.

- Prairie is paid instantly on the fast-pay lane, and the testnet tx id appears.
- Sonora's "urgent, new bank account" email is HELD. Vouch says why in plain English (the bank changed
  without a call-back, plus an injection attempt) and gives the next step.
- The graph stops at an owner-approval interrupt. Dana approves.
- Rheinland (2/10 discount) and Bao Lin settle in **one atomic XRPL batch** with real tx hashes.

## Users and the problem
- **Who:** an owner-operator of a mid-size wholesaler. Dana Whitfield at Heartland Provisions, Kansas City:
  40 people, vendors in four countries.
- **Pain today:**
  - Stablecoin payouts are fast and cheap but irreversible. One BEC bank swap or fake vendor is a
    permanent loss.
  - Manual review slows every honest vendor down.
- **What changes:**
  - Deterministic checks and own models sort each invoice into fast pay, standard, or hold.
  - The owner approves one batch with clear reasons.
  - Holds come with a resolution path.

## Sponsor hooks (see docs/SPONSORS.md)
- **AWS Strands:**
  - a `Graph` mixing deterministic and LLM nodes;
  - structured output (Pydantic) for intake, investigators, and the explainer;
  - an owner-approval **interrupt** with resume;
  - a Cedar-style default-deny policy;
  - hooks for rate limiting, stats, and tracing;
  - read-only evidence tools;
  - tests with `ScriptedModel`.
- **Akamai:** hosted inference as the LLM provider (Bedrock fallback), a 60 rpm limiter, and the
  API + inference services deployable on Linode/LKE.
- **FinTech / Flex:** real AP semantics (payables, credits, discounts, cash forecast, batch settlement) on
  XRPL testnet.

## Data
- `vouch/synth.py`: a seeded synthetic payables world with bad-actor and honest-but-unusual archetypes
  and deliberate realism overlaps.
- No real data or PII.

## Model
- **Targets:** three risk classes (`ato_bec`, `insider`, `fake_vendor`), legitimacy, and an anomaly score.
- **Model:** VouchNet (embeddings, MLP trunk, heads, autoencoder) plus vendor-graph ring features.
  Trains in about 3 s on CPU.
- **Metric that matters:** the honest false-positive (hold) rate at system level, with the real policy.
  Currently 1.1%, with 94.9% of bad actors held. See [MODEL_CARD.md](MODEL_CARD.md).
- **Explanation:** LIME on the dominant head, shown on each card.

## Build order
1. [x] Data, kernel, policy, settlement (mock + XRPL batch), API, scripted demo
2. [x] Models + LIME + model card with held-out split
3. [x] Strands graph with interrupt, intake/investigators/explainer with provenance
4. [x] Red-team suite (18 attacks), ring detection
5. [ ] Live LLM run with the Akamai key; deploy to Akamai; rehearse docs/DEMO.md twice

## Cut list (if behind)
1. Live LLM in the demo (offline templates already read well).
2. LKE deploy (single Linode + compose).
3. XRPL live (mock receipts).

## Risks
- **Akamai key arrives late or is rate-limited.**
  - Offline mode is deterministic.
  - About 6 calls per demo run.
- **XRPL testnet faucet or network flaky.** Switch to `SETTLEMENT_ADAPTER=mock` and narrate the tx id
  from a previous run.
- **In-memory state.** Restart the API before the demo.
