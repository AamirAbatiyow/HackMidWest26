#!/usr/bin/env bash
# Post-deploy verification against a running Vouch API (local or on Akamai).
#
#   infra/scripts/verify_deploy.sh https://<nodebalancer-ip-or-domain>
#   VERIFY_SETTLE=1 infra/scripts/verify_deploy.sh https://...   # also approve + settle one demo card
#
# Checks: TLS answers, /v1/health, /health roles (which Akamai services are live), payments queue,
# a frontend-contract payment shape, Cedar policy mode, model scorer, red-team suite all blocked.
# Exit code is non-zero when a hard check fails. Self-signed certificates are accepted (-k).
set -uo pipefail
base="${1:?usage: verify_deploy.sh <base_url>}"
base="${base%/}"
curl_opts=(-ks --max-time 20)
fail=0

ok()   { printf 'OK    %s\n' "$*"; }
bad()  { printf 'FAIL  %s\n' "$*"; fail=1; }
warn() { printf 'WARN  %s\n' "$*"; }
get()  { curl "${curl_opts[@]}" "$base$1"; }

echo "== Vouch verification: $base =="

# 1. TLS / reachability
if [[ "$base" == https://* ]]; then
  if curl "${curl_opts[@]}" -o /dev/null -w '%{http_code}' "$base/v1/health" | grep -q '^200$'; then
    subject=$(echo | openssl s_client -connect "${base#https://}:443" -servername "${base#https://}" 2>/dev/null | openssl x509 -noout -subject 2>/dev/null || true)
    ok "TLS listener answers (${subject:-certificate subject unavailable})"
  else
    bad "no HTTPS answer from $base"
  fi
fi

# 2. cheap probe
probe=$(get /v1/health)
if echo "$probe" | jq -e '.status == "ok"' >/dev/null 2>&1; then
  ok "/v1/health: $(echo "$probe" | jq -r '"\(.service) \(.version) llm=\(.llm_mode) scorer=\(.scorer) settlement=\(.settlement_adapter) db=\(.database) ocr=\(.ocr.state // "missing")/\(.ocr.tesseract_version // "-")"')"
else
  bad "/v1/health did not return status ok: $probe"
fi

# 3. roles: which Akamai services are live
health=$(get /health)
if echo "$health" | jq -e '.status' >/dev/null 2>&1; then
  for role in inference embeddings model_server database object_storage nodebalancer firewall vpc settlement risk_model policy_engine ocr; do
    state=$(echo "$health" | jq -r --arg r "$role" '.[$r].state // "missing"')
    detail=$(echo "$health" | jq -r --arg r "$role" '.[$r].detail // ""')
    case "$state" in
      live) ok "role $role: live ($detail)";;
      fallback) warn "role $role: fallback ($detail)";;
      off) warn "role $role: off ($detail)";;
      down) bad "role $role: down ($detail)";;
      *) bad "role $role: $state ($detail)";;
    esac
  done
  # ocr: image invoices (PNG/JPG) need the tesseract binary inside the API container; without it they are
  # held as unreadable (see docs/RUNBOOK.md "Image invoices come out as amount 0").
  for must in database model_server nodebalancer firewall vpc ocr; do
    [[ "$(echo "$health" | jq -r --arg r "$must" '.[$r].state')" == "live" ]] || bad "expected $must to be live on Akamai"
  done
else
  bad "/health unreadable"
fi

# 4. info
info=$(get /v1/info)
echo "$info" | jq -e '.policy_mode == "cedar"' >/dev/null 2>&1 && ok "Cedar policy engine active" || warn "policy_mode=$(echo "$info" | jq -r .policy_mode) (python mirror)"
echo "$info" | jq -e '.scorer | test("local-torch|inference-service")' >/dev/null 2>&1 && ok "trained model scoring: $(echo "$info" | jq -r .scorer)" || bad "scorer is $(echo "$info" | jq -r .scorer); expected the trained model"

# 5. payments queue + frontend contract shape
payments=$(get /v1/payments)
count=$(echo "$payments" | jq 'length' 2>/dev/null || echo 0)
if [[ "$count" -ge 6 ]]; then
  ok "$count payments in the queue"
  echo "$payments" | jq -e '.[0] | has("vendor") and has("status") and has("lifecycle") and has("risk") and has("trust_score") and has("evidence") and has("timeline") and has("checklist")' >/dev/null 2>&1 \
    && ok "payment shape matches the frontend contract" || bad "payment shape missing frontend fields"
  held=$(echo "$payments" | jq '[.[] | select(.status != "vouched")] | length')
  [[ "$held" -ge 1 ]] && ok "$held payment(s) on hold (quick_check / verify)" || warn "no held payments in the demo queue"
else
  bad "expected the six demo payments, got $count"
fi

# 6. red-team suite (cached server-side)
red=$(get /v1/redteam)
total=$(echo "$red" | jq -r '.total // 0'); blocked=$(echo "$red" | jq -r '.blocked // 0')
if [[ "$total" -ge 15 && "$total" == "$blocked" ]]; then ok "red-team: $blocked/$total attacks blocked"; else bad "red-team: $blocked/$total blocked"; fi

# 7. optional: approve + settle one approved-ready card (real XRPL tx when SETTLEMENT_ADAPTER=xrpl)
if [[ "${VERIFY_SETTLE:-0}" == "1" ]]; then
  pid=$(echo "$payments" | jq -r '[.[] | select(.status == "vouched" and .lifecycle == "pending")][0].id // empty')
  if [[ -n "$pid" ]]; then
    curl "${curl_opts[@]}" -X POST -H 'content-type: application/json' -d '{"note":"verify_deploy"}' "$base/v1/payments/$pid/approve" >/dev/null
    receipt=$(curl "${curl_opts[@]}" -X POST -H 'content-type: application/json' -d "{\"payment_ids\":[\"$pid\"],\"funding\":\"now\"}" "$base/v1/batch/settle")
    tx=$(echo "$receipt" | jq -r '.tx_id // empty'); url=$(echo "$receipt" | jq -r '.explorer_url // empty')
    [[ -n "$tx" ]] && ok "settled $pid: tx $tx ($url)" || bad "settlement failed: $receipt"
  else
    warn "no pending vouched payment to settle"
  fi
fi

[[ $fail -eq 0 ]] && echo "== verification passed ==" || echo "== verification FAILED =="
exit $fail
