---
name: stress-tests
description: Variable-TPS stress, soak and spike testing with k6 against the service's dedicated TEST namespace, with synchronized monitoring of pod CPU/memory/restarts (kubectl top), MySQL connections and latency/error SLAs. Aborts on restart or error breach. Use last in Phase E.
---
# stress-tests

Inputs from `variables.json`: `stress_tps_ladder` (e.g. `1,3,1,5,2,3`),
`stress_step_seconds` (60), `stress_max_tps`, `stress_p95_ms`,
`stress_error_rate_max`, `stress_endpoints`, `k8s_namespace`,
`k8s_deployment`, `base_url`, auth values. SLA defaults in
`context/environments.json → sla_defaults`.

## 0. Preconditions
- functional tests finished (so stress does not pollute their evidence)
- pods healthy, no restarts in last 10 min:
  `kubectl -n <ns> get pods -l app=<dep> -o wide`
- DB connection baseline recorded (skill `db-verify` §Connections)
- pool size from config: `grep -r maximum-pool-size workspace/<service>/src/main/resources`
- pod limits: `kubectl -n <ns> get deploy <dep> -o jsonpath='{.spec.template.spec.containers[0].resources}'`

## 1. Build the request set
```bash
python3 -I scripts/postman_to_k6_requests.py \
  --collection workspace/<service>/docs/postman/<collection>.json \
  --env docs/<service>/<run>/postman/env.json \
  --select "<stress_endpoints or ALL_GET+MAIN_POST>" \
  --out docs/<service>/<run>/stress/requests.json
```
Each request carries method, url, headers (token resolved), body template
with `${uniq}` placeholders so POSTs create distinct data per iteration.
Obtain a fresh token once per VU in `setup()` if the API needs it.

## 2. Start monitoring (background, same window)
```bash
OUT=docs/<service>/<run>/stress
bash scripts/monitor_pods.sh <ns> <dep> 5 "$OUT/pods.csv" &  PODS_PID=$!
bash scripts/monitor_db.sh 5 "$OUT/db-connections.csv" &     DB_PID=$!
```
`monitor_pods.sh` samples `kubectl top pod` + restart count + phase every 5 s;
`monitor_db.sh` samples `Threads_connected`, `Threads_running`,
`Max_used_connections`, `Aborted_connects`, `Connection_errors_max_connections`
with the read-only user.

Also, after each ladder step, query **Mimir** through the `mcp-movii-metrics` MCP
(PromQL, environment `qa`) for the same window — JVM heap, GC pause, Hikari
pool active/pending, `http_server_requests_seconds` p95/p99 per URI — and save
to `$OUT/mimir-step-<n>.json`. These are the server-side numbers; k6 gives the
client side. If the MCP is unreachable (VPN off), continue with the scripts.

## 3. Run the ladder (STR-001)
```bash
LADDER="1,3,1,5,2,3" STEP_SECONDS=60 BASE_URL=<base_url> \
P95_MS=<sla> ERR_MAX=<rate> REQUESTS=$OUT/requests.json RUN_TAG=<run> \
k6 run scripts/k6_ladder.js \
  --summary-export "$OUT/k6-summary.json" --out json="$OUT/k6-results.json" \
  2>&1 | tee "$OUT/k6-console.txt"
```
`k6_ladder.js` uses the `ramping-arrival-rate` executor so TPS is **exactly**
the ladder (not VUs), tags every request with `step` and `X-QA-Run`, and
enforces thresholds `http_req_duration{p(95)} < P95_MS` and
`http_req_failed < ERR_MAX`. The last stage ramps to 0 for 30 s to observe
recovery.

**Abort rules (watch `pods.csv` live every step):** restart count increases,
`OOMKilled`, memory > 95 % of limit, or error rate > `ERR_MAX` for a full
step → `kill $K6_PID`, record the step and reason, mark STR-001 FAIL.
Never exceed `stress_max_tps`. (Alternative runner: the `k6` MCP
`run_test`/`run_k6_script` tool with the same script and env.)

## 4. Soak (STR-002) and spike (STR-003)
Same script with `LADDER="<max/2>" STEP_SECONDS=600` (soak) and
`LADDER="0,<max>,<max>,0" STEP_SECONDS=5,60,...` → use `SPIKE=1` mode in the
script. Skip when the tester excluded them or time is short — say so.

## 5. Stop monitoring, collect
```bash
kill $PODS_PID $DB_PID
kubectl -n <ns> get events --sort-by=.lastTimestamp > "$OUT/events.txt"
kubectl -n <ns> logs -l app=<dep> --since=<window> | grep -Ei "error|exception|timeout|pool|connection" > "$OUT/logs-errors.txt"
python3 -I scripts/stress_report.py --out "$OUT" --sla context/environments.json --vars docs/<service>/<run>/variables.json
```
`stress_report.py` joins k6 per-step metrics with `pods.csv` and
`db-connections.csv` and writes `stress-results.md` (+ `stress.html` with
simple charts).

## 6. Judge (per `context/severity-matrix.md`)
PASS/FAIL per step and overall; connection leak = connections not back to
baseline ±2 within 60 s after the ramp-down; memory not released after
ramp-down → MEDIUM (possible leak) with the trend; any 5xx under ≤ max TPS →
HIGH; p95 breach → HIGH. Run `log-audit` once more over the stress window
(new error paths often log sensitive data).
