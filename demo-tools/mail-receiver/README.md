# Vouch mail receiver

Small inbound SMTP receiver (Python, [aiosmtpd](https://aiosmtpd.readthedocs.io/)) that accepts
invoices for `business@<MAIL_DOMAIN>`, stores them, parses them into the Vouch backend's intake
request and forwards them over the private network. Built to run as one Docker container on a
Linode inside the VPC; runs just as well on a laptop for the demo.

```
SMTP :25 / :2525 ──▶ recipient check ──▶ size + attachment allowlist ──▶ disk (+ S3 mirror)
HTTP :8025 /inbound ─┘                                                        │
                                                      queue ──▶ POST BACKEND_INTAKE_URL
                                                        │        (X-Vouch-Intake-Secret)
                                                        └── retry w/ backoff ──▶ dead-letter/
```

## Run

```bash
# Docker (production shape)
cp .env.example .env            # set BACKEND_INTAKE_URL, INTAKE_SHARED_SECRET
docker compose up -d --build
curl -s localhost:8025/health

# Bare Python (local demo / tests) — needs Python 3.12
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
SMTP_PORTS=2525 DATA_DIR=./data BACKEND_INTAKE_URL=http://127.0.0.1:8101/v1/intake \
  INTAKE_SHARED_SECRET=dev-secret python -m mail_receiver
```

With `uv`: `uv run --with-requirements requirements.txt python -m mail_receiver`.

## What it accepts and what it rejects

| Check                | Behaviour                                                                                  |
|----------------------|--------------------------------------------------------------------------------------------|
| Recipient            | only `MAIL_ACCEPT`@`MAIL_DOMAIN` (default `business@vouch.local`); others get `550 5.1.1`  |
| Message size         | `MAX_MESSAGE_BYTES` (15 MiB) advertised via `SIZE`; larger → `552`                         |
| Attachments          | allowlist `pdf, png, jpg, jpeg, xlsx, csv, txt` by extension **and** magic bytes; others dropped and recorded, message still forwarded |
| Attachment size/count| `MAX_ATTACHMENT_BYTES` (10 MiB), `MAX_ATTACHMENTS` (10)                                     |
| Attachment handling  | read, sha256, base64, write with mode 0640 under a sanitised filename; never opened/rendered |
| Headers              | kept verbatim, including every `Received` and `Authentication-Results` line               |

## Intake request it forwards

Exactly the backend's `IntakeRequest` (`vouch.models`), as JSON by default:

```json
{
  "headers": {"From": "...", "Authentication-Results": "...", "Received": "...\n..."},
  "body_text": "...", "body_html": "",
  "attachments": [{"filename": "RP-10517.pdf", "content_type": "application/pdf",
                   "data_b64": "...", "sha256": "...", "size": 44399}],
  "source": "email",
  "received_at": "2026-10-11T01:18:17.105758Z"
}
```

Request headers on the POST: `X-Vouch-Intake-Secret` (shared secret), `X-Vouch-Receiver-Message-Id`,
`X-Vouch-Envelope-From`. `submitted_by` defaults to `BACKEND_SUBMITTED_BY` (`ap-inbox`). Set
`BACKEND_INTAKE_FORMAT=eml` and point `BACKEND_INTAKE_URL` at `.../v1/intake/eml` to upload the raw
message instead (multipart form, field `file` = the `.eml`, plus `submitted_by`).

## HTTP API (port 8025 — keep it inside the VPC)

| Endpoint                     | Purpose                                                                 |
|------------------------------|-------------------------------------------------------------------------|
| `GET /health`                | status, queue depth, totals, last delivery result, public config         |
| `GET /recent`                | last 20 messages, **metadata only** (no bodies, no attachment payloads) |
| `POST /inbound`              | fallback transport when SMTP is blocked: body `message/rfc822` (or multipart field `file`), header `X-Vouch-Intake-Secret`, optional `X-Vouch-Envelope-From`, `X-Vouch-Rcpt-To` |
| `POST /dead-letter/retry`    | requeue every dead-lettered message (same secret)                       |

## Storage layout

```
DATA_DIR/
  received/<id>/message.eml        raw bytes exactly as received
  received/<id>/intake.json        what is POSTed to the backend
  received/<id>/meta.json          envelope, peer, raw Received/Authentication-Results, attachment verdicts, delivery status
  received/<id>/attachments/…      kept attachments (mode 0640)
  dead-letter/<id>.json            deliveries that exhausted DELIVERY_MAX_ATTEMPTS
```

## Configuration

All via environment variables; see [`.env.example`](.env.example) for the full list with defaults.
Key ones: `MAIL_DOMAIN`, `MAIL_ACCEPT`, `SMTP_PORTS`, `HTTP_PORT`, `MAX_MESSAGE_BYTES`,
`ALLOWED_EXTENSIONS`, `DATA_DIR`, `BACKEND_INTAKE_URL`, `BACKEND_INTAKE_FORMAT`,
`INTAKE_SHARED_SECRET`, `DELIVERY_MAX_ATTEMPTS`, `DELIVERY_BACKOFF_BASE_S`, `OBJ_*`.

## Deploying on Linode

See [DEPLOY.md](DEPLOY.md): VPC topology, firewall rules (25/2525 only from the demo tool's IPs
and the VPC, 8025 VPC-only), Akamai SMTP restrictions and the fallbacks, the cloud-init /
Terraform templates under `deploy/`, DNS records if a domain exists, and how the demo works
without any domain.

## Tests

```bash
pip install -r requirements.txt
pytest -q
```
