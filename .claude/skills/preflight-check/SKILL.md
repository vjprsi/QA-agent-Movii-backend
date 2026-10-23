---
name: preflight-check
description: Gate before any execution. Verifies CLI tools, MCP access, docs, variables, Postman collection, cluster/DB/pipeline reachability and produces preflight.md with READY/MISSING items and which tests each missing item blocks. Never fails the run.
---
# preflight-check

Run:
```bash
python3 -I scripts/preflight.py --service "<service>" --run "<run>" \
  --repo "workspace/<service>" --vars "docs/<service>/<run>/variables.json" \
  --out "docs/<service>/<run>/preflight.md"
```
The script checks (each line READY / MISSING / WARN):

| Area | Check |
|---|---|
| Tools | git, java, mvn or gradle wrapper, node, newman, k6, kubectl, mysql client, python3 + openpyxl, jq; optional semgrep, gitleaks, trivy |
| Repo | cloned, branch/commit, `/docs` present, spec files found, Postman collection found, variables file found |
| Variables | every `required` key present (from `variables-check.json`), unresolved `{{postman}}` vars, `deployed` value |
| Azure DevOps | `mcp__azure-devops__core_list_projects` works; pipeline `deploy_pipeline` exists (`pipelines_definition list`) when `deployed=no` |
| Kubernetes | `kubectl --context <ctx> get deploy -n <k8s_namespace>` works; deployment found; pods status |
| MySQL | `mysql -h <db_host> -u $MYSQL_TEST_RO_USER -e "SELECT 1"` works; schemas in `db_schema` exist; user has SELECT only (`SHOW GRANTS`) |
| Service | `curl -s <base_url><health_path>` (only meaningful if deployed) |
| Allowlist | base_url host, db_host, k8s_namespace all match `context/environments.json` |

Then **you** (the agent) add to `preflight.md` the MCP-side checks the script
cannot do (call the MCP tools and record the outcome), and the mapping
**missing item → blocked test categories**, e.g.:

```
MISSING  test_otp           → blocks FUN-004, FUN-005 (OTP flows), REG-002
MISSING  stress_tps_ladder  → blocks all STR-*
MISSING  kubectl access     → blocks log-audit, stress monitoring (stress NOT RUN)
```

Decision rules:
- Any CRITICAL access missing (repo, base_url unreachable after deploy) → stop
  after reporting; ask the tester.
- Otherwise → post the MISSING list to the tester as a question, and
  **continue immediately** with all non-blocked phases. When the tester
  answers, re-run this skill and unblock.
- Never ask for a value you can read from the docs or infer safely (e.g.
  `health_path` default). Never guess credentials.
