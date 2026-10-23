#!/usr/bin/env python3
"""Coverage matrix derived from the ACTUAL evidence (not self-reported).

Reads the per-service contract (descriptor.json: contract.endpoints[] with
method/path/fields/error_codes) and every evidence/<ID>/req*.json+resp*.json,
and computes, per endpoint:
  - was it exercised at all (>=1 request matched)?
  - which documented request fields were seen (in bodies or validation errors)?
  - which documented error codes were actually observed in responses?

Writes docs/<svc>/<run>/coverage.json and coverage.md. The HTML dashboard
reads coverage.json for its Coverage tab.

Usage:
  python -I scripts/coverage_report.py --run-dir docs/<svc>/<run> \
     --descriptor docs/<svc>/<run>/descriptor.json
"""
import argparse
import glob
import json
import os
import re


def path_regex(method, path):
    # /instances/{merchantFileCode}/transitions -> ^/instances/[^/]+/transitions$
    pat = re.sub(r"\{[^}]+\}", r"[^/]+", re.escape(path).replace(r"\{", "{").replace(r"\}", "}"))
    pat = re.sub(r"\{[^}]+\}", r"[^/]+", path)
    pat = "^" + re.sub(r"\{[^}]+\}", r"[^/]+", re.escape(path)).replace(r"\{", "").replace(r"\}", "") + "$"
    # simpler robust build:
    segs = []
    for s in path.strip("/").split("/"):
        segs.append("[^/]+" if (s.startswith("{") and s.endswith("}")) else re.escape(s))
    return re.compile("^/" + "/".join(segs) + "$")


def load_evidence(run_dir):
    out = []
    evid = os.path.join(run_dir, "evidence")
    if not os.path.isdir(evid):
        return out
    for tid in sorted(os.listdir(evid)):
        d = os.path.join(evid, tid)
        if not os.path.isdir(d):
            continue
        for rq in sorted(glob.glob(os.path.join(d, "req*.json"))):
            n = re.search(r"(\d+)", os.path.basename(rq)).group(1)
            rsp = os.path.join(d, f"resp{n}.json")
            try:
                req = json.load(open(rq, encoding="utf-8"))
            except Exception:
                continue
            resp = json.load(open(rsp, encoding="utf-8")) if os.path.exists(rsp) else {}
            out.append((tid, req, resp))
    return out


def url_path(url, base_path):
    m = re.sub(r"^https?://[^/]+", "", url or "")
    if base_path and m.startswith(base_path):
        m = m[len(base_path):]
    return m.split("?")[0] or "/"


def observed_error_code(resp):
    b = resp.get("body") if isinstance(resp, dict) else None
    return (b.get("error") or {}).get("code") if isinstance(b, dict) else None


def body_fields(req):
    b = req.get("body") if isinstance(req, dict) else None
    return set(b.keys()) if isinstance(b, dict) else set()


def validation_fields(resp):
    b = resp.get("body") if isinstance(resp, dict) else None
    v = (b.get("error") or {}).get("validations") if isinstance(b, dict) else None
    return {x.get("field") for x in v} if isinstance(v, list) else set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--descriptor", required=True)
    args = ap.parse_args()
    run_dir = os.path.normpath(args.run_dir)
    desc = json.load(open(args.descriptor, encoding="utf-8"))
    base_path = desc.get("base_path", "")
    endpoints = desc.get("contract", {}).get("endpoints", [])
    evidence = load_evidence(run_dir)

    rows = []
    for ep in endpoints:
        rx = path_regex(ep["method"], ep["path"])
        hits = [(req, resp) for (_, req, resp) in evidence
                if (req.get("method") == ep["method"]) and rx.match(url_path(req.get("url", ""), base_path))]
        seen_fields, seen_errs = set(), set()
        for req, resp in hits:
            seen_fields |= body_fields(req) | validation_fields(resp)
            ec = observed_error_code(resp)
            if ec:
                seen_errs.add(ec)
        docf = set(ep.get("fields", []))
        doce = set(ep.get("error_codes", []))
        rows.append({
            "id": ep.get("id", ""), "endpoint": f'{ep["method"]} {ep["path"]}',
            "exercised": bool(hits), "requests": len(hits),
            "fields_documented": sorted(docf), "fields_seen": sorted(docf & seen_fields),
            "fields_missing": sorted(docf - seen_fields),
            "errors_documented": sorted(doce), "errors_seen": sorted(doce & seen_errs),
            "errors_missing": sorted(doce - seen_errs),
        })

    ep_total = len(endpoints)
    ep_cov = sum(1 for r in rows if r["exercised"])
    f_total = sum(len(r["fields_documented"]) for r in rows)
    f_cov = sum(len(r["fields_seen"]) for r in rows)
    e_total = sum(len(r["errors_documented"]) for r in rows)
    e_cov = sum(len(r["errors_seen"]) for r in rows)
    summary = {
        "endpoints": {"covered": ep_cov, "total": ep_total, "pct": round(100 * ep_cov / ep_total) if ep_total else 0},
        "fields": {"covered": f_cov, "total": f_total, "pct": round(100 * f_cov / f_total) if f_total else 0},
        "error_codes": {"covered": e_cov, "total": e_total, "pct": round(100 * e_cov / e_total) if e_total else 0},
    }
    cov = {"summary": summary, "endpoints": rows}
    json.dump(cov, open(os.path.join(run_dir, "coverage.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    # markdown
    md = ["# Coverage — derived from executed evidence", "",
          f"- **Endpoints exercised:** {ep_cov}/{ep_total} ({summary['endpoints']['pct']}%)",
          f"- **Documented request fields seen:** {f_cov}/{f_total} ({summary['fields']['pct']}%)",
          f"- **Documented error codes reproduced:** {e_cov}/{e_total} ({summary['error_codes']['pct']}%)", "",
          "| Endpoint | Exercised | Reqs | Fields seen / documented | Error codes reproduced / documented | Gaps |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        gaps = []
        if not r["exercised"]:
            gaps.append("endpoint untested")
        if r["fields_missing"]:
            gaps.append("fields: " + ",".join(r["fields_missing"]))
        if r["errors_missing"]:
            gaps.append("errors: " + ",".join(r["errors_missing"]))
        md.append(f"| {r['endpoint']} | {'yes' if r['exercised'] else 'NO'} | {r['requests']} | "
                  f"{len(r['fields_seen'])}/{len(r['fields_documented'])} | "
                  f"{len(r['errors_seen'])}/{len(r['errors_documented'])} | {'; '.join(gaps) or '—'} |")
    open(os.path.join(run_dir, "coverage.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"coverage: endpoints {ep_cov}/{ep_total}, fields {f_cov}/{f_total}, error-codes {e_cov}/{e_total} "
          f"-> coverage.json + coverage.md")


if __name__ == "__main__":
    main()
