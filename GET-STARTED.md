# QA Tester Agent — Team Guide

A Claude Code agent that end-to-end tests our Java/Spring Boot services. You give
it an Azure DevOps repo URL; it clones the service, learns it from its `/docs`,
designs an **extensive** test suite (hundreds of functional/product cases plus
security, code-level, endpoint, non-functional and stress), asks you for any
TEST inputs it needs, runs what it can, and writes Excel + Word + HTML reports —
all read-only against TEST, never prod.

This guide has three parts:
- **Part 1 — Publish** (the owner does this once, to share the agent)
- **Part 2 — Install** (each QA teammate does this once, on their machine)
- **Part 3 — Use it** (day-to-day testing)

> There is also a deeper technical reference in `README.md`. This guide is the
> fast path.

---

## Part 1 — Publish the agent (owner, once)

**Yes — put it in a Git repo.** That is exactly how a Claude Code agent is
shared: the agent *is* this folder (CLAUDE.md + `.claude/` + `scripts/` +
`context/`). A teammate "imports" it by cloning the repo and opening the folder
in Claude Code — the `CLAUDE.md` turns Claude into the QA agent automatically.

Recommended home: an Azure DevOps repo next to our other tooling, e.g.
`https://dev.azure.com/movii/transversal/_git/qa-tester-agent`.

```bash
cd "D:\Claude-Projects\QA Agent\qa-agent\qa-agent"
git init
git add .
git commit -m "QA Tester Agent"
git branch -M main
git remote add origin https://dev.azure.com/movii/transversal/_git/qa-tester-agent
git push -u origin main
```

**What gets shared vs. what stays private** (already handled by `.gitignore`):
- ✅ Shared: `CLAUDE.md`, `.claude/`, `scripts/`, `context/`, `.mcp.json`,
  `.env.example`, `requirements.txt`, the guides.
- 🚫 Never committed: `.env` (secrets), and the per-run outputs
  `workspace/`, `docs/<svc>/<run>/`, `test-cases/<svc>/<run>/`.

Before the first push, open `context/environments.json` and confirm the TEST
hosts / namespaces / schemas and the Azure org/project are correct for us — that
file is the allowlist the agent is locked to.

To ship an update later: commit and push; teammates run `git pull`.

---

## Part 2 — Install (each teammate, once)

### 2.1 Prerequisites
- **Claude Code**, signed in with access to **Claude Opus** (the agent pins
  `claude-opus-5-5` in `.claude/settings.json`).
- **VPN** access (the MOVii observability plugins and TEST hosts need it).
- Access to the **movii-marketplace** Azure repo (for the plugins) and an
  **Azure DevOps PAT** (scopes: Code *Read*, Build *Read & execute*, Work Items
  *Read & write*, Test Management *Read & write*).
- **CLI tools:** `git`, Java 17+, Node 18+, Python 3.10+, `jq`, `kubectl`
  (TEST-cluster kubeconfig only), `mysql` client. Optional: `newman`
  (`npm i -g newman newman-reporter-htmlextra`), `k6`, Docker, `semgrep`,
  `gitleaks`, `trivy`.
- **Windows:** have Git Bash available. If `python3` is the Microsoft Store stub,
  add a shim once:
  ```bash
  printf '#!/usr/bin/env bash\nexec python "$@"\n' > ~/bin/python3 && chmod +x ~/bin/python3
  ```

### 2.2 Get the agent and its Python deps
```bash
git clone https://dev.azure.com/movii/transversal/_git/qa-tester-agent
cd qa-tester-agent
pip install -r requirements.txt     # openpyxl, python-docx, markdown, cryptography
```

### 2.3 Fill in your secrets (TEST only)
```bash
cp .env.example .env
# edit .env: ADO PAT (raw + base64), TEST kubeconfig path, SELECT-only MySQL user, OCI profile
```
`.env` is git-ignored — it never leaves your machine. Everything in it is
TEST-scoped; do **not** put any production credential here.

### 2.4 Launch Claude Code from the folder, with the env loaded
```bash
set -a; source .env; set +a
claude
```
On first launch, **trust the folder** when asked. Claude Code then:
- loads `CLAUDE.md` (the agent), `.claude/settings.json` (model, permissions,
  safety hooks), and `.mcp.json` (Azure DevOps, Kubernetes, MySQL, k6);
- offers to install the **movii-marketplace** plugins (OCI, Loki, Mimir, Tempo,
  backend, RAG) declared in settings — accept them.
- Verify tools are connected: `claude mcp list`.

### 2.5 Optional external skill packs (nice-to-have, inside Claude Code)
```
/plugin marketplace add anthropics/skills
/plugin install document-skills@anthropic-agent-skills   # xlsx/pdf/docx/pptx reading of the repo's /docs
```
The agent works without these (it has fallbacks), but they improve doc parsing
and security scans.

---

## Part 3 — Use it (day-to-day)

Open the folder in Claude Code and paste the service repo URL with a plain
request:

```
https://dev.azure.com/movii/<project>/_git/<service>  — please do end-to-end testing of this service
```
Options you can add: `branch development`, `scope: functional + security only`,
`skip stress`, `just design the test cases` (design without executing).

What happens — the agent works in phases (it shows progress):
1. **Fetch & learn** — clones the repo, reads `/docs`, enumerates **every**
   endpoint, writes the machine contract.
2. **Design** — builds the extensive suite (functional/product cases are the
   bulk, each asserting the exact code + message, plus security/code/endpoint/
   non-functional/stress) and produces **`test-plan.xlsx`** for your review.
3. **Ask for inputs** — if cases need a TEST value (client key, a test MSISDN +
   PIN, an OTP, document fields…), it **asks you** via `variables-request.md`
   instead of silently skipping. Give it the values and it runs those cases;
   say you can't and it marks them clearly as blocked.
4. **Execute** — baseline + functional + DB + logs + security + stress, saving
   request/response evidence for every case.
5. **Report** — writes the deliverables below and a chat summary with the
   verdict and top findings.

### What you get (per run, under `docs/<service>/<run>/` and `test-cases/<service>/<run>/`)
| File | What it is |
|---|---|
| `test-plan.xlsx` | The designed cases to review **before** running (GT-GP-F05 columns: Componente, Método, Tipo de prueba, Enfoque, Expected result) |
| `test-cases.xlsx` | The same cases **with results** after the run |
| `QA-REPORT-full.html` | One self-contained dashboard — tabs for Overview, Cases, Request/Response, Stress, Findings, Coverage, Regression |
| `QA-REPORT.md` / `.html` | The written report |
| `word/*.docx` | Word copies of results + evidence |
| `variables-request.md` | The TEST inputs the agent asked you for |
| `coverage.*`, `regression.*` | Endpoint/field/error coverage, and diff vs the previous run |

### Reviewing the cases your teammate (or the agent) designed
Open `test-cases/<service>/<run>/test-plan.xlsx`. If you spot missing coverage,
tell the agent ("add cases for X") — it will extend the suite. Case IDs are
stable across runs, so the Regression tab shows exactly what changed.

---

## Updating the agent
```bash
cd qa-tester-agent
git pull
pip install -r requirements.txt   # in case deps changed
```

## Safety (why this can't touch production)
TEST-scoped credentials only; fail-closed **hooks** block `git push/commit`,
any `kubectl`/SQL write, any host/namespace/schema not in
`context/environments.json`, anything matching `prod|prd|production|live`, and
writes outside `test-cases/ docs/ workspace/`. The prompt rules in `CLAUDE.md`
are the last layer, not the only one.

## Quick troubleshooting
| Symptom | Fix |
|---|---|
| `claude mcp list` shows a server down | Check `.env` is sourced in the same shell; re-run `set -a; source .env; set +a; claude` |
| Plugins didn't install | `/plugin` → trust the `movii-marketplace`; ensure VPN + access to the marketplace repo |
| Python/Excel step fails | `pip install -r requirements.txt`; on Windows add the `python3` shim (2.1) |
| Clone fails (401) | PAT expired or missing Code *Read*; refresh `ADO_PAT` in `.env` |
| A test is "BLOCKED – needs X" | The agent asked for a TEST input in `variables-request.md`; provide it and ask it to re-run those cases |
