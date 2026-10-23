---
name: generate-test-cases
description: Design an exhaustive, senior-QA test suite (extensive positive/negative functional & product cases derived from the user stories/description, plus regression, non-functional, security, code-level, endpoint and stress) for a service from its specs, endpoint-map, data-model and status-codes catalog. Scales to hundreds of cases for large products. Writes one file per test case plus index.csv with traceability and requires_vars. Use in Phase D before any execution.
---
# generate-test-cases

Inputs: `service-profile.md`, `endpoint-map.md`, `data-model.md`,
`analysis-gaps.md`, the Postman collection, `variables.json`,
`context/test-case-template.md`, `context/severity-matrix.md`.

Output: `test-cases/<service>/<run>/<category>/<ID>-<slug>.md` and
`test-cases/<service>/<run>/index.csv` with columns
`id,category,priority,title,traces_to,endpoint,automation,requires_vars,status`.
Also `postman/generated.postman_collection.json` under the same run folder
for every extra request you design (negative cases, authz cases).

## Scope: BUSINESS cases only (the baseline is automatic)
Do **not** re-code the checks that are identical for every Movii Spring Boot
service — `scripts/standard_suite.py` owns them (stable `STD-*` ids, run in
Phase E): ping/health, unknown route, wrong method, malformed body, envelope
shape, correlation-id, timezone, latency SLA, security headers, actuator
exposure, CORS, oversized body. Design only the **service-specific** behaviour:
the documented flows, business rules, state transitions, field validations and
error codes unique to this service. Keep business ids **stable across runs** of
the same service (don't renumber) so `regression_diff.py` can track them.

## Every endpoint gets cases — iterate the descriptor, not the docs

Walk **every** endpoint in `descriptor.json` / `discovered-endpoints.json`, not
only the flow the specs describe best. Orchestrators expose one controller per
flow (login, sign-up, change-password, forget-password-pin/otp, balance,
history, cards…); each needs its own cases. If an endpoint can't be executed
this run (missing credential, unreachable downstream, needs manual data), still
write its case(s) and set `status = BLOCKED (<reason>)` in `index.csv` —
designed-but-blocked is visible and runnable later; never-designed is an
invisible hole. Before you finish, confirm each descriptor endpoint appears at
least once in `index.csv` and call out any with zero cases.

## Be a senior QA: exhaustive, user-story-driven design

You are a senior enterprise QA engineer for a **product** company, not a script
that pokes endpoints. Per the MOVii standard (`context/movii-qa-standard.md`),
**cases are derived from the user stories and the functionality** — how a real
user or a consuming app actually uses the service — and then hardened with
security, code-level and endpoint cases. Mine every source the repo gives you:
the spec / README / SPEC-FUNCIONAL / SPEC-TECNICA, the api-contracts, the
Postman collection, the data model, the status-codes catalog in
`application.yml`, flow diagrams, and any description files the developers
provide (ask Phase A's code-analyst to surface them). **The richer the
description, the more cases you must produce.**

**There is no cap on the number of cases.** A tiny CRUD manager may need a few
dozen; a product flow like onboarding, login or P2P may need **hundreds**. Size
the suite to the service. The team's own hand-written sheets run to 100+ cases
for one orchestrator — match that depth. Never trim coverage to keep the count
small; breadth is the point.

Use the formal techniques a senior QA uses, and name the technique in the case's
`traces_to` so the plan is auditable:
- **Equivalence partitioning** — one case per valid class and per invalid class
  of each input.
- **Boundary-value analysis** — min, min-1, max, max+1, empty, max-length,
  max-length+1 for every bounded field.
- **Decision tables** — for rules driven by combinations of flags/fields
  (e.g. `hasFiscalResidenceAbroad` × `fiscalCountry`, `occupationType` ×
  required fields), one case per meaningful rule row.
- **State-transition testing** — every account/entity state (pending, active,
  suspended, blocked, locked, pin-not-set, deleted) × every operation, valid
  and invalid transitions.
- **Combinatorial / pairwise** — for enumerated fields, enumerate the values and
  their meaningful combinations (the team's sheet has one case *per* document
  type × occupation × fiscal-residence combo — do the same; pairwise if the
  full cross-product explodes).
- **Use-case / user-journey** — end-to-end multi-step journeys the way a user
  lives them (register → OTP → set PIN → login → query balance → change
  password → login again), asserting state and data at each hop.
- **Error guessing** — the odd real-world inputs (international `+57` prefix,
  compound names/surnames, unicode, leading zeros, double-submit, replay).

### Enumeration recipe (apply to every operation)
1. **Happy paths** — every *valid* variation, not just one: each document type
   (CC/CE/PPT), each gender mapping (GEN_FEM/GEN_MAL), single vs compound name
   and surname, each occupation/fiscal combination, each supported channel. The
   happy path is a *family* of cases, not one case.
2. **Field-level negatives** — for every field: missing, empty, null,
   whitespace, wrong type, too short, too long, wrong format/pattern, invalid
   enum value, injection string. Each asserts the **exact** business code +
   message (verbatim from the status-codes catalog / contract).
3. **Business-rule negatives** — duplicates (phone, document), wrong state,
   limit exceeded, blacklist/PEP, expired/used/foreign OTP, wrong current
   credential, mismatched confirmation, policy violations, lockout thresholds.
4. **Response/data correctness** — correct structure, correct mapped labels,
   correct masking, no sensitive field leaked, DB row correct (write ops),
   log lines correct (INFO start/end, masked secrets, ERROR without stacktrace).
5. **Cross-feature journeys & idempotency/concurrency** — the sequences above.

### Product-scenario catalog (prompt yourself with these every time)
Account states; authentication & lockout; credential lifecycle (set / change /
forget / reset); OTP lifecycle (request / validate / expire / reuse / wrong
number); limits and quotas; locale/gender/name-structure mapping; duplicates and
idempotency; concurrency on the same account; pagination and large result sets;
timeouts and downstream-down behaviour; permissions/roles; data retention and
masking; backward compatibility of old payloads. Not all apply to every service
— walk the list, keep what fits, and write cases for each.

Keep the **security, code-level and endpoint** cases (they are important and
differentiating): the `STD-*` baseline runs automatically, and the
`security-tests` checklist is instantiated per service. Functional/product is
the majority; security/code/endpoint sit on top.

## Functional cases come first — think like a human QA tester

For a business service, **functional cases are the bulk of the suite**, not an
afterthought behind the security/baseline checks. Security proves the service
is safe; functional proves it *does the right thing and says the right thing*.
Aim for functional to be the **largest category** on any service that has
business logic (as a rule of thumb, at least as many functional cases as
security + baseline combined). For every operation, write the cases a human
tester would, and for each **assert the exact outcome, not just the HTTP code**:
the specific business `code`, the exact user-facing `message`, and the state
change — e.g.:

- **Wrong credential:** incorrect PIN/MPIN → is the error the *right* one
  ("PIN incorrecto"), not a generic 500? Does it count toward lockout?
- **OTP flows:** wrong OTP, expired OTP, already-used OTP, OTP for a different
  phone → each its own specific message/code.
- **Password change:** wrong `currentPassword`; `newPassword` ==
  `currentPassword`; `newPassword` != `confirmation`; new password violates the
  policy → each distinct, correct message.
- **Registration:** duplicate phone, duplicate document, under-age DOB, invalid
  document type, TyC not accepted, blacklisted/PEP user → the exact rejection.
- **State:** operate on an account in the wrong state (not-active, locked,
  pending) → correct state error.
- **Boundaries & formats:** amount = 0 / negative / over limit, phone not 10
  digits / not starting in 3, bad date format → the field-specific message.
- **Idempotency / duplicates:** same request twice (double-submit) behaves per
  spec; **happy path** returns the right data and the right success message.

Write the **expected `message` text verbatim from the spec/contract** in each
case so the tester (and the run) can confirm message correctness, which is a
real defect class — a wrong or generic message is a FAIL even when the code is
right. Each functional case lists its input prerequisites in `requires_vars`
(e.g. `registered_msisdn;mpin`) so the variables-request can ask for them; a
case you cannot run yet is still **designed in full** and only marked BLOCKED
after the tester has been asked for the inputs (see the prerequisite gate in
CLAUDE.md Phase D).

## Coverage rules (minimum per endpoint in endpoint-map.md)

**functional (FUN-)**
- Happy path per documented flow (from spec), chained where the flow is
  multi-step (register → OTP → login → transfer → balance).
- Every request field: missing, wrong type, boundary (min/max/length), empty,
  null, whitespace, unicode, very long (10 KB).
- Business rules from the spec: limits, states, idempotency (same request
  twice), duplicates, concurrency (two parallel requests on the same account).
- Error contract: every documented error code reproduced **and the exact
  message verified**; body matches the standard error format; no stack trace.
- Response contract: field names, types, formats (dates ISO-8601 UTC, money
  decimals), no extra sensitive fields leaked (e.g. PIN hash returned).
- For every write endpoint add a **DB assertion** (table/columns from
  `data-model.md`, encryption state) and a **log assertion** (expected
  event line, traceId present).

**regression (REG-)**
- Everything already covered by the Postman collection, as-is (import
  request names verbatim) — these run first and act as the baseline.
- Backward-compat: old payload shapes mentioned in spec changelog still work.

**non-functional (NFR-)**
- Health/readiness/liveness respond; `/actuator/*` exposure limited to the
  documented endpoints (env/beans/heapdump must be closed).
- Timeouts and resilience: dependency down (if a mock/flag exists in TEST)
  returns a controlled error within the timeout; no thread/connection leak
  (check DB connections before/after 200 requests).
- Logging quality: JSON, level, traceId on 100 % of lines; no sensitive
  data; error logs carry the error code.
- Config hygiene: TEST profile active, no DEBUG for SQL loggers, actuator
  secured.
- Pagination/large payload behaviour; response compression; CORS if exposed.

**security (SEC-)** — one case per item in skill `security-tests` §Checklist,
instantiated for this service (endpoints, roles, fields).

**stress (STR-)**
- STR-001 ladder test with `stress_tps_ladder` (default `1,3,1,5,2,3`),
  `stress_step_seconds` each, on `stress_endpoints` (default: all GET + the
  main POST flow with unique data per iteration).
- STR-002 soak: `stress_max_tps/2` for 10 min (memory trend, DB connections).
- STR-003 spike: 0 → `stress_max_tps` in 5 s, hold 60 s, back to 0 — recovery
  time to baseline.
- STR-004 DB-connection behaviour: connections used vs pool max from config
  (`spring.datasource.hikari.maximum-pool-size`), leaks after the run.

## Review workbook — the TEST PLAN (always, BEFORE execution)
This is a gate: the QA team reviews the designed suite before anything runs.
As soon as every case file and `index.csv` exist — and before Phase E — build
the plan workbook:
```bash
python3 -I scripts/cases_to_xlsx.py --run-dir test-cases/<service>/<run> --mode plan
```
→ `test-cases/<service>/<run>/test-plan.xlsx`: a Summary sheet (planned cases
per category) + one sheet per category with **Test #, Priority, Title,
Endpoint, Traces to, Preconditions, Test data, Automation, Steps (what is
executed), Expected result** — and no results columns. Give the tester this
path and the per-category counts, and let them flag any coverage they want
added or run manually, before you execute.

For this to be useful the case files must be rich: fill Priority,
Preconditions, Test data and the Endpoint in each `<ID>.md` (template
`context/test-case-template.md`) and the `priority`/`endpoint` columns in
`index.csv`. A thin case file (steps + expected only) still works — Endpoint is
auto-derived from the first HTTP verb in the steps — but the plan is weaker.

The execution report (`test-cases.xlsx`, `--mode full`, adds Status / Observed
/ Severity) is produced later in Phase F by skill `evidence-report`.

## Writing rules
- **Fill `requires_vars` on every case that needs an input** (key, MSISDN,
  PIN/MPIN, password, OTP, document fields, encrypted Authorization, crypt
  key/IV, DB user…). This drives the prerequisite-variables **ASK** gate: after
  designing the cases, run `scripts/variables_request.py` and **ask the tester
  to provide the NEED list — do NOT mark the cases BLOCKED by default.** A case
  is BLOCKED only after the tester has been asked and cannot supply the value.
  Use `derived:<var>` for values obtained mid-run (e.g. an OTP read from SMS).
- Use `test_data.json` labels, never literal secrets; TEST data only.
- `Enfoque` (GT-GP-F05): functional→Funcional, security→Vulnerabilidad,
  stress→Prueba de carga. `Tipo de prueba`: Automatizado when the agent runs it,
  Manual when it needs a human (real OTP SMS, device). Set `automation=manual`
  for those.
- Keep business ids **stable across runs** so regression tracking works.
- Show the tester the per-category counts and the top-10 highest-risk cases
  before execution; proceed unless they object.
