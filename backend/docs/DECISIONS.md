# Decisions log

Newest first. One line of context, the decision, and what would make us revisit it.

| When (CT) | Decision | Why | Revisit if |
|---|---|---|---|
| Sun am | The API image ships the Tesseract binary (`tesseract-ocr` + `tesseract-ocr-eng`, also in the app Linode apt list); a missing engine is `down` in `/health` + `/v1/health` and leads the card's hold reason (`R_OCR_MISSING`) instead of "could not be read"; the OCR probe re-checks a negative every 15 s | on Akamai an emailed PNG came out as amount 0: `python:3.12-slim` has no tesseract and pytesseract alone is not OCR; PDFs never touched it | image size matters (use the pure-Python `ocr-rapid` extra instead) |
| Sat eve | Owner approval accepts only `approved: true` or an explicit approve word; anything else declines | interrupt responses are attacker-reachable input; type confusion must fail closed | — |
| Sat eve | Scorer chain: inference service → in-process model → labelled heuristic | demo must never die on a missing model or torch | heuristic ever shown on stage (retrain first) |
| Sat eve | XRPL: approved cards settle as one atomic `Batch` (tfAllOrNothing, ≤8 inner); amounts scaled by `XRPL_XRP_PER_USD` | one owner approval = one all-or-nothing transfer; faucet funds last | Batch amendment disabled on testnet (set `XRPL_USE_BATCH=false`) |
| Sat eve | vouch needs torch only to train/serve; base deps include Strands + xrpl-py | Strands graph is the product; torch stays opt-in (`--extra ml`, `INFERENCE_EXTRAS`) | image size matters |
| Sat eve | LLM never authors money: intake may only quote verbatim, numbers in LLM text must be kernel facts, policy forbids `amount_origin=llm` | irreversible payouts; hallucinated or injected amounts must be impossible, not unlikely | — |
| Sat eve | Strands `Graph` with deterministic `MultiAgentBase` nodes + 3 LLM roles; interrupt via `BeforeNodeCallEvent` | visible Strands use, ~6 LLM calls per demo, all with template fallbacks | — |
| Sat 3:25pm | **Concept pick: VOUCH** (payment trust layer for stablecoin vendor payouts) | FinTech + Strands + Akamai in one story | — |
| Sat (setup) | uv workspace: `packages/*` shared libs + `projects/*` concepts, one lockfile | switching concepts costs minutes; one `make test` covers all | build times hurt |
| Sat (setup) | Heavy stacks are opt-in groups (`ml`, `agents`, `chain`, `tf`); LIME+sklearn in default install | clean-machine install stays fast; LIME smoke test still runs | a concept needs torch at serve time |
| Sat (setup) | API and model inference are separate services; agents call the model as a fixed HTTP tool | deterministic scores + explanations; agent can't hallucinate numbers | latency matters more than separation |
| Sat (setup) | Rate limiting via shared in-process sliding window + Strands `BeforeModelCallEvent` hook | Akamai key is 60 rpm; Strands creates a new OpenAI client per request so transport injection isn't reliable | need >1 API replica (move limiter to Valkey) |
| Sat (setup) | Bedrock fallback through Strands `ModelRouter` + `FallbackStrategy` (provisional API) | free failover when both providers configured | router API changes / misbehaves |
| Sat (setup) | Settlement `mock` adapter is the default | demo works end-to-end before chain integration | — |
| Sat (setup) | Local S3 = SeaweedFS (MinIO no longer publishes Docker Hub images) | `docker pull minio/minio` is denied | — |
| Sat (setup) | Deploy fast path = single Linode + compose behind NodeBalancer; LKE optional | fewer moving parts at 3am | judges weight Kubernetes |