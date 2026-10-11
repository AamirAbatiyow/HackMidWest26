#!/usr/bin/env bash
# Tail container logs on the Akamai Linodes.
#   infra/scripts/tail_logs.sh [host] [api|inference]
# host defaults to the first app Linode from terraform output. `inference` is tailed on the private
# model Linode through the app Linode (ssh -J), since the model server has no public interface.
set -euo pipefail
cd "$(dirname "$0")/../.."
tf="terraform -chdir=infra/terraform/akamai"
host="${1:-}"
svc="${2:-api}"
[[ -n "$host" ]] || host=$($tf output -json app_public_ips | jq -r '.[0]')

if [[ "$svc" == "inference" ]]; then
  model_ip=$($tf output -raw model_vpc_ip)
  ssh -J "root@$host" "root@$model_ip" "cd /opt/vouch/repo/backend && docker compose -f infra/compose/akamai-model.yml logs -f --tail=200"
else
  ssh "root@$host" "cd /opt/vouch/repo/backend && docker compose -f infra/compose/akamai-app.yml logs -f --tail=200"
fi
