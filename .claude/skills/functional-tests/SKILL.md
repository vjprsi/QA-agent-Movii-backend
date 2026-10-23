---
name: functional-tests
description: Execute functional and regression API test cases with Newman (Postman CLI) against the TEST base URL, using variables.json, and store request/response evidence per test id. Use in Phase E step 1.
---
# functional-tests

## 1. Build the Newman environment from variables.json (never commit it)
```bash
python3 -I scripts/make_newman_env.py --vars docs/<service>/<run>/variables.json \
  --test-data docs/<service>/<run>/test_data.json \
  --out docs/<service>/<run>/postman/env.json
```
Resolves `{{var}}` names used by the collection to variable keys / test_data
labels; unresolved names are already in `variables-check.json` → BLOCKED.

## 2. Run the baseline (the repo's collection = regression)
```bash
newman run workspace/<service>/docs/postman/<collection>.json \
  -e docs/<service>/<run>/postman/env.json \
  --env-var baseUrl=<base_url> \
  --reporters cli,json,htmlextra \
  --reporter-json-export docs/<service>/<run>/functional/regression-newman.json \
  --reporter-htmlextra-export docs/<service>/<run>/functional/regression-newman.html \
  --timeout-request 15000 --delay-request 100 --insecure
```
(`htmlextra` needs `npm i -g newman-reporter-htmlextra`; if absent use `cli,json`.)

## 3. Run the generated cases
Same command on `test-cases/<service>/<run>/postman/generated.postman_collection.json`
→ `functional/generated-newman.json`. For chained flows set
`--folder "<flow name>"` so order is preserved. Add a unique run tag
(`X-QA-Run: <run>`) header to every request so logs can be filtered later.

## 4. Evidence + status
```bash
python3 -I scripts/newman_to_evidence.py --newman docs/<service>/<run>/functional/*.json \
  --index test-cases/<service>/<run>/index.csv \
  --evidence docs/<service>/<run>/evidence
```
Writes `evidence/<ID>/request.json`, `response.json`, `assertions.txt`
(masked) and updates `status` in `index.csv` (PASS / FAIL / BLOCKED).

## 5. Manual-automation cases
For `automation=manual` (real OTP etc.): ask the tester for the value at the
moment it is needed; if not available, mark `BLOCKED (manual input)`.

## 6. Summarise
Write `functional/functional-results.md`: counts, failures with one-line
cause, and the list of `(ID, endpoint, DB tables)` that `db-verify` must
check next.
