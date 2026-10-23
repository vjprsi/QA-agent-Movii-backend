#!/usr/bin/env python3
"""Turn Newman JSON reports into per-test evidence folders and update index.csv statuses.

Matching rule: a Newman request whose name starts with a test id (e.g. "FUN-012 transfer negative amount")
or has the id in its folder name is linked to that id. Unmatched requests are stored under evidence/_unmatched/.
"""
import argparse
import csv
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mask import mask_json_like, mask_in_text  # noqa: E402

ID_RE = re.compile(r"\b((?:FUN|REG|NFR|SEC|STR)-\d{3})\b")


def decode_body(b):
    if not b:
        return ""
    if isinstance(b, dict) and "data" in b:
        try:
            return bytes(b["data"]).decode("utf-8", "replace")
        except Exception:
            return str(b)
    return str(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--newman", nargs="+", required=True)
    ap.add_argument("--index", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--known-values", default="", help="variables.json for literal masking")
    a = ap.parse_args()

    known = []
    if a.known_values and os.path.exists(a.known_values):
        V = json.load(open(a.known_values, encoding="utf-8"))
        known = [v for k, v in V.items() if isinstance(v, str) and any(h in k.lower() for h in ("pass", "pin", "secret", "token", "otp", "key", "msisdn"))]

    results = {}  # id -> (status, detail)
    files = []
    for g in a.newman:
        files += glob.glob(g)
    for fp in files:
        rep = json.load(open(fp, encoding="utf-8"))
        for ex in rep.get("run", {}).get("executions", []):
            item = ex.get("item", {})
            name = item.get("name", "")
            ids = ID_RE.findall(name) or ID_RE.findall(json.dumps(item.get("_", {}))) or []
            tid = ids[0] if ids else "_unmatched"
            folder = os.path.join(a.evidence, tid if tid != "_unmatched" else f"_unmatched/{re.sub(r'[^A-Za-z0-9_-]+', '_', name)[:60]}")
            os.makedirs(folder, exist_ok=True)
            req, res = ex.get("request", {}), ex.get("response", {})
            req_out = {"name": name, "method": req.get("method"), "url": req.get("url", {}).get("raw") if isinstance(req.get("url"), dict) else req.get("url"),
                       "headers": {h.get("key"): h.get("value") for h in (req.get("header") or [])},
                       "body": decode_body((req.get("body") or {}).get("raw"))}
            res_out = {"code": res.get("code"), "status": res.get("status"), "responseTime_ms": res.get("responseTime"),
                       "headers": {h.get("key"): h.get("value") for h in (res.get("header") or [])},
                       "body": decode_body(res.get("stream"))}
            for fname, obj in (("request.json", req_out), ("response.json", res_out)):
                txt = json.dumps(mask_json_like(obj), indent=2, ensure_ascii=False)
                open(os.path.join(folder, fname), "w", encoding="utf-8").write(mask_in_text(txt, known))
            asserts = ex.get("assertions", []) or []
            failed = [x for x in asserts if x.get("error")]
            lines = [f"{'FAIL' if x.get('error') else 'PASS'}  {x.get('assertion')}" + (f"  → {x['error'].get('message')}" if x.get("error") else "") for x in asserts]
            if ex.get("requestError"):
                lines.append(f"REQUEST ERROR  {ex['requestError']}")
                failed.append({"error": ex["requestError"]})
            open(os.path.join(folder, "assertions.txt"), "w", encoding="utf-8").write("\n".join(lines) or "no assertions defined")
            status = "FAIL" if failed else ("PASS" if asserts else "PASS (no assertions)")
            if tid != "_unmatched":
                prev = results.get(tid)
                results[tid] = ("FAIL", f"{len(failed)} failed") if (failed or (prev and prev[0] == "FAIL")) else (status, f"{len(asserts)} assertions")

    # update index.csv
    rows = list(csv.DictReader(open(a.index, encoding="utf-8")))
    for r in rows:
        if r["id"] in results and r.get("status", "") not in ("BLOCKED",):
            r["status"] = results[r["id"]][0]
    with open(a.index, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else ["id", "status"])
        w.writeheader(); w.writerows(rows)
    summary = {"matched": len(results), "pass": sum(1 for s, _ in results.values() if s.startswith("PASS")),
               "fail": sum(1 for s, _ in results.values() if s == "FAIL")}
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
