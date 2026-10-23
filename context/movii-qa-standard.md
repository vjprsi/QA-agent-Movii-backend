# MOVii QA certification standard (GT-GP-F05)

This is the company test-development standard the agent certifies against and
mirrors in its deliverables. It comes from the QA team's own format
"GT-GP-F05 Desarrollo de Pruebas". Treat each line below as a rule the service
is expected to meet; a violation is a finding at the severity in
`severity-matrix.md`.

## How cases are derived (the most important rule)
- **Test cases are defined from the USER STORIES and the functionality** of the
  component/product — not only from the endpoint list. Start from *how a user
  (or a consuming app) actually uses the service* and work outward to every
  path, rule and error. The richer the spec/description, the more cases.
- A service is a **product feature**: design positive (happy) and negative
  cases for every real-world scenario a user or integrator can create, then the
  security, code-level and endpoint cases on top. Functional/product cases are
  the majority.

## Branches & deployment
- QA certifies the **release** branch; development delivers to QA from
  `development`. The release deploy must be **succeeded** on Azure (OKE).
- `application.yml` must be the single, updated config file in Azure.

## Versioning
- Semantic versioning `vX.Y.Z` (X breaks compatibility, Y adds back-compatible
  features, Z fixes). The version lives in **both** the POM/Gradle and the YML,
  is defined by development, and must be **higher than the version in
  production**. Flag a mismatch or a non-superior version.

## Logs (strict)
- Keys, PINs and OTPs must be **securely encrypted** in requests, responses and
  logs; the encrypted sensitive data must never be shown — mask with `****`.
  (The team treats a plaintext secret in logs as a fireable offense — so a
  plaintext PIN/OTP/password/key in any log is a **CRITICAL** finding.)
- Log level (info/debug/error) must be configurable from `application.yml`.
- Format shows the **correlationId and the thread on every line**, across the
  whole transaction flow.
- At least these key steps logged at **INFO**: start and end of the transaction
  with the consumed service name.
- Exceptions logged at **ERROR without stacktrace**.
- ISO-8583 / SOAP components: log the raw frame (string) **and** the decomposed
  frame (field: value) with sensitive values masked.

## Development / code quality
- **SonarQube**: no medium- or high-severity warnings. Un-fixable warnings must
  be documented by development and must be **≤ 5**.
- One config file only: `application.yml`. Standardized error handling defined
  **from the YML** (status-codes → code + message mapping).
- Developers must keep the **Postman collection in the repo `docs/` folder**
  updated on every change.
- Context path standard: `/movii-api/<BUSINESS_LINE>/v<N>/...` (or
  `/moviired-api/<BUSINESS_LINE>/v<N>/...`). Flag non-conforming paths.
- **No service is invoked with plain PIN+user** — use a TOKEN, or
  `USERNAME:PASSWORD` encrypted with **configurable seeds** from
  `application.yml`. A plaintext credential on the wire is a finding.

## API-Manager
- Every service must expose a **PING** method (health/liveness). Missing PING is
  a finding.

## Deliverable format (mirror GT-GP-F05)
The team's workbook has these tabs; the agent's Excel should map to them:
- **Introducción** — the functionality/component/product under test.
- **Casos** — the test cases, columns: `ID CP, Componente, Método, Caso Prueba,
  Severidad, Tipo de prueba (Automatizado|Manual), Enfoque
  (Funcional|Vulnerabilidad|Prueba de carga), Resultados Esperados, Resultados
  Obtenidos, Estado del Resultado`.
- **Informe** — execution report (analyst, certified environment, component,
  date, result).
- **Checklist** — documentary items for the release committee.
- **Cronograma** — deployment schedule.

`Enfoque` maps from the agent's category: functional → Funcional; security →
Vulnerabilidad; stress → Prueba de carga; regression/non-functional keep their
own label. `Tipo de prueba` = Automatizado when the agent runs it, Manual when
it is designed for a human (e.g. a case needing a device SMS/OTP read by hand).
