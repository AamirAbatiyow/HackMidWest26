#!/usr/bin/env bash
# Deploy one project to Akamai Cloud. Usage: DEPLOY_TARGET=instance|lke infra/scripts/deploy_akamai.sh <project>
#
# instance (default): terraform apply -> rsync repo + .env + artifacts -> docker compose on the VM.
# lke:                terraform apply (use_lke=true in tfvars) -> build/push images -> kubectl apply -k.
#
# Needs: LINODE_TOKEN, terraform, infra/terraform/terraform.tfvars, .env (copied to the server, never committed).
# TODO: run end-to-end once against a real account early; this script has not been exercised with live credentials.
set -euo pipefail
cd "$(dirname "$0")/../.."
project="${1:?usage: deploy_akamai.sh <project>}"
target="${DEPLOY_TARGET:-instance}"
tf="terraform -chdir=infra/terraform"

[[ -d "projects/$project" ]] || { echo "no such project: $project"; exit 1; }
[[ -n "${LINODE_TOKEN:-}" ]] || { echo "export LINODE_TOKEN first (Akamai Cloud Manager -> API Tokens)"; exit 1; }
[[ -f infra/terraform/terraform.tfvars ]] || { echo "cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars and edit it"; exit 1; }
[[ -f .env ]] || { echo "missing .env"; exit 1; }

$tf init -input=false >/dev/null
$tf apply -input=false -auto-approve -var "use_lke=$([[ $target == lke ]] && echo true || echo false)"

if [[ "$target" == "instance" ]]; then
  ip=$($tf output -raw instance_public_ip)
  ssh_opts=(-o StrictHostKeyChecking=accept-new)
  echo "waiting for cloud-init on $ip..."
  until ssh "${ssh_opts[@]}" "root@$ip" 'cloud-init status --wait >/dev/null 2>&1; command -v docker' >/dev/null 2>&1; do sleep 10; done
  rsync -az --delete -e "ssh ${ssh_opts[*]}" \
    --exclude .venv --exclude .git --exclude data --exclude '__pycache__' --exclude .env \
    ./ "root@$ip:/opt/app/repo/"
  scp "${ssh_opts[@]}" .env "root@$ip:/opt/app/repo/.env"
  ssh "${ssh_opts[@]}" "root@$ip" "cd /opt/app/repo && PROJECT=$project INFERENCE_EXTRAS='${INFERENCE_EXTRAS:---extra explain}' docker compose --profile app up -d --build"
  url=$($tf output -raw public_url 2>/dev/null || echo "http://$ip:8100")
else
  registry="${REGISTRY:?set REGISTRY, e.g. ghcr.io/<user>}"
  overlay="infra/k8s/overlays/$project"
  [[ -d "$overlay" ]] || { echo "create $overlay (copy overlays/vouch)"; exit 1; }
  docker build -f infra/docker/python-app.Dockerfile --build-arg PROJECT="$project" \
    --build-arg EXTRAS="--extra agents" -t "$registry/$project-api:latest" .
  docker build -f infra/docker/python-app.Dockerfile --build-arg PROJECT="$project" \
    --build-arg EXTRAS="${INFERENCE_EXTRAS:---extra explain}" --build-arg APP_MODULE="$project.services.inference:app" \
    -t "$registry/$project-inference:latest" .
  docker push "$registry/$project-api:latest"
  docker push "$registry/$project-inference:latest"
  export KUBECONFIG="$PWD/.kubeconfig-$project"
  $tf output -raw kubeconfig | base64 -d > "$KUBECONFIG"
  kubectl create namespace "$project" --dry-run=client -o yaml | kubectl apply -f -
  kubectl -n "$project" create secret generic app-secrets --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f -
  kubectl apply -k "$overlay"
  kubectl -n "$project" rollout status deploy/api --timeout=180s
  lb=$(kubectl -n "$project" get svc api -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
  url="http://$lb"
fi

echo "deployed: $url"
infra/scripts/smoke_test.sh "$project" "$url" || echo "smoke test failed (inference /ready needs a trained model on the server)"
