#!/usr/bin/env bash
# Usage: DEPLOY_TARGET=instance|lke infra/scripts/tail_logs.sh <project> [api|inference]
set -euo pipefail
cd "$(dirname "$0")/../.."
project="${1:?usage: tail_logs.sh <project> [api|inference]}"
svc="${2:-api}"

if [[ "${DEPLOY_TARGET:-instance}" == "lke" ]]; then
  export KUBECONFIG="$PWD/.kubeconfig-$project"
  kubectl -n "$project" logs -f "deploy/$svc" --tail=200
else
  ip=$(terraform -chdir=infra/terraform output -raw instance_public_ip)
  ssh "root@$ip" "cd /opt/app/repo && docker compose --profile app logs -f --tail=200 $svc"
fi
