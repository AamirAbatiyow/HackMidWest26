SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
RUN := $(UV) run --all-packages
PROJECTS := $(notdir $(wildcard projects/*))
project ?= vouch
# `make setup` installs the trained-model (torch CPU + LIME) and XRPL stacks so the demo is real out of the box.
GROUPS ?= ml chain
TF_DIR := infra/terraform/akamai

.PHONY: help setup setup-min setup-agents setup-all lint format test check \
        run-vouch serve-vouch train-vouch dev-vouch demo-vouch demo-vouch-files demo-vouch-xrpl redteam-vouch \
        smoke-llm samples xrpl-wallets xrpl-smoke up down logs smoke \
        tf-init tf-validate tf-plan deploy-akamai destroy-akamai verify-akamai tail-logs clean

help: ## Show targets
	@grep -hE '^[a-zA-Z0-9_%-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo "  projects: $(PROJECTS)"

# --- Environment --------------------------------------------------------------------------------
# Each setup-* is an exact sync: it installs base + the listed stacks (and removes stacks not listed).

setup: ## Install deps for all packages/projects (+ torch CPU, LIME, xrpl-py), create .env from .env.example
	@command -v $(UV) >/dev/null || { echo "uv not found: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
	$(UV) sync --all-packages $(foreach g,$(GROUPS),--group $(g))
	@test -f .env || { cp .env.example .env && echo "created backend/.env from .env.example (fill in AKAMAI_INFERENCE_API_KEY locally)"; }

setup-min: ## Smallest install (heuristic scorer, mock ledger): no torch, no xrpl
	$(MAKE) setup GROUPS=""

setup-agents: ## setup + Strands Agents SDK extras (MCP, OpenTelemetry exporters)
	$(MAKE) setup GROUPS="ml chain agents"

setup-all: ## setup + every optional stack
	$(MAKE) setup GROUPS="ml chain agents tf"

# --- Quality ------------------------------------------------------------------------------------

lint: ## Ruff lint + format check
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format: ## Auto-fix lint + format
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

test: ## Run every test (imported engine/model/red-team tests + intake/sender/vendor/audit/Cedar/API tests)
	$(RUN) pytest

check: lint test ## lint + test

# --- Vouch --------------------------------------------------------------------------------------

run-vouch: ## Start the Vouch API on :8101 (frontend contract + /v1 engine routes)
	$(RUN) vouch-api

serve-vouch: ## Start the risk-model inference service on :8201 (private model Linode in production)
	$(RUN) python -m vouch.services.inference

train-vouch: ## Train the vouch-risk PyTorch model on synthetic data and register a new version
	$(RUN) python -m vouch.models.train

dev-vouch: ## API + inference together (Ctrl-C stops both)
	@trap 'kill 0' EXIT; $(MAKE) --no-print-directory serve-vouch & $(MAKE) --no-print-directory run-vouch

demo-vouch: ## Seed, hold, approve, settle: the six-invoice Friday run in-process (no servers needed)
	$(RUN) vouch-demo

demo-vouch-files: ## Same demo, but the invoices enter as .eml / PDF / XLSX / PNG (OCR) / CSV through intake
	$(RUN) vouch-demo --files

demo-vouch-xrpl: ## Demo settling on the XRPL testnet (needs XRPL_WALLET_SEED from `make xrpl-wallets`)
	$(RUN) vouch-demo --xrpl

redteam-vouch: ## Run the 24-attack red-team suite (prompt injection, LLM output, approvals, limits, identity, Cedar)
	$(RUN) vouch-redteam

smoke-llm: ## Live Akamai inference smoke (chat + embeddings); skips cleanly when AKAMAI_INFERENCE_API_KEY is unset
	$(RUN) vouch-smoke-llm

samples: ## Regenerate projects/vouch/samples (synthetic .eml / PDF / XLSX / PNG / CSV invoices)
	$(RUN) vouch-make-samples

xrpl-wallets: ## Fund two XRPL testnet faucet wallets, set up IOU trustlines and write XRPL_* vars into .env (never commit .env)
	$(RUN) python -m hm_settlement.xrpl_setup --write-env

xrpl-smoke: ## Opt-in live XRPL testnet smoke test: sends a real IOU payment (needs XRPL_WALLET_SEED from `make xrpl-wallets`)
	$(RUN) pytest packages/settlement/tests/test_xrpl_smoke.py -v -s

# --- Local infra (Docker) -----------------------------------------------------------------------

up: ## Postgres+pgvector, Valkey, S3-compatible store; add project=vouch to also run the API + inference containers
	@if [ -n "$(filter command line,$(origin project))" ]; then \
		PROJECT=$(project) docker compose --profile app up -d --build; \
	else docker compose up -d; fi

down: ## Stop local containers
	docker compose --profile app down

logs: ## Follow local container logs
	docker compose --profile app logs -f --tail=100

smoke: ## Hit the health endpoints of a running API: make smoke [host=http://localhost:8101]
	infra/scripts/smoke_test.sh $(project) $(host)

# --- Akamai Cloud (Linode) ------------------------------------------------------------------------
# Nothing here is applied without LINODE_TOKEN in the environment. tfstate and *.tfvars are gitignored.

tf-init: ## terraform init (local state)
	terraform -chdir=$(TF_DIR) init -input=false

tf-validate: tf-init ## terraform fmt -check + validate (no credentials needed)
	terraform -chdir=$(TF_DIR) fmt -check -recursive
	terraform -chdir=$(TF_DIR) validate

tf-plan: tf-init ## terraform plan (needs LINODE_TOKEN; TF_VAR_* override terraform.tfvars)
	@test -n "$$LINODE_TOKEN" || { echo "LINODE_TOKEN is not set"; exit 1; }
	TF_VAR_linode_token="$$LINODE_TOKEN" terraform -chdir=$(TF_DIR) plan -input=false

deploy-akamai: ## terraform apply the Vouch stack in us-ord, then run the post-deploy verification (needs LINODE_TOKEN)
	infra/scripts/deploy_akamai.sh

destroy-akamai: ## terraform destroy everything tagged vouch-hackathon (needs LINODE_TOKEN; asks for confirmation)
	infra/scripts/destroy_akamai.sh

verify-akamai: ## Post-deploy checks against the NodeBalancer (health, roles, payments, settle dry-run): make verify-akamai host=https://...
	infra/scripts/verify_deploy.sh $(host)

tail-logs: ## Tail API logs on the app Linode over SSH: make tail-logs host=<ip>
	infra/scripts/tail_logs.sh $(host)

clean: ## Remove caches (keeps .venv, data and artifacts)
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
