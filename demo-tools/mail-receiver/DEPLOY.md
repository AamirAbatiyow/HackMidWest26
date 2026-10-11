# Deploying the mail receiver on a Linode inside the VPC

Nothing in this folder applies anything. `deploy/cloud-init.yaml` and `deploy/linode.tf.example`
are templates with `<PLACEHOLDER>` tokens; review them, fill the values, and run `terraform plan`
yourself (no credentials are stored in the repo).

## Topology

```
 Faris's laptop                       Linode VPC (us-ord) — backend/infra/terraform/akamai
 ┌──────────────────┐   SMTP 25/2525  ┌────────────────────────┐  HTTP (private)  ┌──────────────────┐
 │ invoice-creator  │ ──────────────▶ │ mail-receiver          │ ───────────────▶ │ Vouch API        │
 │ (web UI, :8300)  │  public IP      │ 10.0.1.20  (+1:1 NAT)  │  10.0.1.10:8101  │ POST /v1/intake  │
 └──────────────────┘                 │ :25 :2525 :8025        │  X-Vouch-Intake- │ (app Linode)     │
          │  HTTP fallback (if SMTP   └────────────────────────┘  Secret: …       └──────────────────┘
          └─ is blocked) → receiver /inbound, or straight to the backend intake
```

* The receiver joins the backend's **ingress-app subnet** (`10.0.1.0/24`; the app Linodes are
  `10.0.1.10` / `10.0.1.11`, API port `8101`). The backend's Cloud Firewall already accepts the
  API port from that subnet, so no backend-side firewall change is needed. It gets a public IPv4
  via the VPC interface's 1:1 NAT so the demo tool can reach it **by IP** — no domain or DNS is
  needed for the demo.
* The backend is reached over the VPC private address: `BACKEND_INTAKE_URL=http://10.0.1.10:8101/v1/intake`
  (`BACKEND_INTAKE_FORMAT=json`), or `…/v1/intake/eml` with `BACKEND_INTAKE_FORMAT=eml` (multipart
  `file` upload). The shared secret (`INTAKE_SHARED_SECRET`) is sent as `X-Vouch-Intake-Secret`
  on every POST. The backend does not validate that header yet; it protects the receiver's own
  `POST /inbound` and `POST /dead-letter/retry` in the meantime.

## Firewall (Linode Cloud Firewall + ufw on the host)

| Port | Protocol | Allowed from                         | Purpose                                   |
|------|----------|--------------------------------------|-------------------------------------------|
| 22   | TCP      | demo-tool IPs                        | SSH                                       |
| 25   | TCP      | demo-tool IPs, VPC subnet            | SMTP                                      |
| 2525 | TCP      | demo-tool IPs, VPC subnet            | SMTP alternate (when 25 is filtered)      |
| 8025 | TCP      | VPC subnet only                      | `/health`, `/recent`, `/inbound`, retries |

Everything else inbound is dropped; outbound is allowed (the receiver needs HTTP to the backend
and HTTPS to Object Storage if enabled).

## Akamai/Linode SMTP restrictions and the fallbacks

Akamai (Linode) restricts SMTP on new accounts: outbound ports 25/465/587 are blocked until the
account is reviewed, and some regions/providers filter inbound 25 as well. Treat port 25 as
"nice to have" for the hackathon:

1. **Port 2525** — the receiver listens on 25 *and* 2525; set `DEMO_SMTP_PORT=2525` in the
   invoice-creator. Nothing else changes (same recipient, same headers, same storage).
2. **HTTP fallback via the receiver** — `POST /inbound` on port 8025 with `Content-Type:
   message/rfc822` and the `X-Vouch-Intake-Secret` header (set `RECEIVER_INBOUND_URL` in the
   invoice-creator). The message goes through the exact same parse/store/forward pipeline,
   so the demo stays identical; only the transport differs. Open 8025 to the demo-tool IPs in
   that case.
3. **HTTP straight to the backend** — set `BACKEND_INTAKE_URL` in the invoice-creator; it POSTs
   the `.eml` (or the IntakeRequest JSON) directly. This bypasses the receiver, so use it only
   if the receiver host is unreachable.

To lift the SMTP block for real: open a Linode support ticket ("SMTP port restrictions") with the
Linode label and the intended use.

## Running it

```bash
# on the Linode (cloud-init does all of this)
git clone --depth 1 https://github.com/AamirAbatiyow/HackMidWest26.git /opt/vouch-mail/repo
cd /opt/vouch-mail/repo/demo-tools/mail-receiver
cp .env.example .env            # set BACKEND_INTAKE_URL, INTAKE_SHARED_SECRET, MAIL_DOMAIN
docker compose up -d --build
curl -s http://127.0.0.1:8025/health | jq .
```

With Terraform (`deploy/linode.tf.example`): the backend stack exports `vpc_id` (`terraform output
-raw vpc_id` in `backend/infra/terraform/akamai`); the ingress subnet id comes from
`linode-cli vpcs subnets-list <vpc_id>`. Pass `demo_tool_ips` (the laptop's public IP as `/32`),
`ssh_public_key`, `intake_shared_secret` and `git_branch`; `backend_vpc_ip` defaults to `10.0.1.10`.
Afterwards `terraform output mail_receiver_public_ip` is the value for `DEMO_SMTP_HOST`.

Binding port 25 as the container's non-root user works because `docker-compose.yml` sets
`net.ipv4.ip_unprivileged_port_start=0` for the container. If a port cannot be bound the
receiver logs an error and keeps serving the ports that did bind.

## Object Storage (optional)

Set `OBJ_ENDPOINT` (e.g. `https://us-ord-1.linodeobjects.com`), `OBJ_BUCKET`, `OBJ_ACCESS_KEY`,
`OBJ_SECRET_KEY`. Every received message directory (`message.eml`, `intake.json`, `meta.json`,
`attachments/*`) is mirrored to `s3://<bucket>/<OBJ_PREFIX><id>/…` in the background; the local
disk copy under `DATA_DIR` remains authoritative and mirroring failures are recorded in
`meta.json` without affecting delivery.

## DNS, if Faris has a domain (not required)

| Record | Name                     | Value                                              | Why                                        |
|--------|--------------------------|----------------------------------------------------|--------------------------------------------|
| A      | `mail.yourdomain.com`    | `<receiver public IP>`                             | hostname for the MX                        |
| MX     | `yourdomain.com`         | `10 mail.yourdomain.com.`                          | senders deliver `business@yourdomain.com`  |
| TXT    | `yourdomain.com`         | `v=spf1 ip4:<receiver public IP> -all`             | SPF — only matters if this host also sends |
| TXT    | `_dmarc.yourdomain.com`  | `v=DMARC1; p=none; rua=mailto:dmarc@yourdomain.com` | DMARC reporting for the domain             |
| PTR    | reverse DNS of the IP    | `mail.yourdomain.com` (set in Linode → Network)    | rDNS, expected by real senders             |

Then set `MAIL_DOMAIN=yourdomain.com` so `business@yourdomain.com` is accepted, and point the
invoice-creator at `DEMO_SMTP_HOST=mail.yourdomain.com`, `DEMO_MAIL_TO=business@yourdomain.com`.

**Without a domain** (the hackathon default): keep `MAIL_DOMAIN=vouch.local`, send straight to
the receiver's IP (`DEMO_SMTP_HOST=<ip>`, `DEMO_MAIL_TO=business@vouch.local`). The receiver
accepts the recipient by literal match, so no DNS is involved anywhere.

## What the receiver does *not* do (on purpose)

* It does **not** verify SPF/DKIM/DMARC. For the demo the `Authentication-Results` header is
  authored by the invoice-creator (labelled `demo-simulated`) and passed through verbatim. In
  production a verifying MTA (Postfix + OpenDKIM/policyd-spf, or an inbound gateway) in front
  of it would prepend its own `Authentication-Results`, which the backend already prefers
  (topmost header wins).
* It does **not** open, render or execute attachments. Bytes are allow-listed by extension and
  magic bytes, hashed, base64-encoded and stored with mode 0640.
* It does **not** relay. `RCPT TO` anything other than the configured mailbox is answered `550`.
