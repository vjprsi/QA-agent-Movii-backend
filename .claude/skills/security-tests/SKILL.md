---
name: security-tests
description: Security test checklist and execution for a private Spring Boot backend behind a public load balancer — OWASP API Top 10, auth/authz, input validation, secrets and dependency scanning, egress/public-IP detection, container and Kubernetes hardening, data exposure in logs and DB. Non-destructive, TEST only.
---
# security-tests

Tools: curl / Newman for probes; `semgrep`, `gitleaks`, `trivy` if installed
(otherwise grep-based fallbacks below); `scripts/check_egress.py`;
`kubectl get ... -o yaml` (read-only); skills `log-audit`, `db-verify`.
External skill packs that strengthen this (install once, see README):
`sast-semgrep`, `secrets-gitleaks`, `sca-trivy`, `dast-zap`, `dast-nuclei`
from **SecOpsAgentKit**, and the static-analysis / supply-chain plugins from
**trailofbits/skills**.

## Checklist → one SEC-### case each (instantiate per service)

### A. Authentication & authorization (OWASP API1/2/5)
- SEC-A1 every non-public endpoint without token → 401 (not 200/500)
- SEC-A2 expired / tampered-signature / `alg:none` JWT → 401
- SEC-A3 token of user A on user B's resource (BOLA) → 403/404, no data
- SEC-A4 role escalation: user token on admin endpoint → 403
- SEC-A5 brute force: 20 wrong PIN/password → lock or rate-limit present
- SEC-A6 OTP reuse / OTP of another user / OTP after expiry → rejected
- SEC-A7 session/token revocation after logout or password change

### B. Input validation & injection (API8/3)
- SEC-B1 SQLi probes in every string/number field (`' OR 1=1 --`, `1;SELECT`)
  → 400, no 500, no SQL text in body/logs
- SEC-B2 NoSQL/LDAP/command/path-traversal payloads where applicable
- SEC-B3 mass assignment: extra fields (`"balance":1e9`, `"role":"ADMIN"`,
  `"id":1`) ignored, not persisted (verify in DB)
- SEC-B4 oversized payload (2 MB) and deep JSON nesting → 413/400 quickly
- SEC-B5 content-type confusion (`text/plain`, XML) → 415
- SEC-B6 negative/zero/huge amounts, float precision (`0.1+0.2`), currency
  mismatch → rejected, DB unchanged
- SEC-B7 unicode/homoglyph/emoji in identifiers; null bytes

### C. Data exposure (API3/API10)
- SEC-C1 responses never return PIN/password/hash/token/full card/full
  msisdn where spec says masked (check every 200 body)
- SEC-C2 error bodies: no stack trace, class names, SQL, server header
  versions
- SEC-C3 logs: run `log-audit` sensitive scan → any hit is a SEC finding
- SEC-C4 DB: run `db-verify` encryption + plaintext scan
- SEC-C5 `/actuator/env`, `/actuator/heapdump`, `/actuator/beans`,
  `/actuator/mappings`, `/swagger-ui`, `/v3/api-docs` → 401/404 in TEST
  unless documented
- SEC-C6 security headers on responses (`Strict-Transport-Security`,
  `X-Content-Type-Options`, `Cache-Control: no-store` on sensitive data)
- SEC-C7 TLS only on base_url; `http://` redirect or refused

### D. Secrets & code (supply chain)
- SEC-D1 `gitleaks detect --source workspace/<service> --report-path ...`
  (fallback: grep patterns from `context/sensitive-patterns.json` across the
  repo incl. `application*.yml`, `k8s/`, `azure-pipelines*.yml`, history
  `git log -p | grep`)
- SEC-D2 `semgrep --config p/owasp-top-ten --config p/java --config p/spring`
  on `src/main/java` (fallback: grep for `MessageDigest.getInstance("MD5")`,
  `DES`, `ECB`, `Random(` for tokens, `permitAll()`, `csrf().disable()`,
  `TrustAllStrategy`, `setHostnameVerifier`, `allowCredentials(true)` with `*`)
- SEC-D3 `trivy fs --scanners vuln workspace/<service>` (pom/gradle CVEs);
  fallback `mvn org.owasp:dependency-check-maven:check` if network allows
- SEC-D4 Dockerfile: non-root user, pinned base image, no secrets in
  `ENV`/`ARG`, no `curl | sh`; `trivy image <image>` if the registry is reachable

### E. Egress / network (your private-environment rule)
- SEC-E1 `python3 -I scripts/check_egress.py --repo workspace/<service> --allow context/environments.json`
  → lists every URL/IP/host in code, config, Dockerfile, k8s manifests,
  pipeline; flags public IPs, non-allowlisted public DNS names, `http://`,
  webhooks, telemetry/analytics SDKs, Maven repos outside the corporate
  mirror. Each public target = HIGH (CRITICAL if it carries data)
- SEC-E2 runtime: `kubectl get networkpolicy -n <ns> -o yaml` — is egress
  restricted? If no NetworkPolicy → MEDIUM (document)
- SEC-E3 runtime connections: `kubectl exec` is forbidden for you, so use
  `pods_log` + the service's own HTTP-client logs, and the `movii-oci` MCP (NSG rules,
  security lists and route tables of the qa subnet) to show no public destinations
- SEC-E4 service exposure: `kubectl get svc,ingress -n <ns>` — only the
  intended Service is behind the LB; no NodePort/LoadBalancer type on
  internal services
- SEC-E5 DB reachability: `db_host` resolves to a private IP only

### F. Kubernetes & runtime hardening
- SEC-F1 `kubectl get deploy <dep> -o yaml`: `runAsNonRoot`,
  `readOnlyRootFilesystem`, `allowPrivilegeEscalation:false`, drop
  capabilities, resources requests/limits set, liveness/readiness probes
- SEC-F2 secrets come from K8s Secrets / OCI Vault, not ConfigMap or env
  literals (`kubectl get deploy -o yaml | grep -i pass`)
- SEC-F3 image pulled by digest or immutable tag; `imagePullPolicy`
- SEC-F4 ServiceAccount token automount disabled unless needed; RBAC minimal

### G. Business-logic abuse (API6)
- SEC-G1 replay of a signed/authorized request (same idempotency key or
  without) → no double debit
- SEC-G2 race: 10 parallel withdrawals of full balance → only one succeeds
  (verify ledger in DB)
- SEC-G3 limits bypass by splitting amounts / changing currency / timezone
  tricks on daily limits

## Execution rules
- Non-destructive payloads only; one proof request per case; TEST only.
- Save every probe as `evidence/SEC-xxx/request.json` + `response.json`
  (masked) + `notes.md`. Scanner outputs go to `docs/<service>/<run>/security/`.
- Severity per `context/severity-matrix.md`; map each finding to OWASP API
  Top 10 2023 + CWE.
- Output `security/security-results.md` + `index.csv` status updates.
