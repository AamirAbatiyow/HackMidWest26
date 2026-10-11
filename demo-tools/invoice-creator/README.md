# Vouch invoice creator (demo tool)

Operator app that builds **synthetic** vendor invoice emails and sends them into Vouch the same
way a real vendor would: as SMTP mail to `business@<domain>`, received by the
[mail receiver](../mail-receiver/) and forwarded to the backend's `POST /v1/intake`.

Everything it produces is fake and labelled as such (visible **DEMO / SYNTHETIC** badge, demo
footer on every invoice, simulated `Authentication-Results` marked as a simulation). No real
people, companies, bank accounts or tax ids appear anywhere.

```
invoice-creator :8300 ── SMTP ──▶ mail-receiver :25/:2525 ── HTTP ──▶ Vouch API :8101 /v1/intake
        │                              │
        │  fallbacks: POST receiver /inbound  ·  POST backend /v1/intake(/eml) directly  ·  download .eml
        └─ tracks each send through the receiver (/recent/{id}) to the backend result
```

## Run

```bash
cd demo-tools/invoice-creator
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python -m invoice_creator serve            # http://127.0.0.1:8300
```

With `uv`: `uv run --with-requirements requirements.txt python -m invoice_creator serve`.

Defaults talk to a receiver on `127.0.0.1:2525` (`business@vouch.local`). Settings come from the
environment or a `.env` file next to this README (never committed):

| Variable | Default | Meaning |
|----------|---------|---------|
| `DEMO_SMTP_HOST` / `DEMO_SMTP_PORT` | `127.0.0.1` / `2525` | mail receiver; in the VPC demo the receiver's public IP, port `2525` if `25` is filtered |
| `DEMO_MAIL_TO` | `business@vouch.local` | `RCPT TO` — must match the receiver's `MAIL_ACCEPT@MAIL_DOMAIN` |
| `RECEIVER_INBOUND_URL` | *(empty)* | enables the "HTTP → receiver /inbound" delivery, e.g. `http://127.0.0.1:8025/inbound` |
| `RECEIVER_API_URL` | derived | receiver `/health` + `/recent` base used for tracking (defaults to port 8025 on `DEMO_SMTP_HOST`) |
| `BACKEND_INTAKE_URL` / `BACKEND_INTAKE_FORMAT` | *(empty)* / `eml` | enables "HTTP → backend intake": `eml` → `http://127.0.0.1:8101/v1/intake/eml` (multipart `file`), `json` → `http://127.0.0.1:8101/v1/intake` |
| `INTAKE_SHARED_SECRET` | *(empty)* | sent as `X-Vouch-Intake-Secret` on the HTTP deliveries (same value as the receiver's) |
| `DEMO_AUTHSERV_ID` | `mx.vouch.local` | authserv-id written into the simulated `Authentication-Results` header |
| `DEMO_OWNER_NAME` / `DEMO_OWNER_ADDRESS` | Grand Avenue Trading LLC, KC | "Bill To" when a preset/invoice does not set its own |
| `DEMO_HOST` / `DEMO_PORT` / `DEMO_DATA_DIR` | `127.0.0.1` / `8300` / `./data` | web UI bind and where built `.eml`s + the send log live |

## Judge flow (about two minutes)

1. Start the backend (`make run-vouch` in `backend/`, port 8101), the receiver
   (`SMTP_PORTS=2525 BACKEND_INTAKE_URL=http://127.0.0.1:8101/v1/intake python -m mail_receiver`
   in `../mail-receiver`) and this app. The receiver pill in the header turns green.
2. Keep the default story **Heartland Provisions Co.** — its vendors are the backend's seeded
   vendor master, so every lane comes out as intended. Click a scenario, watch the live preview,
   optionally change format / sender identity / SPF-DKIM-DMARC outcome, press **Send to Vouch**.
3. Or press **Send all 6 scenarios** and read the send log while the backend's inbox fills up:

| # | Scenario | Preset | Format | Expected in Vouch |
|---|----------|--------|--------|-------------------|
| a | Legit vendor | Prairie Packaging Supply, $1,215, PO-48790 | PDF | `fast_pay` — verified vendor under the owner's $2,500 rule |
| b | Bank-detail swap / account takeover | Sonora Fresh Produce, $9,850, lookalike From + Reply-To, SPF softfail / DMARC fail, new HK IBAN, "URGENT" + prompt-injection note | body | `hold` — sender checks fail, unconfirmed bank change, injection flagged |
| c | Duplicate invoice | Midwest Facility Services, INV-2291A, $4,780 | XLSX | `hold` — duplicate of paid INV-2291 |
| d | Bank change confirmed by call-back | Rheinland Gewürze GmbH, EUR 8,240 | CSV | `standard` — payable in the Friday batch, not fast-pay |
| e | Fake vendor ring | Apex Global Trading LLC, $12,000, proton.me sender, ring bank account | PNG (OCR) | `hold` — bank account shared across vendors |
| f | Honest brand-new small vendor | Bao Lin Ceramics, $640 | PDF | `standard` — new is not suspicious, just not fast-pay yet |

The second story, **Grand Avenue Trading (original spec)**, holds the six scenarios from the brief
including the two-step duplicate (`midwest` → `midwest-resend`) and split-invoice
(`brightline-1` → `brightline-2`) flows. Those vendors are unknown to the real backend's master
file, so there they hold as "not on the master file"; use them with `../e2e/stub_backend.py` to
show the mail mechanics.

## What a send contains

* A multipart email: plain-text body (vendor, `Invoice No:`, `Total Due:`, `Due Date:`,
  `PO Number:`, bank line), plus the invoice as PDF, PNG, XLSX or CSV — or body-only.
  Labels match what the backend's deterministic extractor keys on. The PNG is laid out for Tesseract:
  1600 px wide with 300 dpi metadata, 38 px black-on-white text, every line word-wrapped inside the
  margins (long BEC notes are never clipped), and a slashed-zero font for identifiers so OCR does not
  read `US0…` as `USO…`. The backend needs the `tesseract-ocr` + `tesseract-ocr-eng` packages to read
  it (`/v1/health` → `ocr.state` must be `live`).
* Sender identity: legit or lookalike `From`, optional `Reply-To`, and a simulated
  `Authentication-Results: <DEMO_AUTHSERV_ID> (demo-simulated); spf=…; dkim=…; dmarc=…` header,
  and an `X-Vouch-Demo` marker header on every message. The receiver passes these headers through
  untouched.
* Every send is logged (`data/send-log.jsonl`, `GET /api/log`), the `.eml` is downloadable, and
  the log shows the receiver's delivery status for that message.

## CLI

```bash
python -m invoice_creator presets [--story heartland|reyes]
python -m invoice_creator send --preset sonora --format body --delivery smtp|receiver_http|backend|none
python -m invoice_creator send-all --story heartland --pause 2
python -m invoice_creator build --preset apex --format png --out /tmp/eml   # write the .eml only
```

## Tests

```bash
pip install -r requirements.txt && pytest -q      # presets (incl. alignment with the backend's vendor master), renderers, headers
ruff check . && ruff format --check .
```
