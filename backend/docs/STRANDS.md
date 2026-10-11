# Strands Decider Integration

The [Strands Decider](https://github.com/strands-labs/strands-decider) is a small, fast
decision model for agentic AI workflows. Unlike an LLM, which generates arbitrary text, a
decision model picks between sets of options and rates things on a scale—faster than an
LLM, with calibrated confidence scores.

## What the Decider Does in Vouch

The Decider makes two routing decisions at intake time:

1. **Email format classification** — Is this a forwarded invoice email, a direct vendor
   email, a payment notification, or something else? The answer determines which parser
   path the email follows.

2. **Parser tool selection** — Should we use the PDF extractor, the structured-text parser,
   the image/OCR pipeline, or the spreadsheet reader? The Decider picks the right tool
   based on the email content and attachments.

These are *routing* decisions only. The Decider never sees payment amounts, vendor bank
details, or anything that could influence the approve/hold decision. That belongs to:

- **The kernel** (risk scoring, LIME explanations)
- **Cedar policy** (authorization rules)
- **The owner** (final approval or hold)

## Pydantic Wrapping

Decider responses are wrapped in Pydantic models for type safety:

```python
from pydantic import BaseModel

class DeciderChoice(BaseModel):
    choice: str
    confidence: float
    probabilities: dict[str, float]

class EmailFormatDecision(DeciderChoice):
    """Which email format is this? forwarded_invoice | direct_vendor | payment_notification | other"""
    pass

class ParserToolDecision(DeciderChoice):
    """Which parser tool? pdf | text | ocr | spreadsheet"""
    pass
```

## Fallback to hackathon-chat

When `DECIDER_URL` is unset or the Decider service is unreachable, the intake pipeline
falls back to the Akamai-hosted `hackathon-chat` LLM classifier. This is slower (300–1400
ms vs ~100 ms) and does not provide calibrated confidence scores, but it works without
deploying a separate service.

## Deterministic vs Model Split

| Decision type | Source | Notes |
|---------------|--------|-------|
| Email format | Decider model | Picks one of four categories |
| Parser tool | Decider model | Picks based on attachments and content |
| Risk score | Kernel (torch + LIME) | PyTorch model with explainability |
| Authorization | Cedar policy | Deterministic rules, no ML |
| Final decision | Owner | Human approval or hold |

The Decider handles the fast, rote decisions so the expensive LLM calls are reserved for
tasks that need them (vendor resolution, freeform explanations).

## CPU Hosting

The Decider runs on CPU—no GPU required. The 2B parameter model needs about 4.5 GB of RAM
for weights, plus headroom for inference. We deploy it on a 16 GB dedicated-CPU Linode
(`g6-dedicated-8`: 4 vCPU, 16 GB RAM) in the model subnet, alongside the risk model server.

### Infrastructure

- **Location**: Model subnet (`10.0.2.0/24`) in the us-ord VPC
- **Firewall**: Port 8099 open only from the app/ingress subnet (`10.0.1.0/24`)
- **No public interface**: Reaches the internet through the forward proxy on app Linode #1
- **Weights**: Pre-downloaded on first boot (~4.5 GB from Hugging Face)

### Local Development

```bash
# Run the Decider locally (downloads weights on first build)
make decider-local

# Output:
# DECIDER_URL=http://localhost:8099

# Health check
curl http://localhost:8099/health

# Test request
curl http://localhost:8099/v1/systemone \
  -H 'Content-Type: application/json' \
  -d '{
    "state": "Invoice from Acme Corp for $5,000",
    "questions": {
      "format": {"type": "choice", "instructions": "Email format?=forwarded_invoice,direct_vendor,payment_notification,other"}
    }
  }'
```

### API

The Decider exposes a single endpoint:

```
POST /v1/systemone
Content-Type: application/json

{
  "state": "<text to classify>",
  "questions": {
    "<question_id>": {
      "type": "choice" | "noul" | "score",
      "instructions": "<question>=<option1>,<option2>,..."
    }
  }
}
```

Response:

```json
{
  "format": {
    "answer": "forwarded_invoice",
    "confidence": 0.89,
    "probabilities": {
      "forwarded_invoice": 0.89,
      "direct_vendor": 0.07,
      "payment_notification": 0.03,
      "other": 0.01
    }
  }
}
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DECIDER_URL` | URL of the Decider service | (unset = fallback to LLM) |
| `DECIDER_MODEL` | Hugging Face model ID | `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610` |
| `DECIDER_PORT` | Port the Decider listens on | `8099` |

## References

- [strands-decider repository](https://github.com/strands-labs/strands-decider) (Apache-2.0)
- [Hugging Face weights](https://huggingface.co/StrandsAgents/strands-decider-2B-qwen3.5-v1-2610)
- [Strands Agents SDK](https://github.com/strands-agents/sdk-python)
