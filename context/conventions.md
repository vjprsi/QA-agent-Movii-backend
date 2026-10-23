# Conventions (how our services and tests are expected to look)

## Service conventions (what "correct" means for us)
- Spring Boot 3.x, Java 17+, Maven (`pom.xml`) or Gradle.
- Health: `GET /actuator/health` → `{"status":"UP"}`. Info: `/actuator/info`.
- Auth: Bearer JWT on every business endpoint. Public endpoints must be listed
  in the spec; anything else unauthenticated = **HIGH** finding.
- Standard error body:
  `{"code": "<SERVICE>-<NNN>", "message": "...", "traceId": "...", "timestamp": "..."}`
  Stack traces or SQL text in responses = **HIGH** finding.
- Correlation: every request/response/log line carries `traceId` (header
  `X-Trace-Id` or `X-Request-Id`).
- Logs: JSON, one line per event, fields `timestamp level logger traceId message`.
  Business events log at INFO; validation failures WARN; unexpected ERROR.
- Sensitive fields that must NEVER appear in logs or in plaintext in the DB:
  `msisdn/phone` (may appear masked `57300****123`), `pin`, `password`,
  `otp`, `token`, `jwt`, `cardNumber/pan`, `cvv`, `documentId/cedula`,
  `email` (masked OK), `secret`, `apiKey`.
- DB: field names `snake_case`; money as `DECIMAL(19,4)` or minor-unit `BIGINT`,
  never FLOAT; timestamps `UTC`; soft-delete via `deleted_at`.
- Encryption at rest: columns listed in the spec / `encrypted_db_fields`
  variable must hold ciphertext (base64 or hex, no readable digits/letters
  matching the input). Columns in `plaintext_db_fields` must be readable.
- Networking: services talk to the internet only through the approved
  egress/NAT or not at all. Any direct public IP, public DNS name (not in
  allowlist), or `http://` call in code/config = finding.

## Test-case conventions
- IDs: `FUN-###`, `REG-###`, `NFR-###`, `SEC-###`, `STR-###`.
- One file per test case, template in `context/test-case-template.md`.
- Every case traces to a spec section or an endpoint in `endpoint-map.md`.
- Every executed case has evidence: request, response, DB query+result, log
  excerpt — saved as files, referenced by path.
- Severity from `context/severity-matrix.md`.

## Report conventions
- Report path: `docs/<service>/<run>/QA-REPORT.md` and `.html`.
- Evidence folder: `docs/<service>/<run>/evidence/<TEST-ID>/`.
- Masking: secrets and PII shown as first 2 + last 2 chars (`ab****yz`).
- Language: English; keep Spanish field names as they appear in the service.
