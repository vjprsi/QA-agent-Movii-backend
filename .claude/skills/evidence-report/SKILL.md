---
name: evidence-report
description: Structure and rules for the final QA-REPORT (Markdown + HTML) with evidence index, traceability matrix, findings and sign-off. Use in Phase F by the report-writer.
---
# evidence-report

Output: `docs/<service>/<run>/QA-REPORT.md` → `QA-REPORT.html`
(`python3 -I scripts/md_to_html.py QA-REPORT.md`). Everything referenced must
exist under the run folder; use relative links.

## Sections (keep this order)
1. **Cover** — service, repo URL, branch + commit, build/image tag,
   environment (TEST, namespace), run id, dates, tester name
   (`$QA_TESTER_NAME`), agent model, scope executed, scope excluded (why).
2. **Executive summary** — verdict (RELEASE-READY / NOT READY / READY WITH
   RISKS), 5–8 bullets, counts table
   (category × PASS/FAIL/BLOCKED/NOT RUN/UNVERIFIED).
3. **Service under test** — from `service-profile.md` (short), endpoint count,
   data model summary, deployment evidence (pipeline run id, before/after).
4. **Preflight & inputs** — `preflight.md` summary, variables (masked table),
   missing items and how they were handled.
5. **Test design** — approach per category, traceability matrix
   (spec section → test ids), coverage: endpoints covered / total, fields
   covered / total.
6. **Results by category** — functional, regression, non-functional,
   security, stress: each with a table (id, title, result, severity,
   evidence link) and narrative of failures.
7. **Findings register** — one row per FAIL: id, severity, title,
   endpoint/component, description, repro, impact, recommendation,
   OWASP/CWE (security), evidence link. Sorted by severity.
8. **Data protection review** — logs scan summary, DB encryption/plaintext
   summary, response exposure summary. Explicit "no sensitive data found" or
   the list.
9. **Performance** — ladder table, charts (`stress.html` link), SLA
   verdicts, resource and DB-connection behaviour, recommendations
   (pool size, limits, HPA).
10. **Environment & tooling** — tool versions (`newman -v`, `k6 version`,
    `kubectl version --client`), MCP servers used, limitations.
11. **Sign-off** — tester, date, open questions for the dev team,
    re-test plan.
12. **Appendix** — evidence index (tree of `evidence/`), raw files list.

## Word copies of the results (always)
The QA team needs the results in Word, not only JSON. After the report:
```bash
python3 -I scripts/results_to_docx.py --run-dir docs/<service>/<run>
```
→ `docs/<service>/<run>/word/`:
- `results-summary.docx` — every `results/*.json` suite as a table
  (id, title, status, severity, observed) + counts.
- `evidence.docx` — each `evidence/<ID>/reqN.json`+`respN.json` as readable
  request/response blocks.
- `stress-results.docx` — `stress/summary.json` as tables + the notes.
Inputs are already masked; the script only reformats them. Also build the
execution report workbook (the full version of the Phase-D test plan, with
results):
```bash
python3 -I scripts/cases_to_xlsx.py --run-dir test-cases/<service>/<run> --mode full
```
→ `test-cases.xlsx` (same layout as `test-plan.xlsx` plus Status / Observed /
Severity, colour-coded).

## Coverage + regression (always, before the dashboard)
```bash
python3 -I scripts/coverage_report.py --run-dir docs/<service>/<run> \
   --descriptor docs/<service>/<run>/descriptor.json
python3 -I scripts/regression_diff.py --service <service> --run <run>
```
- `coverage.json`/`coverage.md` — endpoint / field / error-code coverage,
  derived from the executed request/response evidence (not self-reported);
  cite the three numbers in the Executive summary and flag untested endpoints.
- `regression.json`/`regression.md` — fixed / regressed / still-failing / new
  vs the service's previous run (baseline note if none). **Call out any
  `regressed` (PASS→FAIL) prominently** — that is a new defect since last run.

## One-file HTML dashboard (always, after QA-REPORT.html exists)
Assemble everything into a single self-contained, tabbed page for the team
(Overview, Test cases, Request/Response, Stress, Findings, Coverage, Regression):
```bash
python3 -I scripts/build_html_report.py --run-dir docs/<service>/<run>
```
→ `docs/<service>/<run>/QA-REPORT-full.html` — opens from a file (no network),
light/dark, filterable case table that links into the request/response
evidence. Run it **after** `QA-REPORT.html` (it embeds that as the Overview
tab) and after the workbooks (it reads `index.csv` + case files + `evidence/`).
List `test-plan.xlsx`, `test-cases.xlsx`, the `word/` files and
`QA-REPORT-full.html` in the final chat summary.

## Rules
- Only facts from files. Missing evidence → `UNVERIFIED`, never PASS.
- Mask secrets/PII everywhere (`ab****yz`); the raw logs stay as files but
  the report warns they may contain PII if the scan found hits.
- Each finding has a recommendation a developer can act on and a re-test id.
- Also write `docs/<service>/<run>/SUMMARY.json` (counts, verdict, top
  findings) for later dashboards/drive upload.
- If the tester wants bugs in Azure DevOps: prepare the list (title,
  severity→priority, repro, evidence) and ask before `wit_create_work_item`.
