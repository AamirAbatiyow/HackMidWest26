#!/usr/bin/env bash
# Deploy Vouch to Akamai Cloud (us-ord): terraform apply -> push human-held secrets over SSH -> verify.
#
#   export LINODE_TOKEN=...                      # Akamai Cloud Manager -> API Tokens (read/write)
#   cp infra/terraform/akamai/terraform.tfvars.example infra/terraform/akamai/terraform.tfvars  # edit
#   make deploy-akamai                           # = infra/scripts/deploy_akamai.sh
#   infra/scripts/deploy_akamai.sh --secrets-only   # re-push secrets + restart the API (no terraform)
#   infra/scripts/deploy_akamai.sh --plan            # terraform plan only
#
# Secrets pushed from the local environment / backend/.env (never from Terraform, never committed):
#   AKAMAI_INFERENCE_API_KEY, XRPL_WALLET_SEED, XRPL_DESTINATION_ADDRESS, API_KEYS
# Terraform-known settings (database URL, object storage keys, model URL, CORS) are written by cloud-init.
#
# NOT YET EXERCISED WITH LIVE CREDENTIALS: validated with `terraform validate` + `terraform plan` only.
set -euo pipefail
cd "$(dirname "$0")/../.."
tf_dir="infra/terraform/akamai"
tf="terraform -chdir=$tf_dir"
mode="${1:-apply}"

need() { command -v "$1" >/dev/null || { echo "missing: $1"; exit 1; }; }
need terraform; need ssh; need curl; need jq

[[ -n "${LINODE_TOKEN:-}" ]] || { echo "export LINODE_TOKEN first (Akamai Cloud Manager -> API Tokens)"; exit 1; }
if [[ ! -f "$tf_dir/terraform.tfvars" ]]; then
  echo "cp $tf_dir/terraform.tfvars.example $tf_dir/terraform.tfvars and edit it (ssh key, admin CIDR, repo ref)"; exit 1
fi
export TF_VAR_linode_token="$LINODE_TOKEN"

# Load backend/.env (if present) for the secrets we push. Real environment variables win.
if [[ -f .env ]]; then
  while IFS='=' read -r k v; do
    [[ "$k" =~ ^[A-Z_]+$ ]] || continue
    [[ -z "${!k:-}" ]] && export "$k=$v"
  done < <(grep -E '^(AKAMAI_INFERENCE_API_KEY|XRPL_WALLET_SEED|XRPL_DESTINATION_ADDRESS|API_KEYS)=' .env || true)
fi

$tf init -input=false >/dev/null

if [[ "$mode" == "--plan" ]]; then
  $tf plan -input=false
  exit 0
fi

if [[ "$mode" != "--secrets-only" ]]; then
  echo "== terraform apply (Managed PostgreSQL alone takes 10-20 minutes) =="
  $tf apply -input=false -auto-approve
fi

public_url=$($tf output -raw public_url)
mapfile -t app_ips < <($tf output -json app_public_ips | jq -r '.[]')
settlement=$(grep -E '^settlement_adapter' "$tf_dir/terraform.tfvars" | sed -E 's/.*"(.*)".*/\1/' || echo xrpl)
ssh_opts=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

if [[ "$settlement" == "xrpl" && -z "${XRPL_WALLET_SEED:-}" ]]; then
  echo "settlement_adapter=xrpl but XRPL_WALLET_SEED is empty: run 'make xrpl-wallets' first (or set settlement_adapter=mock)"
  exit 1
fi
[[ -n "${AKAMAI_INFERENCE_API_KEY:-}" ]] || echo "warning: AKAMAI_INFERENCE_API_KEY is empty; the API will run with template fallbacks"

secrets=$(mktemp); trap 'rm -f "$secrets"' EXIT
{
  echo "# pushed by deploy_akamai.sh $(date -u +%FT%TZ)"
  [[ -n "${AKAMAI_INFERENCE_API_KEY:-}" ]] && echo "AKAMAI_INFERENCE_API_KEY=$AKAMAI_INFERENCE_API_KEY"
  [[ -n "${XRPL_WALLET_SEED:-}" ]] && echo "XRPL_WALLET_SEED=$XRPL_WALLET_SEED"
  [[ -n "${XRPL_DESTINATION_ADDRESS:-}" ]] && echo "XRPL_DESTINATION_ADDRESS=$XRPL_DESTINATION_ADDRESS"
  [[ -n "${API_KEYS:-}" ]] && echo "API_KEYS=$API_KEYS"
} > "$secrets"

for ip in "${app_ips[@]}"; do
  echo "== app $ip: waiting for cloud-init =="
  until ssh "${ssh_opts[@]}" "root@$ip" 'cloud-init status --wait >/dev/null 2>&1 && test -f /opt/vouch/repo/backend/.env' 2>/dev/null; do
    sleep 10; printf '.'
  done; echo
  # Replace any previously pushed secrets, keep the Terraform-written base .env.
  ssh "${ssh_opts[@]}" "root@$ip" "cd /opt/vouch/repo/backend && sed -i '/^# pushed by deploy_akamai.sh/,\$d' .env"
  ssh "${ssh_opts[@]}" "root@$ip" "cat >> /opt/vouch/repo/backend/.env" < "$secrets"
  ssh "${ssh_opts[@]}" "root@$ip" "cd /opt/vouch/repo/backend && git pull --ff-only >/dev/null 2>&1 || true; docker compose -f infra/compose/akamai-app.yml up -d --build"
done

echo "== waiting for $public_url/v1/health =="
for _ in $(seq 1 60); do
  if curl -ksf --max-time 5 "$public_url/v1/health" >/dev/null; then break; fi
  sleep 5; printf '.'
done; echo
echo "deployed: $public_url"
$tf output next_steps
infra/scripts/verify_deploy.sh "$public_url" || echo "verification reported problems (see above)"
