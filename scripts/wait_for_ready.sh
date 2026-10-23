#!/usr/bin/env bash
# Wait for a rollout + health endpoint, and capture deploy evidence (read-only kubectl).
#   bash scripts/wait_for_ready.sh <namespace> <deployment> <health_url> [timeout_s] [out_dir]
set -u
NS="$1"; DEP="$2"; HEALTH="$3"; TO="${4:-600}"; OUT="${5:-.}"
CTX="${K8S_CONTEXT_TEST:-}"
KC="kubectl ${CTX:+--context $CTX} -n $NS"
mkdir -p "$OUT"

echo "[wait] rollout status $DEP (timeout ${TO}s)"
$KC rollout status deploy/"$DEP" --timeout="${TO}s" | tee "$OUT/rollout.txt"
RC=${PIPESTATUS[0]}

$KC get deploy,pods,svc -o wide > "$OUT/after.txt" 2>&1
$KC describe deploy "$DEP" > "$OUT/describe.txt" 2>&1
$KC get events --sort-by=.lastTimestamp > "$OUT/events.txt" 2>&1
POD=$($KC get pods -l app="$DEP" -o name 2>/dev/null | head -1)
[ -n "$POD" ] && $KC logs "$POD" --all-containers --tail=300 > "$OUT/startup-log.txt" 2>&1
$KC get deploy "$DEP" -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}' > "$OUT/image.txt" 2>/dev/null

if [ "$RC" -ne 0 ]; then echo "[wait] rollout FAILED (rc=$RC)"; exit 2; fi

echo "[wait] polling health $HEALTH"
END=$(( $(date +%s) + TO ))
while [ "$(date +%s)" -lt "$END" ]; do
  CODE=$(curl -sk -m 8 -o "$OUT/health.json" -w '%{http_code}' "$HEALTH" || echo 000)
  if [ "$CODE" = "200" ] && grep -qi '"status"\s*:\s*"UP"' "$OUT/health.json" 2>/dev/null; then
    echo "[wait] healthy: $(cat "$OUT/health.json" | head -c 200)"; exit 0
  fi
  sleep 10
done
echo "[wait] health endpoint did not return UP within ${TO}s (last HTTP $CODE)"; exit 3
