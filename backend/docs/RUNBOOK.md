# Runbook

## 0. First time on a machine
```bash
infra/scripts/bootstrap.sh all      # installs uv if missing, deps (+torch CPU, strands, chain SDKs), .env, pre-commit
# edit .env: AKAMAI_INFERENCE_BASE_URL / _API_KEY / _MODEL (from kickoff), CORS_ALLOW_ORIGINS (frontend origin)
make lint && make test
```
`make setup` = base only (fast). `setup-ml`, `setup-agents`, `setup-all` add stacks. Each is an exact sync, so the last one wins.

## 1. Run one project locally (no Docker)
```bash
make train-vouch     # writes artifacts/models/vouch-baseline/<version>/
make dev-vouch       # API :8101 + inference :8201 together (or run-/serve- in two terminals)
make smoke project=vouch
```
API docs: `http://localhost:8101/docs`. The frontend points at `http://localhost:8101`.

## 2. Local backing services (Docker)
```bash
make up                         # postgres+pgvector :5432, valkey :6379, S3-compatible :9000
make up project=vouch        # + vouch API :8100 and inference :8200 in containers
make logs / make down
```
`.env` defaults already point at these. Buckets are created on first use (`ObjectStore().ensure_bucket()`).

## 3. Deploy to Akamai Cloud
```bash
export LINODE_TOKEN=...                                        # Cloud Manager -> API Tokens
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars   # edit: prefix, ssh key, admin_cidrs, bucket_label
make deploy-akamai project=vouch                            # instance path (default)
DEPLOY_TARGET=lke REGISTRY=ghcr.io/<you> make deploy-akamai project=vouch   # LKE path
make tail-logs project=vouch
make smoke project=vouch host=http://<nodebalancer-ip>
```
After the first apply: `terraform -chdir=infra/terraform output -raw object_storage_access_key` (and secret / database_url) into the server's `.env`.
Managed Postgres is slow to provision; enable it early (`enable_postgres = true`) or use the compose Postgres on the instance.

### 3a. Image invoices (PNG/JPEG) need Tesseract *inside the API container*
`pytesseract` is only a wrapper; the API image (`python:3.12-slim`) installs `tesseract-ocr` + `tesseract-ocr-eng`
itself (`infra/docker/python-app.Dockerfile`, build arg `OCR=1`, set by `infra/compose/akamai-app.yml`). Without
the binary every image invoice is held with amount 0 and the reason
"image invoice could not be read: this server has no OCR engine". Check and roll out:

```bash
curl -ks https://<nodebalancer>/v1/health | jq .ocr        # {"state":"live","backend":"tesseract","tesseract_version":"5.3.0",...}
# Rebuild the API image on the app Linode (picks up the Dockerfile change; ~1-2 min of API downtime while the
# container is replaced; the NodeBalancer health check on /v1/health shows the node down meanwhile):
ssh root@<app-ip> 'cd /opt/vouch/repo/backend && git pull --ff-only && docker compose -f infra/compose/akamai-app.yml up -d --build'
# or from your machine, the same thing plus secrets + verification:
infra/scripts/deploy_akamai.sh --secrets-only
infra/scripts/verify_deploy.sh https://<nodebalancer>        # FAILs when /v1/health .ocr.state != live
```

No-downtime stopgap (zero restarts; survives `docker compose restart` but **not** a rebuild or `up --build`,
so do the rebuild above afterwards): install the package into the running container. A missing engine is
re-probed on every intake / health poll, so the next image invoice is OCRed and `/v1/health .ocr` flips to
`live` within seconds:
```bash
ssh root@<app-ip> 'cd /opt/vouch/repo/backend && \
  docker compose -f infra/compose/akamai-app.yml exec -T -u root api sh -c \
    "apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/* && tesseract --version"'
curl -ks https://<nodebalancer>/v1/health | jq .ocr.state     # "live"
```
Cards already held with "this server has no OCR engine" are not re-run: resubmit the email (or re-key the
invoice and resolve the hold). `apt-get` on the Linode host itself does nothing for the container (different
filesystem); cloud-init installs it there only for running the API outside Docker.

## 4. When things break
| Symptom | Fix |
|---|---|
| `ConfigError: No LLM provider configured` | fill `AKAMAI_INFERENCE_*` (or `BEDROCK_MODEL_ID`) in `.env` |
| Agent calls slow / 429s | expected at 60 rpm; check for tool loops, shorten prompts, rehearse with `ScriptedModel` |
| `/ready` 503 on inference | no model yet: `make train-<project>` (or copy `artifacts/` to the server) |
| Frontend CORS error | add its exact origin to `CORS_ALLOW_ORIGINS`, restart the API |
| `ProfileNotFound` from boto3 | an empty `AWS_PROFILE=` is exported; remove it |
| Deploy works but NodeBalancer shows nodes down | API must listen on `api_port` (8100) on the VPC IP; check `docker compose ps` on the VM |
| PNG/JPEG invoice lands with amount 0, "image invoice could not be read: this server has no OCR engine" (PDFs fine) | `tesseract` binary missing in the API container: `/v1/health` → `.ocr.state == "down"`. Rebuild the image (Dockerfile `OCR=1`) or install it in the running container, see §3a |

## 5. Freeze before judging
Last commit before the deadline, then **no code changes**. Re-run `docs/SUBMISSION.md`.
