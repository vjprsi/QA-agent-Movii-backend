#!/usr/bin/env python3
"""Join k6 per-step results with pod and DB monitoring → stress-results.md (+ stress.html with simple charts).

  python3 -I scripts/stress_report.py --out docs/<svc>/<run>/stress --sla context/environments.json --vars docs/<svc>/<run>/variables.json
Expects in --out: k6-results.json (k6 --out json), pods.csv, db-connections.csv (optional), k6-summary.json (optional).
"""
import argparse
import csv
import json
import os
import statistics
from collections import defaultdict


def pctl(values, p):
    if not values:
        return None
    vs = sorted(values)
    k = max(0, min(len(vs) - 1, int(round(p / 100.0 * (len(vs) - 1)))))
    return vs[k]


def load_k6(path):
    """Stream k6 JSON lines; return per-step durations/errors and overall time bounds."""
    per_step = defaultdict(lambda: {"dur": [], "err": 0, "n": 0, "status": defaultdict(int), "t": []})
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") != "Point":
                continue
            m, d = o.get("metric"), o.get("data", {})
            tags = d.get("tags") or {}
            step = tags.get("step", "?")
            if m == "http_req_duration":
                per_step[step]["dur"].append(d["value"]); per_step[step]["n"] += 1; per_step[step]["t"].append(d["time"])
                per_step[step]["status"][tags.get("status", "?")] += 1
            elif m == "http_req_failed" and d.get("value") == 1:
                per_step[step]["err"] += 1
    return per_step


def load_csv(path):
    if not path or not os.path.exists(path):
        return []
    rows = [r for r in csv.DictReader((l for l in open(path, encoding="utf-8") if not l.startswith("#")))]
    return rows


def to_f(x):
    try:
        return float(x)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--sla", required=True)
    ap.add_argument("--vars", required=True)
    a = ap.parse_args()
    sla = json.load(open(a.sla, encoding="utf-8")).get("sla_defaults", {})
    V = json.load(open(a.vars, encoding="utf-8"))
    p95_sla = float(V.get("stress_p95_ms") or sla.get("p95_ms", 800))
    p99_sla = float(V.get("stress_p99_ms") or sla.get("p99_ms", 1500))
    err_max = float(V.get("stress_error_rate_max") or sla.get("error_rate_max", 0.01))
    ladder = [int(x) for x in str(V.get("stress_tps_ladder", "")).replace(";", ",").split(",") if x.strip().isdigit()]
    step_s = int(str(V.get("stress_step_seconds", "60")).split(",")[0])

    k6_path = os.path.join(a.out, "k6-results.json")
    steps = load_k6(k6_path) if os.path.exists(k6_path) else {}
    pods = load_csv(os.path.join(a.out, "pods.csv"))
    db = load_csv(os.path.join(a.out, "db-connections.csv"))

    # time window per step from k6 points
    def window(st):
        ts = sorted(steps[st]["t"])
        return (ts[0], ts[-1]) if ts else (None, None)

    def in_window(ts, w):
        return w[0] and w[1] and w[0][:19] <= ts[:19] <= w[1][:19]

    rows, verdicts = [], []
    restarts_seen = set()
    for st in sorted(steps, key=lambda s: int(s) if str(s).isdigit() else 999):
        d = steps[st]
        w = window(st)
        dur = d["dur"]
        p50, p95, p99 = pctl(dur, 50), pctl(dur, 95), pctl(dur, 99)
        err_rate = (d["err"] / d["n"]) if d["n"] else 0.0
        secs = max(1.0, (len(set(t[:19] for t in d["t"])) or 1))
        achieved = d["n"] / secs
        pw = [r for r in pods if in_window(r["ts"], w)]
        cpu = [to_f(r["cpu_m"]) for r in pw if to_f(r["cpu_m"]) is not None]
        mem = [to_f(r["mem_Mi"]) for r in pw if to_f(r["mem_Mi"]) is not None]
        rst = {r["pod"]: int(r["restarts"] or 0) for r in pw}
        for p, n in rst.items():
            base = min(int(r["restarts"] or 0) for r in pods if r["pod"] == p) if pods else 0
            if n > base:
                restarts_seen.add((st, p))
        dbw = [r for r in db if in_window(r["ts"], w)]
        conn = [to_f(r["threads_connected"]) for r in dbw if to_f(r["threads_connected"]) is not None]
        target = ladder[int(st)] if str(st).isdigit() and int(st) < len(ladder) else "?"
        ok = (p95 is None or p95 <= p95_sla) and (p99 is None or p99 <= p99_sla) and err_rate <= err_max and not any(s == st for s, _ in restarts_seen)
        verdicts.append(ok)
        fmt = lambda x: f"{x:.0f}" if isinstance(x, (int, float)) else "–"
        rows.append(f"| {st} | {target} | {achieved:.2f} | {fmt(p50)} | {fmt(p95)} | {fmt(p99)} | {100*err_rate:.2f}% | "
                    f"{fmt(min(cpu)) if cpu else '–'}–{fmt(max(cpu)) if cpu else '–'} | {fmt(min(mem)) if mem else '–'}–{fmt(max(mem)) if mem else '–'} | "
                    f"{len([1 for s,_ in restarts_seen if s==st])} | {fmt(min(conn)) if conn else '–'}–{fmt(max(conn)) if conn else '–'} | {'PASS' if ok else 'FAIL'} |")

    # recovery: last 30 s of pods/db vs first 30 s
    def avg(vals):
        return statistics.mean(vals) if vals else None
    base_conn = avg([to_f(r["threads_connected"]) for r in db[:6] if to_f(r["threads_connected"]) is not None])
    end_conn = avg([to_f(r["threads_connected"]) for r in db[-6:] if to_f(r["threads_connected"]) is not None])
    base_mem = avg([to_f(r["mem_Mi"]) for r in pods[:6] if to_f(r["mem_Mi"]) is not None])
    end_mem = avg([to_f(r["mem_Mi"]) for r in pods[-6:] if to_f(r["mem_Mi"]) is not None])
    leak_conn = base_conn is not None and end_conn is not None and end_conn > base_conn + 2
    mem_not_released = base_mem is not None and end_mem is not None and end_mem > base_mem * 1.25

    overall = "PASS" if verdicts and all(verdicts) and not restarts_seen and not leak_conn else ("FAIL" if verdicts else "NOT RUN")
    md = [f"# Stress results — ladder {ladder} TPS × {step_s}s", "",
          f"**Overall: {overall}**  · SLA p95 ≤ {p95_sla:.0f} ms, p99 ≤ {p99_sla:.0f} ms, errors ≤ {100*err_max:.2f}%", "",
          "| step | target TPS | achieved TPS | p50 ms | p95 ms | p99 ms | errors | pod CPU m (min–max) | pod mem Mi (min–max) | restarts | DB conns (min–max) | verdict |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"] + rows
    md += ["", "## Recovery (30 s after ramp-down)",
           f"- DB connections: baseline {base_conn if base_conn is None else round(base_conn,1)} → end {end_conn if end_conn is None else round(end_conn,1)} → "
           + ("**possible connection leak (FAIL)**" if leak_conn else "returned to baseline (OK)"),
           f"- Pod memory: baseline {base_mem if base_mem is None else round(base_mem)} Mi → end {end_mem if end_mem is None else round(end_mem)} Mi → "
           + ("**not released (MEDIUM, investigate leak)**" if mem_not_released else "OK"),
           f"- Pod restarts during run: {len(restarts_seen)}" + (" **(FAIL)**" if restarts_seen else ""), "",
           "## Files", "- k6-results.json, k6-summary.json, k6-console.txt, pods.csv, db-connections.csv, events.txt, logs-errors.txt, stress.html"]
    open(os.path.join(a.out, "stress-results.md"), "w", encoding="utf-8").write("\n".join(md))

    # tiny self-contained HTML charts (no external libs)
    def series(rows_, key, tkey="ts"):
        return [(r[tkey], to_f(r[key])) for r in rows_ if to_f(r[key]) is not None]
    mem_s, cpu_s, conn_s = series(pods, "mem_Mi"), series(pods, "cpu_m"), series(db, "threads_connected")
    lat = [(t, v) for st in steps for t, v in zip(steps[st]["t"], steps[st]["dur"])]
    lat.sort()
    def svg(points, title, color):
        if not points:
            return f"<h3>{title}</h3><p>no data</p>"
        ys = [p[1] for p in points]; mx = max(ys) or 1
        W, H = 900, 180
        pts = " ".join(f"{(i/(len(points)-1 or 1))*W:.1f},{H-(y/mx)*(H-10):.1f}" for i, (_, y) in enumerate(points))
        return (f"<h3>{title} (max {mx:.0f})</h3><svg width='{W}' height='{H}' style='background:#fafafa;border:1px solid #ddd'>"
                f"<polyline fill='none' stroke='{color}' stroke-width='1.5' points='{pts}'/></svg>")
    html = ["<!doctype html><meta charset='utf-8'><title>Stress charts</title><body style='font-family:sans-serif;max-width:960px;margin:auto'>",
            f"<h1>Stress — {V.get('service_name','service')} — {overall}</h1><pre>{chr(10).join(md[:3])}</pre>",
            svg(lat, "Latency ms (per request, time-ordered)", "#1565c0"), svg(mem_s, "Pod memory Mi", "#c62828"),
            svg(cpu_s, "Pod CPU millicores", "#ef6c00"), svg(conn_s, "MySQL threads_connected", "#2e7d32"), "</body>"]
    open(os.path.join(a.out, "stress.html"), "w", encoding="utf-8").write("\n".join(html))
    print("\n".join(md[:6 + len(rows)]))


if __name__ == "__main__":
    main()
