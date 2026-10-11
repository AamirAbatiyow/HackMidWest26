#!/usr/bin/env bash
# Tear down everything Terraform created for Vouch on Akamai Cloud (tag vouch-hackathon).
#   export LINODE_TOKEN=...; make destroy-akamai
# Add --yes to skip the confirmation prompt (CI). The Object Storage bucket must be empty to delete;
# this script empties it first when the s3 CLI (aws or s3cmd) is available.
set -euo pipefail
cd "$(dirname "$0")/../.."
tf_dir="infra/terraform/akamai"
tf="terraform -chdir=$tf_dir"

[[ -n "${LINODE_TOKEN:-}" ]] || { echo "export LINODE_TOKEN first"; exit 1; }
export TF_VAR_linode_token="$LINODE_TOKEN"
$tf init -input=false >/dev/null

if [[ "${1:-}" != "--yes" ]]; then
  echo "This destroys the Vouch VPC, Linodes, NodeBalancer, firewalls, Object Storage bucket and the managed database."
  read -r -p "Type 'destroy' to continue: " answer
  [[ "$answer" == "destroy" ]] || { echo "aborted"; exit 1; }
fi

bucket=$($tf output -raw object_storage_bucket 2>/dev/null || true)
endpoint=$($tf output -raw object_storage_endpoint 2>/dev/null || true)
if [[ -n "$bucket" && -n "$endpoint" ]] && command -v aws >/dev/null; then
  echo "== emptying bucket $bucket =="
  AWS_ACCESS_KEY_ID="${OBJECT_STORAGE_ACCESS_KEY:-}" AWS_SECRET_ACCESS_KEY="${OBJECT_STORAGE_SECRET_KEY:-}" \
    aws --endpoint-url "$endpoint" s3 rm "s3://$bucket" --recursive 2>/dev/null || echo "(bucket not emptied; destroy may fail on it)"
fi

$tf destroy -input=false -auto-approve
echo "destroyed. Local state kept in $tf_dir/terraform.tfstate (gitignored)."
