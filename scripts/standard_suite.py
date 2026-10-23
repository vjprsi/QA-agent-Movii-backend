#!/usr/bin/env python3
"""Reusable STANDARD baseline suite for any Movii Spring Boot service that uses
the GlobalApiResponse envelope. These checks are identical across services, so
the agent never re-codes them — it only designs the service-specific *business*
cases. Stable `STD-*` ids make the results comparable run-over-run (regression).

Driven by a per-service descriptor (JSON) the agent writes in Phase A:
{
  "service": "...", "base_url": "http://...", "base_path": "/movii-api/...",
  "sla_p95_ms": 800,
  "probe_get": "/ping",                      // a GET that returns 200
  "write_endpoint": {                        // optional; enables body/method checks
     "path": "/instances", "method": "POST",
     "min_valid_body": {"merchantFileCode": "QA-STD-PROBE"}
  },
  "enveloped": true
}

Writes: test-cases/<svc>/<run>/<category>/STD-*.md (+ upserts index.csv),
docs/<svc>/<run>/evidence/STD-*/, docs/<svc>/<run>/results/standard.json.

Usage:
  python -I scripts/standard_suite.py --descriptor docs/<svc>/<run>/descriptor.json \
     --run-dir docs/<svc>/<run> --cases-dir test-cases/<svc>/<run>
"""
import argparse
import csv
import datetime
import json
import os
import time
import urllib.error
import urllib.request
import uuid

CAT = {"OPS": "regression", "API": "functional", "OBS": "non-functional", "SEC": "security"}
EVID = None  # set in main


def http(method, url, body=None, headers=None, raw=None, tid=None, save=True, n_hint=None):
    h = {"Content-Type": "application/json"}
    if tid:
        h["correlation-id"] = f"qa-std-{tid}"
    h.update(headers or {})
    data = raw.encode() if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, rh, txt = r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, rh, txt = e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    ms = round((time.time() - t0) * 1000)
    try:
        js = json.loads(txt)
    except Exception:
        js = None
    if save and tid:
        d = os.path.join(EVID, tid)
        os.makedirs(d, exist_ok=True)
        nn = n_hint or (len([f for f in os.listdir(d) if f.startswith("req")]) + 1)
        json.dump({"method": method, "url": url, "headers": h, "body": body if body is not None else (raw[:300] if raw else None)},
                  open(os.path.join(d, f"req{nn}.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        json.dump({"status": status, "ms": ms,
                   "headers": {k: v for k, v in rh.items() if k.lower() in ("content-type", "correlation-id", "x-content-type-options", "cache-control", "access-control-allow-origin", "server")},
                   "body": (js if js is not None else txt[:1500])},
                  open(os.path.join(d, f"resp{nn}.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    return status, js, ms, {k.lower(): v for k, v in rh.items()}


def envelope_ok(b):
    return isinstance(b, dict) and all(k in b for k in ("code", "message", "success", "timestamp", "correlationId"))


def err_code(b):
    if not isinstance(b, dict):
        return None
    err = b.get("error")
    return err.get("code") if isinstance(err, dict) else None


def build_cases(desc):
    """Return a list of (id, title, category, priority, endpoint, expected, fn, sev)."""
    base = desc["base_url"]
    bp = desc.get("base_path", "")
    full = lambda p: base + p
    api = lambda p: base + bp + p
    probe = desc.get("probe_get", "/ping")
    we = desc.get("write_endpoint")
    sla = desc.get("sla_p95_ms", 800)
    cases = []

    def add(cid, title, pri, endpoint, expected, fn, sev):
        cases.append({"id": cid, "title": title, "category": CAT[cid.split("-")[1]], "priority": pri,
                      "endpoint": endpoint, "expected": expected, "fn": fn, "sev": sev})

    # ---- OPS (regression)
    def f_ping(t):
        s, b, ms, _ = http("GET", api(probe), tid=t)
        ok = s == 200
        return ok, f"HTTP {s} ({ms} ms)"
    add("STD-OPS-01", f"GET {probe} returns 200", "P1", f"GET {probe}", "HTTP 200", f_ping, "HIGH")

    def f_health(t):
        s, b, ms, _ = http("GET", full("/actuator/health"), tid=t)
        ok = s == 200 and isinstance(b, dict) and b.get("status") == "UP"
        return ok, f"HTTP {s} status={b.get('status') if isinstance(b,dict) else b} ({ms} ms)"
    add("STD-OPS-02", "GET /actuator/health is UP", "P1", "GET /actuator/health", "200 {status:UP}", f_health, "HIGH")

    enveloped = desc.get("enveloped", True)

    # ---- API (functional)
    def f_unknown(t):
        s, b, ms, _ = http("GET", api(f"/__qa_no_such_route__{uuid.uuid4().hex[:6]}"), tid=t)
        ok = s == 404 and (envelope_ok(b) if desc.get("enveloped", True) else True)
        return ok, f"HTTP {s} {err_code(b)} enveloped={envelope_ok(b)} ({ms} ms)"
    add("STD-API-01", "Unknown route -> 404 in envelope", "P2", "GET /<unknown>", "404 NOT_FOUND inside GlobalApiResponse", f_unknown, "LOW")

    if enveloped:
        def f_envelope(t):
            s, b, ms, _ = http("GET", api(f"/__qa_env_probe__{uuid.uuid4().hex[:6]}"), tid=t)
            missing = [k for k in ("code", "message", "success", "timestamp", "correlationId") if not (isinstance(b, dict) and k in b)]
            ok = not missing
            return ok, f"HTTP {s}; envelope missing keys={missing}"
        add("STD-API-02", "Error responses use the GlobalApiResponse envelope", "P2", "all", "code,message,success,timestamp,correlationId present", f_envelope, "MEDIUM")

    if we:
        def f_method(t):
            s, b, ms, _ = http("PATCH", api(we["path"]), tid=t)
            ok = s == 405
            return ok, f"HTTP {s} {err_code(b)} ({ms} ms)"
        add("STD-API-03", "Unsupported HTTP method -> 405", "P2", f"PATCH {we['path']}", "405 METHOD_NOT_ALLOWED", f_method, "LOW")

        def f_malformed(t):
            s, b, ms, _ = http(we.get("method", "POST"), api(we["path"]), raw='{"x": ', tid=t)
            ok = s == 400 and err_code(b) == "VALIDATION_ERROR"
            return ok, f"HTTP {s} {err_code(b)} ({ms} ms)"
        add("STD-API-04", "Malformed JSON body -> 400", "P2", f"{we.get('method','POST')} {we['path']}", "400 VALIDATION_ERROR (Malformed request body)", f_malformed, "LOW")

    # ---- OBS (non-functional) — the correlation-echo and timestamp checks encode
    # MOVii GlobalApiResponse house conventions; skip them for non-enveloped contracts.
    if enveloped:
        def f_corr(t):
            s, b, ms, _ = http("GET", api(f"/__qa_corr__{uuid.uuid4().hex[:6]}"), tid=t)
            cid = b.get("correlationId") if isinstance(b, dict) else None
            ok = cid == f"qa-std-{t}"
            return ok, f"sent=qa-std-{t} echoed={cid}"
        add("STD-OBS-01", "correlation-id propagated into the envelope", "P1", "all", "envelope.correlationId == sent id", f_corr, "MEDIUM")

        def f_tz(t):
            s, b, ms, _ = http("GET", api(f"/__qa_tz__{uuid.uuid4().hex[:6]}"), tid=t)
            ts = b.get("timestamp", "") if isinstance(b, dict) else ""
            local = datetime.datetime.now().strftime("%Y-%m-%d %H")
            ok = bool(ts) and str(ts)[:13] == local
            return ok, f"envelope ts={ts}; local hour={local}"
        add("STD-OBS-02", "Timestamps in America/Bogota (not UTC)", "P2", "all", "timestamp local Bogota hour", f_tz, "LOW")

    def f_latency(t):
        lat = []
        for _ in range(20):
            s, _, ms, _ = http("GET", api(probe), save=False)
            lat.append(ms)
        lat.sort()
        p95 = lat[int(len(lat) * 0.95) - 1]
        ok = p95 <= sla
        return ok, f"20x {probe}: p50={lat[len(lat)//2]} p95={p95} max={lat[-1]} ms (SLA p95<={sla})"
    add("STD-OBS-03", "Probe latency within SLA", "P2", f"GET {probe}", f"p95 <= {sla} ms", f_latency, "MEDIUM")

    # ---- SEC (security hardening)
    def f_headers(t):
        s, b, ms, h = http("GET", api(probe), tid=t)
        missing = [x for x in ("x-content-type-options", "cache-control") if x not in h]
        return (not missing), f"missing headers: {missing}; server={h.get('server')}"
    add("STD-SEC-01", "Basic security headers present", "P3", f"GET {probe}", "X-Content-Type-Options + Cache-Control present", f_headers, "LOW")

    def f_actuator(t):
        out = {}
        for ep in ("env", "beans", "heapdump", "mappings"):
            s, _, _, _ = http("GET", full(f"/actuator/{ep}"), save=False)
            out[ep] = s
        return all(v == 404 for v in out.values()), f"exposure: {out} (only health,info expected)"
    add("STD-SEC-02", "Sensitive actuator endpoints not exposed", "P2", "GET /actuator/*", "env/beans/heapdump/mappings all 404", f_actuator, "MEDIUM")

    def f_cors(t):
        s, b, ms, h = http("GET", api(probe), headers={"Origin": "http://qa-not-allowed.example"}, tid=t)
        acao = h.get("access-control-allow-origin")
        ok = acao not in ("*", "http://qa-not-allowed.example")
        return ok, f"Access-Control-Allow-Origin={acao!r}"
    add("STD-SEC-03", "CORS does not allow arbitrary origins", "P3", f"GET {probe}", "no wildcard/echoed ACAO", f_cors, "LOW")

    if we:
        def f_oversized(t):
            big = {list(we["min_valid_body"].keys())[0]: "A" * (2 * 1024 * 1024)} if we.get("min_valid_body") else {"x": "A" * (2 * 1024 * 1024)}
            s, b, ms, _ = http(we.get("method", "POST"), api(we["path"]), raw=json.dumps(big), tid=t)
            ok = s != 500
            return ok, f"HTTP {s} for 2 MB body (expect 413/400, never 500) ({ms} ms)"
        add("STD-SEC-04", "Oversized body rejected, not 500", "P2", f"{we.get('method','POST')} {we['path']}", "413 or 400; never 500", f_oversized, "LOW")
    return cases


def upsert_index(cases_dir, rows):
    p = os.path.join(cases_dir, "index.csv")
    base = ["id", "category", "priority", "title", "traces_to", "endpoint", "source", "status"]
    existing = {}
    # preserve the UNION of columns - never drop extras the business cases added
    # (e.g. requires_vars, automation). Keep first-seen order, base first.
    cols = list(base)
    if os.path.exists(p):
        rdr = csv.DictReader(open(p, encoding="utf-8"))
        for c in (rdr.fieldnames or []):
            if c not in cols:
                cols.append(c)
        for r in rdr:
            existing[r["id"]] = r
    for r in rows:
        for c in r:
            if c not in cols:
                cols.append(c)
        existing[r["id"]] = r
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in existing.values():
            w.writerow({c: r.get(c, "") for c in cols})


def write_case(cases_dir, svc, run, c, status, observed):
    cat = c["category"]
    os.makedirs(os.path.join(cases_dir, cat), exist_ok=True)
    body = (f"# {c['id']} — {c['title']}\n\n| Field | Value |\n|---|---|\n"
            f"| Category | {cat} |\n| Priority | {c['priority']} |\n| Endpoint | {c['endpoint']} |\n"
            f"| Traces to | Movii house contract (standard baseline) |\n| Preconditions | service deployed |\n"
            f"| Test data | generated |\n| Automation | scripts/standard_suite.py |\n| Source | standard |\n\n"
            f"## Steps\n{c['endpoint']}\n\n## Expected result\n{c['expected']}\n\n"
            f"## Actual result\n- Status: {status}\n- Observed: {observed}\n"
            f"- Evidence: `docs/{svc}/{run}/evidence/{c['id']}/`\n"
            + (f"- Severity: {c['sev']}\n" if status == "FAIL" else ""))
    open(os.path.join(cases_dir, cat, f"{c['id']}.md"), "w", encoding="utf-8").write(body)


def main():
    global EVID
    ap = argparse.ArgumentParser()
    ap.add_argument("--descriptor", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--cases-dir", required=True)
    args = ap.parse_args()
    desc = json.load(open(args.descriptor, encoding="utf-8"))
    run_dir, cases_dir = os.path.normpath(args.run_dir), os.path.normpath(args.cases_dir)
    svc = desc.get("service", run_dir.replace("\\", "/").split("/")[-2])
    run = run_dir.replace("\\", "/").split("/")[-1]
    EVID = os.path.join(run_dir, "evidence")
    os.makedirs(os.path.join(run_dir, "results"), exist_ok=True)

    cases = build_cases(desc)
    results, rows = [], []
    for c in cases:
        t0 = time.time()
        try:
            ok, observed = c["fn"](c["id"])
            status = "PASS" if ok else "FAIL"
        except Exception as e:  # noqa: BLE001
            status, observed = "BLOCKED", f"harness error: {e}"
        results.append({"id": c["id"], "title": c["title"], "trace": "standard baseline",
                        "status": status, "observed": observed,
                        "severity": None if status != "FAIL" else c["sev"], "secs": round(time.time() - t0, 2)})
        write_case(cases_dir, svc, run, c, status, observed)
        rows.append({"id": c["id"], "category": c["category"], "priority": c["priority"], "title": c["title"],
                     "traces_to": "standard baseline", "endpoint": c["endpoint"], "source": "standard", "status": status})
        print(f"{status:8} {c['id']}  {c['title']}  -> {str(observed)[:120]}")
    upsert_index(cases_dir, rows)
    json.dump(results, open(os.path.join(run_dir, "results", "standard.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    p = sum(1 for r in results if r["status"] == "PASS")
    print(f"\nstandard baseline: {p}/{len(results)} PASS  (results/standard.json)")


if __name__ == "__main__":
    main()
