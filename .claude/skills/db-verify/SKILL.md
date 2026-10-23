---
name: db-verify
description: Verify MySQL state after functional tests with read-only queries — rows written, field values and types, encryption state (ciphertext vs plaintext), no sensitive data in plaintext, soft-delete and audit columns. Use in Phase E step 2 and inside security tests.
---
# db-verify

Inputs: `data-model.md`, `functional-results.md` (list of ID → endpoint →
tables), `variables.json` (`db_schema`, `encrypted_db_fields`,
`plaintext_db_fields`, test user identifiers), `context/sensitive-patterns.json`.

Tooling: `mcp__mysql__mysql_query` (read-only server) or
`mysql -h $MYSQL_TEST_HOST -u $MYSQL_TEST_RO_USER -p"$MYSQL_TEST_RO_PASS" --batch`.
Only `SELECT / SHOW / DESCRIBE / EXPLAIN`. Hooks block anything else.

## Per write test case (ID)
1. From the request evidence take the business key (msisdn, account id,
   transaction id, `X-QA-Run` tag if stored).
2. Run the lookup, save `evidence/<ID>/db.sql` and `db.txt` (masked):
   ```sql
   SELECT * FROM <schema>.<table> WHERE <key> = '<value>' ORDER BY created_at DESC LIMIT 5;
   ```
3. Assert and record in `db-verify/db-results.md`:
   - row exists exactly once (or N times when the spec says so); duplicates → FAIL
   - each field = expected (amount, status, currency, fk ids); types match
     `DESCRIBE <table>` (money is DECIMAL/BIGINT, not FLOAT/DOUBLE → FAIL HIGH)
   - timestamps are UTC and within the request window
   - `created_at/updated_at/created_by` populated; soft-delete column untouched
   - **encryption**: for every `encrypted_db_fields` column, the value must
     NOT equal/contain the plaintext you sent, must look like
     ciphertext (base64/hex, length ≥ 24) → otherwise **CRITICAL**;
     for `plaintext_db_fields` the value must be readable → otherwise HIGH
   - **sensitive plaintext scan**: run the regexes from
     `context/sensitive-patterns.json` against the row dump (PIN, password,
     full card, OTP, JWT). Hash columns are fine if they are hashes (bcrypt
     `$2a$`, argon2 `$argon2`, sha256 hex 64) — a reversible or plain value → CRITICAL
4. For negative/rejected cases: assert **no** row was written (or a REJECTED
   row with reason, if the spec says so).
5. Idempotency case: same request twice → exactly one row.
6. Concurrency case: two parallel transfers → balance consistent
   (`SELECT balance` before/after, sum of ledger rows = balance).

## Schema-level checks (once per run)
```sql
SELECT table_name, column_name, data_type, column_type, is_nullable
FROM information_schema.columns WHERE table_schema IN (<db_schema>) ORDER BY 1,2;
SHOW INDEX FROM <schema>.<table>;      -- FK/lookup columns indexed?
SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema IN (<db_schema>);
```
Compare with `data-model.md` and the DB architecture doc: missing columns,
type drift, missing indexes on columns used in WHERE by the code → findings.

## Connections baseline (used by stress)
```sql
SHOW STATUS LIKE 'Threads_connected'; SHOW STATUS LIKE 'Max_used_connections';
SHOW VARIABLES LIKE 'max_connections';
SELECT user, host, db, command, time, state FROM information_schema.processlist WHERE user = '<service db user>';
```
Save to `db-verify/connections-baseline.txt`.

Output: `docs/<service>/<run>/db-verify/db-results.md` (table: ID, table,
check, result, evidence path) + status updates in `index.csv`.
