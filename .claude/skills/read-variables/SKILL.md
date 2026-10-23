---
name: read-variables
description: Clone the service repo from Azure DevOps and parse /docs/variables*.xlsx (and the Postman collection) into variables.json + test_data.json, masking secrets and listing missing keys. Use at the start of Phase A.
---
# read-variables

## 1. Clone (never print the PAT)
```bash
# repo URL: https://dev.azure.com/<org>/<project>/_git/<repo>
REPO_URL="<url>" ; SERVICE="<repo>" ; BRANCH="<branch or empty>"
AUTH_URL="${REPO_URL/https:\/\//https://pat:${ADO_PAT}@}"
git clone --quiet ${BRANCH:+--branch "$BRANCH"} "$AUTH_URL" "workspace/$SERVICE" 2>&1 | sed "s/${ADO_PAT}/<redacted>/g"
git -C "workspace/$SERVICE" rev-parse --short HEAD
mkdir -p "workspace/$SERVICE/qa"     # the only writable place inside the repo
```
If the clone fails (401/403) → report "Azure DevOps PAT missing or without
Code(Read) scope" in preflight; do not retry with guessed credentials.
Alternative when git is not possible: `mcp__azure-devops__repo_file`
(`list_directory` / `get_content`) to read `/docs` and source files directly.

## 2. Locate inputs
```bash
ls -R workspace/$SERVICE/docs
```
Expected: specs (md/pdf/docx), diagrams, DB architecture, `postman/*.json`,
`variables*.xlsx`. If `/docs` is missing → MISSING item "docs folder", you
can still analyse code but mark spec-traceability as unavailable.

## 3. Parse variables
```bash
python3 -I scripts/read_variables.py \
  --xlsx "workspace/$SERVICE/docs/variables.xlsx" \
  --postman "workspace/$SERVICE/docs/postman/<collection>.json" \
  --out "docs/$SERVICE/<run>/"
```
Produces in the run folder:
- `variables.json`      — all keys (real values; file is local only)
- `variables.masked.md` — table for the report (secrets masked)
- `test_data.json`      — rows of the `test_data` sheet
- `variables-check.json` — `{"missing_required":[...], "unresolved_postman_vars":[...], "deployed": "yes|no|missing"}`

Read `variables-check.json` and carry its content into `preflight-check`.
Use `variables.json` values only through scripts/env vars; when you must show
one in chat or in a file, use the masked form.

## 4. Decide deployment
`deployed` = `yes` → Phase C is a health verification only.
`deployed` = `no` or missing → Phase C runs the deploy pipeline (ask if
`deploy_pipeline` is also missing).
