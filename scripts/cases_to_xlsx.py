#!/usr/bin/env python3
"""Build a reviewable Excel workbook of the test suite for a run.

Reads  test-cases/<service>/<run>/index.csv  and every per-case Markdown file
under the category folders, and writes  test-cases/<service>/<run>/test-cases.xlsx
with:
  - a "Summary" sheet: counts per category x status, plus prepared/missing view;
  - one sheet per category (functional, regression, non-functional, security,
    stress) with one row per case and the parsed fields a QA reviewer needs.

The workbook is what the QA team opens to see what is prepared, what each case
checks, and its current status (PASS / FAIL / BLOCKED / NOT RUN). It carries no
secrets: it reproduces only the case Markdown, which is already masked.

Usage:
  python -I scripts/cases_to_xlsx.py --run-dir test-cases/<service>/<run>
  (optional --out <path.xlsx>)
"""
import argparse
import csv
import glob
import os
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

CATEGORIES = ["functional", "regression", "non-functional", "security", "stress"]

# Design columns: what the QA team reviews BEFORE execution (the test plan).
# (header, parsed-key or @section or _derived)
# Columns mirror the team's GT-GP-F05 "Casos" tab (Componente, Metodo, Tipo de
# prueba, Enfoque) so the export drops straight into their workflow.
PLAN_COLUMNS = [
    ("Test #", "_id"),
    ("Componente", "_componente"),
    ("Priority", "priority"),
    ("Title", "_title"),
    ("Metodo / Endpoint", "endpoint"),
    ("Tipo de prueba", "_tipo"),
    ("Enfoque", "_enfoque"),
    ("Traces to", "traces to"),
    ("Preconditions", "preconditions"),
    ("Test data", "test data"),
    ("Requires vars", "requires vars"),
    ("Steps (what is executed)", "@steps"),
    ("Expected result", "@expected result"),
]
# Execution columns appended in full mode: what actually happened.
EXEC_COLUMNS = [
    ("Status", "_status"),
    ("Observed", "@actual result"),
    ("Severity", "severity"),
]

# per-header width
WIDTHS = {
    "Test #": 14, "Componente": 24, "Priority": 9, "Title": 34,
    "Metodo / Endpoint": 26, "Tipo de prueba": 14, "Enfoque": 16,
    "Traces to": 26, "Preconditions": 24, "Test data": 20, "Requires vars": 22,
    "Steps (what is executed)": 48, "Expected result": 48,
    "Status": 11, "Observed": 42, "Severity": 10,
}

# category -> Enfoque (GT-GP-F05)
ENFOQUE = {
    "functional": "Funcional", "security": "Vulnerabilidad",
    "stress": "Prueba de carga", "regression": "Regresión",
    "non-functional": "No funcional",
}


def derive_gtgp(c, cat, service):
    """Fill the GT-GP-F05 derived columns on a parsed case."""
    c["_componente"] = service
    c["_enfoque"] = ENFOQUE.get(cat, cat)
    auto = str(c.get("automation", "")).strip().lower()
    c["_tipo"] = "Manual" if auto in ("manual", "no", "human") else "Automatizado"

STATUS_FILL = {
    "PASS": "C8E6C9",
    "FAIL": "FFCDD2",
    "BLOCKED": "E1BEE7",
    "NOT RUN": "ECEFF1",
    "UNVERIFIED": "E1BEE7",
}
HEAD_FILL = PatternFill("solid", fgColor="37474F")
HEAD_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(bold=True, size=14)


def parse_case(path):
    """Return {parsed table fields} + {@section: text} + _id/_title."""
    text = open(path, encoding="utf-8").read()
    out = {}
    m = re.search(r"^#\s+(.*)$", text, re.M)
    out["_title_line"] = m.group(1).strip() if m else os.path.basename(path)
    # ID and short title from "# FUN-019 — short title"
    tm = re.match(r"\s*([A-Z]+-\d+)\s*[—-]\s*(.*)", out["_title_line"])
    out["_id"] = tm.group(1) if tm else os.path.splitext(os.path.basename(path))[0]
    out["_title"] = tm.group(2).strip() if tm else out["_title_line"]
    # key/value table rows: | key | value |
    for k, v in re.findall(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$", text, re.M):
        key = k.strip().lower()
        if key in ("field", "") or re.fullmatch(r":?-{2,}:?", key):
            continue
        out[key] = v.strip()
    # dashed bullet fields: "- Key: value" (common lightweight case style)
    for k, v in re.findall(r"^\s*[-*]\s*([A-Za-z][\w /]+?)\s*:\s*(.*?)\s*$", text, re.M):
        key = k.strip().lower()
        if key and key not in out:
            out[key] = v.strip()
    # ## sections
    for sec, body in re.findall(r"^##\s+(.+?)\s*$\n(.*?)(?=^##\s|\Z)", text, re.M | re.S):
        out["@" + sec.strip().lower()] = body.strip()
    return out


def load_index(run_dir):
    idx = {}
    p = os.path.join(run_dir, "index.csv")
    if os.path.exists(p):
        for row in csv.DictReader(open(p, encoding="utf-8")):
            idx[row["id"]] = row
    return idx


def collect(run_dir, service="service"):
    idx = load_index(run_dir)
    cases = {c: [] for c in CATEGORIES}
    for cat in CATEGORIES:
        for f in sorted(glob.glob(os.path.join(run_dir, cat, "*.md"))):
            c = parse_case(f)
            row = idx.get(c["_id"], {})
            c["_category"] = cat
            if not c.get("priority"):
                c["priority"] = row.get("priority", "")
            if not c.get("endpoint"):
                # prefer index.csv; else derive the first HTTP verb+path from the steps
                ep = row.get("endpoint", "")
                if not ep:
                    m = re.search(r"\b(GET|POST|PUT|DELETE|PATCH)\s+(/[\w/{}.-]*)",
                                  c.get("@steps", "") + " " + c.get("traces to", ""))
                    ep = f"{m.group(1)} {m.group(2)}" if m else ""
                c["endpoint"] = ep
            c["_status"] = (row.get("status") or c.get("@actual result_status") or "NOT RUN").strip()
            # status may also be embedded in actual-result section
            sm = re.search(r"Status:\s*([A-Z ]+)", c.get("@actual result", ""))
            if sm and (not row.get("status")):
                c["_status"] = sm.group(1).strip()
            if not c.get("traces to"):
                c["traces to"] = row.get("traces_to", "")
            if not c.get("requires vars"):
                c["requires vars"] = row.get("requires_vars", "")
            if not c.get("automation"):
                c["automation"] = row.get("automation", "")
            # fall back to dashed-bullet fields when the richer sections are absent
            if not c.get("@expected result"):
                c["@expected result"] = c.get("expected result", "") or c.get("expected", "")
            if not c.get("@steps"):
                c["@steps"] = c.get("steps", "")
            derive_gtgp(c, cat, service)
            # severity from actual-result if not a table field
            if not c.get("severity"):
                vm = re.search(r"Severity:?\s*\**\s*([A-Za-z]+)", c.get("@actual result", ""))
                if vm and vm.group(1).upper() in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
                    c["severity"] = vm.group(1).upper()
            cases[cat].append(c)
    return cases, idx


def style_header(ws, ncol):
    for j in range(1, ncol + 1):
        cell = ws.cell(row=1, column=j)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = Alignment(vertical="center")


def write_category_sheet(wb, cat, cases, columns):
    ws = wb.create_sheet(cat[:31])
    headers = [h for h, _ in columns]
    ws.append(headers)
    style_header(ws, len(headers))
    for c in cases:
        ws.append([c.get(key, "") for _, key in columns])
    for j, (h, _) in enumerate(columns, 1):
        ws.column_dimensions[get_column_letter(j)].width = WIDTHS.get(h, 20)
    status_col = headers.index("Status") + 1 if "Status" in headers else None
    for i in range(2, ws.max_row + 1):
        for j in range(1, len(headers) + 1):
            ws.cell(row=i, column=j).alignment = Alignment(wrap_text=True, vertical="top")
        if status_col:
            st = str(ws.cell(row=i, column=status_col).value or "").upper()
            if st in STATUS_FILL:
                ws.cell(row=i, column=status_col).fill = PatternFill("solid", fgColor=STATUS_FILL[st])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{ws.max_row}"
    return ws


def write_summary(wb, cases, service, run, mode):
    ws = wb.create_sheet("Summary", 0)
    kind = "Test plan (for review — not yet executed)" if mode == "plan" else "Execution report"
    ws["A1"] = f"{kind} — {service}"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Run {run}"
    ws["A2"].font = Font(italic=True, color="555555")
    if mode == "plan":
        ws["A3"] = ("This workbook lists every test case the agent designed for this service: "
                    "test number, endpoint, steps and the expected result. Review coverage here "
                    "before execution. Add rows for anything your team wants covered manually; "
                    "the execution report (full mode) is produced after the run with results.")
        ws["A3"].font = Font(italic=True, color="555555")
        ws["A3"].alignment = Alignment(wrap_text=True)
        ws.append([]) ; ws.append([])
    statuses = ["PASS", "FAIL", "BLOCKED", "NOT RUN", "UNVERIFIED"]
    header = ["Category", "Planned cases"] if mode == "plan" else ["Category", "Total"] + statuses
    r0 = ws.max_row + 2
    for j, h in enumerate(header, 1):
        ws.cell(row=r0, column=j, value=h).fill = HEAD_FILL
        ws.cell(row=r0, column=j).font = HEAD_FONT
    r = r0 + 1
    totals = {s: 0 for s in statuses}
    gtot = 0
    for cat in CATEGORIES:
        cs = cases[cat]
        ws.cell(row=r, column=1, value=cat)
        ws.cell(row=r, column=2, value=len(cs))
        if mode != "plan":
            counts = {s: 0 for s in statuses}
            for c in cs:
                st = c["_status"].upper()
                counts[st] = counts.get(st, 0) + 1
                totals[st] = totals.get(st, 0) + 1
            for j, s in enumerate(statuses, 3):
                ws.cell(row=r, column=j, value=counts.get(s, 0))
        gtot += len(cs)
        r += 1
    ws.cell(row=r, column=1, value="TOTAL").font = Font(bold=True)
    ws.cell(row=r, column=2, value=gtot).font = Font(bold=True)
    if mode != "plan":
        for j, s in enumerate(statuses, 3):
            ws.cell(row=r, column=j, value=totals.get(s, 0)).font = Font(bold=True)
    for j, w in enumerate([16, 14, 8, 8, 10, 10, 12], 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    if mode != "plan":
        ws.cell(row=r + 2, column=1, value="Status legend: PASS=verified ok  FAIL=defect  "
                "BLOCKED=needs input/access  NOT RUN=designed, not executed  "
                "UNVERIFIED=no evidence").font = Font(italic=True, color="555555")
    return ws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, help="test-cases/<service>/<run>")
    ap.add_argument("--mode", choices=["plan", "full"], default="full",
                    help="plan = design-time review workbook (no results); "
                         "full = execution report with Status/Observed/Severity")
    ap.add_argument("--out")
    args = ap.parse_args()
    run_dir = os.path.normpath(args.run_dir)
    parts = run_dir.replace("\\", "/").split("/")
    service = parts[-2] if len(parts) >= 2 else "service"
    run = parts[-1]
    columns = PLAN_COLUMNS if args.mode == "plan" else PLAN_COLUMNS + EXEC_COLUMNS
    cases, _ = collect(run_dir, service)
    wb = Workbook()
    wb.remove(wb.active)
    write_summary(wb, cases, service, run, args.mode)
    for cat in CATEGORIES:
        if cases[cat]:
            write_category_sheet(wb, cat, cases[cat], columns)
    default = "test-plan.xlsx" if args.mode == "plan" else "test-cases.xlsx"
    out = args.out or os.path.join(run_dir, default)
    wb.save(out)
    total = sum(len(v) for v in cases.values())
    print(f"wrote {out}  (mode={args.mode}, {total} cases, "
          f"{sum(1 for c in CATEGORIES if cases[c])} sheets)")


if __name__ == "__main__":
    main()
