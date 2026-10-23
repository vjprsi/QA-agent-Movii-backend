# Severity matrix

| Severity | Definition | Examples |
|---|---|---|
| **CRITICAL** | Money, data or security exposure; or the service is unusable | Sensitive data (PIN, password, token, full MSISDN, card) in logs or plaintext in DB; auth bypass; SQLi; service down under ≤ expected TPS; direct internet egress from a private service |
| **HIGH** | Core business flow wrong or SLA broken, no workaround | Wrong balance after transfer; negative amount accepted; p95 > SLA at target TPS; stack trace in API response; missing authz on an endpoint |
| **MEDIUM** | Non-core defect or degraded quality with workaround | Wrong error code; missing validation on optional field; log line missing traceId; memory steadily growing but within limit |
| **LOW** | Cosmetic / informational | Typo in message; inconsistent field casing; verbose DEBUG in TEST |

Stress verdicts:
- PASS: all ladder steps meet p95/p99 and error-rate SLA; no pod restart;
  memory and CPU below `pod_*_limit_pct_max`; DB connections return to
  baseline within 60 s after the last step.
- FAIL: any SLA breach at ≤ `stress_max_tps`, any restart/OOMKilled, DB
  connection leak (connections do not return to baseline), errors > max.
