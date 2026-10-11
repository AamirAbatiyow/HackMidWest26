#!/usr/bin/env bash
# Usage:
#   infra/scripts/smoke_test.sh vouch                 # local: API + inference ports from config.py
#   infra/scripts/smoke_test.sh vouch http://1.2.3.4  # deployed: just the public API URL
set -uo pipefail
cd "$(dirname "$0")/../.."
project="${1:?usage: smoke_test.sh <project> [base_url]}"
base="${2:-}"

check() {
  local url="$1" code
  code=$(curl -s -o /tmp/smoke.out -w '%{http_code}' --max-time 5 "$url")
  if [[ "$code" == "200" ]]; then echo "OK   $url  $(head -c 160 /tmp/smoke.out)"; else echo "FAIL $url  ($code)"; fail=1; fi
}

fail=0
if [[ -n "$base" ]]; then
  check "$base/health"
  check "$base/ready"
else
  cfg="projects/$project/$project/config.py"
  [[ -f "$cfg" ]] || { echo "no such project: $project"; exit 1; }
  api_port=$(grep -Po '^\s*port: int = \K\d+' "$cfg")
  inf_port=$(grep -Po '^\s*inference_port: int = \K\d+' "$cfg")
  check "http://localhost:$api_port/health"
  check "http://localhost:$api_port/v1/info"
  check "http://localhost:$inf_port/health"
  check "http://localhost:$inf_port/ready"
fi
exit $fail
