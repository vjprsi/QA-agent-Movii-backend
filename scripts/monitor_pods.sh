#!/usr/bin/env bash
# Sample pod CPU/memory/restarts/phase every N seconds into a CSV (read-only kubectl).
#   bash scripts/monitor_pods.sh <namespace> <deployment/app-label> <interval_s> <out.csv>
set -u
NS="$1"; APP="$2"; INT="${3:-5}"; OUT="$4"
CTX="${K8S_CONTEXT_TEST:-}"
KC="kubectl ${CTX:+--context $CTX} -n $NS"

# limits once (first container)
LIM_CPU=$($KC get deploy "$APP" -o jsonpath='{.spec.template.spec.containers[0].resources.limits.cpu}' 2>/dev/null)
LIM_MEM=$($KC get deploy "$APP" -o jsonpath='{.spec.template.spec.containers[0].resources.limits.memory}' 2>/dev/null)
echo "# limits cpu=${LIM_CPU:-none} memory=${LIM_MEM:-none}" > "$OUT"
echo "ts,pod,cpu_m,mem_Mi,restarts,phase,ready" >> "$OUT"

while true; do
  TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  # top (may be unavailable → blanks)
  declare -A CPU MEM
  while read -r pod cpu mem; do
    [ -z "$pod" ] && continue
    CPU[$pod]="${cpu%m}"; MEM[$pod]="${mem%Mi}"
  done < <($KC top pod -l app="$APP" --no-headers 2>/dev/null)
  while read -r pod ready status restarts _; do
    [ -z "$pod" ] && continue
    echo "$TS,$pod,${CPU[$pod]:-},${MEM[$pod]:-},$restarts,$status,$ready" >> "$OUT"
  done < <($KC get pods -l app="$APP" --no-headers 2>/dev/null)
  sleep "$INT"
done
