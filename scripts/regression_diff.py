#!/usr/bin/env python3
"""Regression tracking across runs of the SAME service.

Compares the current run's cases to the previous run's (by stable test id) and
classifies each: fixed (was FAIL/BLOCKED, now PASS), regressed (was PASS, now
FAIL), still-failing, new, removed, unchanged. Stable ids (STD-* baseline + the
agent keeping business ids stable per service) make this meaningful.

Reads test-cases/<svc>/<run>/index.csv for each run; the previous run is the
most recent run folder before the current under test-cases/<svc>/.

Writes docs/<svc>/<run>/regression.json and regression.md. The HTML dashboard
reads regression.json for its Regression tab.

Usage:
  python -I scripts/regression_diff.py --service <svc> --run <run> \
     --cases-root test-cases --docs-root docs
  (or --prev-run to force a baseline)
"""
import argparse
import csv
import json
import os


def load_run(cases_root, svc, run):
    p = os.path.join(cases_root, svc, run, "index.csv")
    out = {}
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding="utf-8")):
            out[r["id"]] = {"status": (r.get("status") or "").upper(), "title": r.get("title", ""),
                            "category": r.get("category", "")}
    return out


def list_runs(cases_root, svc):
    d = os.path.join(cases_root, svc)
    if not os.path.isdir(d):
        return []
    return sorted(x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--prev-run")
    ap.add_argument("--cases-root", default="test-cases")
    ap.add_argument("--docs-root", default="docs")
    args = ap.parse_args()

    runs = list_runs(args.cases_root, args.service)
    prev = args.prev_run
    if not prev:
        earlier = [r for r in runs if r < args.run]
        prev = earlier[-1] if earlier else None

    cur = load_run(args.cases_root, args.service, args.run)
    out_dir = os.path.join(args.docs_root, args.service, args.run)
    os.makedirs(out_dir, exist_ok=True)

    if not prev:
        result = {"service": args.service, "run": args.run, "previous_run": None,
                  "note": "No previous run for this service - this is the baseline.",
                  "counts": {}, "changes": []}
        json.dump(result, open(os.path.join(out_dir, "regression.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        open(os.path.join(out_dir, "regression.md"), "w", encoding="utf-8").write(
            f"# Regression vs previous run\n\nNo previous run for **{args.service}** - this run is the baseline.\n")
        print("regression: no previous run (baseline) -> regression.json")
        return

    old = load_run(args.cases_root, args.service, prev)
    fixed, regressed, still_failing, new, removed, unchanged = [], [], [], [], [], []
    for cid in sorted(set(cur) | set(old)):
        o, c = old.get(cid), cur.get(cid)
        if o and not c:
            removed.append({"id": cid, "was": o["status"], "title": o["title"]})
        elif c and not o:
            new.append({"id": cid, "now": c["status"], "title": c["title"]})
        else:
            os_, cs_ = o["status"], c["status"]
            rec = {"id": cid, "was": os_, "now": cs_, "title": c["title"]}
            if os_ != "PASS" and cs_ == "PASS":
                fixed.append(rec)
            elif os_ == "PASS" and cs_ == "FAIL":
                regressed.append(rec)
            elif cs_ == "FAIL":
                still_failing.append(rec)
            else:
                unchanged.append(rec)
    counts = {"fixed": len(fixed), "regressed": len(regressed), "still_failing": len(still_failing),
              "new": len(new), "removed": len(removed), "unchanged": len(unchanged)}
    result = {"service": args.service, "run": args.run, "previous_run": prev, "counts": counts,
              "regressed": regressed, "fixed": fixed, "still_failing": still_failing,
              "new": new, "removed": removed}
    json.dump(result, open(os.path.join(out_dir, "regression.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    def tbl(title, rows, cols):
        if not rows:
            return [f"**{title}:** none", ""]
        out = [f"**{title}:** {len(rows)}", "", "| " + " | ".join(cols) + " |",
               "|" + "|".join(["---"] * len(cols)) + "|"]
        for r in rows:
            out.append("| " + " | ".join(str(r.get(c.lower().replace(" ", "_"), r.get(c, ""))) for c in cols) + " |")
        return out + [""]
    md = [f"# Regression vs previous run", "",
          f"Service **{args.service}** — current `{args.run}` vs previous `{prev}`.", "",
          f"Fixed {counts['fixed']} · Regressed {counts['regressed']} · Still failing {counts['still_failing']} · "
          f"New {counts['new']} · Removed {counts['removed']} · Unchanged {counts['unchanged']}", ""]
    md += tbl("Regressed (PASS -> FAIL)", [{"id": r["id"], "title": r["title"]} for r in regressed], ["id", "title"])
    md += tbl("Fixed (was failing -> PASS)", [{"id": r["id"], "title": r["title"]} for r in fixed], ["id", "title"])
    md += tbl("Still failing", [{"id": r["id"], "title": r["title"]} for r in still_failing], ["id", "title"])
    md += tbl("New cases", [{"id": r["id"], "title": r["title"]} for r in new], ["id", "title"])
    md += tbl("Removed cases", [{"id": r["id"], "title": r["title"]} for r in removed], ["id", "title"])
    open(os.path.join(out_dir, "regression.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"regression vs {prev}: fixed {counts['fixed']}, regressed {counts['regressed']}, "
          f"still-failing {counts['still_failing']}, new {counts['new']}, removed {counts['removed']} -> regression.json")


if __name__ == "__main__":
    main()
