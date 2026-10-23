# <ID> — <short title>

| Field | Value |
|---|---|
| Category | functional / regression / non-functional / security / stress |
| Priority | P1 / P2 / P3 |
| Traces to | spec §x.y / endpoint `POST /v1/...` / requirement id |
| Preconditions | user exists, balance ≥ X, token valid ... |
| Test data | `test_data.<label>` or inline (masked) |
| Automation | Postman request `<name>` / k6 scenario / manual |

## Steps
1. ...
2. ...

## Expected result
- HTTP <code>, body matches `<schema or fields>`
- DB: `<table>` row with `<fields>` ; encrypted fields ciphertext
- Logs: INFO line `<event>` with traceId, no sensitive data

## Actual result   (filled at execution)
- Status: PASS / FAIL / BLOCKED / NOT RUN
- Observed: ...
- Evidence: `evidence/<ID>/request.json`, `response.json`, `db.sql`, `db.txt`, `log.txt`
- Severity (if FAIL): CRITICAL / HIGH / MEDIUM / LOW  — reason
