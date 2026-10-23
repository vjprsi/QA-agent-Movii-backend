# qa-agent — end-to-end QA tester for Java/Spring Boot services

Open this folder in Claude Code, paste the Azure DevOps repo link of a service
and say *"please do end-to-end testing of this service"*. The agent clones the
repo, learns it from `/docs`, deploys it to its TEST namespace if needed,
designs functional / regression / non-functional / security / stress test
cases, executes them, verifies MySQL and the pod logs, and writes a complete
evidence report under `docs/<service>/<run>/`.

```
qa-agent/
├─ CLAUDE.md                 ← the agent: identity, inputs, 6-phase workflow, hard rules, summary format
├─ .mcp.json                 ← tool connections: Azure DevOps, Kubernetes (read-only), MySQL (read-only), k6 (OCI/logs/metrics/traces come from MOVii plugins)
├─ .env.example              ← secrets template (copy to .env, never commit)
├─ .claude/
│  ├─ settings.json          ← model (Opus 5.5), allow/ask/deny permissions, hooks
│  ├─ agents/                ← subagents: code-analyst, security-tester, stress-tester, report-writer
│  ├─ skills/                ← procedures: preflight-check, read-variables, deploy-service, generate-test-cases,
│  │                            functional-tests, db-verify, log-audit, security-tests, stress-tests, evidence-report
│  └─ hooks/                 ← hard guards (via run_hook.sh, fail-closed): guard_bash, guard_mysql, guard_k8s, guard_readonly_mcp, guard_write_paths
├─ context/                  ← environments.json (TEST allowlist), conventions, variables schema, test-case template,
│                               severity matrix, sensitive-data regexes
├─ scripts/                  ← deterministic helpers the skills call (python/bash/k6)
├─ workspace/                ← cloned repos (agent may write only to workspace/<svc>/qa/)
├─ test-cases/<svc>/<run>/   ← cases + index.csv + test-plan.xlsx (review before run) + test-cases.xlsx (with results)
└─ docs/<svc>/<run>/         ← evidence + descriptor.json + coverage.* + regression.* + QA-REPORT.md/.html + QA-REPORT-full.html (tabs: everything) + word/*.docx
```

## What each layer contributes to the harness

| Layer | File(s) | Role |
|---|---|---|
| Identity & process | `CLAUDE.md` | System prompt: who the agent is, what it receives, the phases, the rules |
| Hands | `.mcp.json` | External systems it can reach (each server = one credential, scoped to TEST) |
| Model & limits | `.claude/settings.json` | `claude-opus-5-5`; what is allowed / needs a yes / is denied; hooks wiring |
| Deterministic guards | `.claude/hooks/*.py` | Run before every Bash / MySQL / K8s / Write call; exit 2 blocks the call regardless of what the model decided |
| Specialists | `.claude/agents/*.md` | Subagents with their own context window and narrower tools |
| Know-how | `.claude/skills/*/SKILL.md` | Loaded only when needed; exact commands and judgement rules per phase |
| Facts | `context/*` | TEST allowlist, conventions, SLA defaults, regexes — edit per company, no prompt changes needed |
| Precision work | `scripts/*` | Parsing xlsx, scanning logs, k6 ladder, joins — things an LLM should not do by hand |

## Install (once per QA machine)

1. **Claude Code** with access to Claude Opus 5.5.
2. **CLI tools**: `git`, Java 17+, Maven/Gradle wrapper (comes with the repo), Node 18+,
   `npm i -g newman newman-reporter-htmlextra`, [k6](https://grafana.com/docs/k6/latest/set-up/install-k6/),
   `kubectl` (kubeconfig for the **TEST** OKE cluster only), `mysql` client, `jq`, Python 3.10+ with
   `pip install -r requirements.txt` (openpyxl, python-docx, markdown, cryptography — needed for the
   Excel/Word/HTML deliverables and the AES harness). Optional but recommended for security: `semgrep`, `gitleaks`, `trivy`,
   `az` CLI, `oci` CLI, Docker (for the k6 MCP).
   **Windows:** run Claude Code with Git Bash available. `python3` is usually the Microsoft Store
   stub, so add a shim once: `printf '#!/usr/bin/env bash\nexec python "$@"\n' > ~/bin/python3 && chmod +x ~/bin/python3`.
   `pip install --user uv` puts `uvx` in `%APPDATA%\Python\Python3xx\Scripts` — add that folder to PATH.
   Hooks run through `.claude/hooks/run_hook.sh`, which finds a working Python itself and **blocks the
   call** if none is found or a guard crashes (fail-closed).
3. **Secrets**: `cp .env.example .env`, fill it, then start Claude Code with the variables exported:
   ```bash
   set -a; source .env; set +a; claude
   ```
4. **Allowlist**: edit `context/environments.json` — TEST hosts, namespaces, schemas, pipeline pattern.
   Nothing outside this file can be touched; hooks enforce it.
5. **MCP servers** start automatically from `.mcp.json` (`claude mcp list` to verify):
   - Azure DevOps — Microsoft's `@azure-devops/mcp`, PAT auth, domains limited to core/repositories/pipelines/work-items/test-plans
   - Kubernetes — `kubernetes-mcp-server` with `--read-only`
   - MySQL — `@benborla29/mcp-server-mysql` with all write flags `false` **and** a SELECT-only DB user
   - k6 — `grafana/mcp-k6` via Docker (optional; the stress skill also works with the k6 CLI)

   **MOVii marketplace plugins** (declared in `.claude/settings.json` → `extraKnownMarketplaces` +
   `enabledPlugins`; Claude Code offers to install them when you trust the folder). All are HTTP,
   read-only, and **need the VPN**:
   - `movii-oci-mcp` — OCI read-only: OKE, OCIR, Vault metadata, VCN/NSG, API Gateway, LB, logging (compartments dev|qa)
   - `mcp-movii-logs` / `mcp-movii-metrics` / `mcp-movii-traces` — Loki (LogQL), Mimir (PromQL), Tempo (TraceQL)
   - `movii-backend-mcp` — backend components and docs; `movii-rag-qa-mcp` — semantic search over the QA knowledge base
   Their tools are named `mcp__plugin_<plugin>_<server>__<tool>`; `guard_readonly_mcp.py` checks every call.
6. **External skill packs** (inside Claude Code, `/plugin` commands):
   ```
   /plugin marketplace add anthropics/skills
   /plugin install document-skills@anthropic-agent-skills      # xlsx, pdf, docx, pptx → reads the repo's /docs
   /plugin marketplace add https://github.com/AgentSecOps/SecOpsAgentKit.git
   /plugin install <sast-semgrep | secrets-gitleaks | sca-trivy | dast-zap | dast-nuclei | container-hadolint | sbom-syft>
   /plugin marketplace add trailofbits/skills                   # static-analysis (Semgrep/CodeQL/SARIF), supply-chain audit
   /plugin menu                                                  # pick the plugins you want
   ```
   The agent's own skills reference these by name as optional reinforcement; everything still runs
   with grep-based fallbacks when they are not installed.

## Run

```
> https://dev.azure.com/<org>/<project>/_git/wallet-core  — please do end-to-end testing of this service
```
Optional: `branch feature/x`, `scope: functional+security only`, `skip stress`.

What happens (see `CLAUDE.md`): clone → read `/docs` → parse `variables.xlsx` → code analysis → **preflight**
(missing variables/access are listed and asked, never fatal) → deploy via pipeline if `deployed=no` →
test-case design (counts shown) → Newman functional/regression → DB verification → log audit →
security → stress ladder → `QA-REPORT.md/.html` + chat summary.

## What the repo under test must provide in `/docs`

- Specifications, flows, diagrams, DB architecture (md/pdf/docx/pptx/png).
- `postman/<name>.postman_collection.json` (+ optional environment). Request names may start with a
  test id (`REG-001 Get balance`) so results map 1:1.
- `variables.xlsx` — sheet `variables` (`key | value | required | category | description`) and optional
  sheet `test_data`. Full key list in `context/variables-schema.md`. Key switches:
  `deployed = yes|no`, `deploy_pipeline`, `stress_tps_ladder = 1,3,1,5,2,3`.

## Safety model (why this cannot hurt production)

1. **Credentials are TEST-scoped**: PAT limited scopes, kubeconfig of the TEST cluster only, SELECT-only DB user,
   OCI profile on the TEST compartment. Even a wrong decision has nothing to act on.
2. **Hooks** block `git push/commit`, every `kubectl` write, every SQL write, any host/namespace/schema not in
   `context/environments.json`, anything containing `prod|prd|production|live`, and writes outside
   `test-cases/ docs/ workspace/<svc>/qa/`.
3. **Permissions** in `settings.json` deny the same things at the tool layer and require a yes for pipeline runs
   and Azure DevOps writes.
4. **Prompt rules** in `CLAUDE.md` are the last layer, not the first.

## Later

- Point `docs/` at a shared drive or OCI Object Storage bucket (add an upload step at the end of
  `evidence-report`); `SUMMARY.json` is produced per run for dashboards.
- Add service-specific conventions to `context/conventions.md` instead of editing prompts.
