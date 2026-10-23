---
name: log-audit
description: Pull pod logs for the run window from the service's TEST namespace, verify expected log events and structure (JSON, level, traceId), and scan for sensitive data (MSISDN, PIN, password, OTP, tokens, cards, document ids, SQL, stack traces). Use in Phase E step 3 and after deploy/stress.
---
# log-audit

## 1. Collect
```bash
NS=<k8s_namespace>; DEP=<k8s_deployment>; OUT=docs/<service>/<run>/logs
mkdir -p $OUT
for P in $(kubectl --context $K8S_CONTEXT_TEST -n $NS get pods -l app=$DEP -o name); do
  kubectl --context $K8S_CONTEXT_TEST -n $NS logs $P --all-containers --since-time="<run start ISO>" --timestamps > "$OUT/$(basename $P).log"
  kubectl --context $K8S_CONTEXT_TEST -n $NS logs $P --previous --all-containers > "$OUT/$(basename $P).previous.log" 2>/dev/null || true
done
```
(or `mcp__kubernetes__pods_log`). Then query **Loki** through the
`mcp-movii-logs` MCP (LogQL, environment `qa` only) for the same window and
save as `$OUT/loki.json` (labels: `k8s_namespace_name`, `k8s_pod_name`,
`service_name`; QA namespaces are `<domain>-qa`, e.g. `core-qa`) — it keeps logs of pods that restarted or were
replaced, which `kubectl logs` loses. For every ERROR with a traceId, pull the
trace from the `mcp-movii-traces` MCP (Tempo) and save under `$OUT/traces/`.
If the service ships logs to OCI Logging, list its log groups with the
`movii-oci` MCP. If an MCP is unreachable (VPN off), note it in
`preflight.md` and continue with `kubectl` only.

## 2. Scan for sensitive data
```bash
python3 -I scripts/scan_logs.py --logs "$OUT"/*.log --patterns context/sensitive-patterns.json \
  --extra-fields "<log_sensitive_fields from variables>" \
  --known-values docs/<service>/<run>/variables.json \
  --out "$OUT/sensitive-scan.md" --json "$OUT/sensitive-scan.json"
```
`--known-values` makes the scan also search for the **actual** test values
(msisdn, pin, password, otp, tokens) you used in the run — the strongest check.
Every hit = finding (severity from the pattern), with file:line and the
masked excerpt. Masked forms in `allowed_masked_examples` are fine.

## 3. Structure & correctness
`scripts/scan_logs.py` also writes `log-structure.json`:
- % lines valid JSON; fields present (`timestamp level logger traceId message`)
- level distribution; ERROR/WARN count; distinct exception classes
- % lines with traceId; requests from `X-QA-Run: <run>` tag found
- SQL statements logged (Hibernate `show-sql`/DEBUG) → finding in TEST if
  they include parameter values
- stack traces count; repeated identical ERRORs (noise) → MEDIUM

Then **you** verify the business events: for each executed FUN/REG case with
a log assertion, grep the traceId (from the response header/body) and confirm
the expected event lines exist and carry the right outcome. Missing event →
FAIL on that case (MEDIUM unless the spec requires it for audit → HIGH).

## 4. Output
`docs/<service>/<run>/logs/log-results.md`: sensitive-data table (pattern,
count, severity, sample masked), structure summary, per-test event
verification table, and status updates in `index.csv`.
Delete nothing; raw logs stay in the run folder as evidence (they are local
only — remind the tester the folder may contain PII if scan found hits).
