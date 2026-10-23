#!/usr/bin/env python3
"""Scan pod logs for sensitive data and assess log structure.

  python3 -I scripts/scan_logs.py --logs docs/<svc>/<run>/logs/*.log \
      --patterns context/sensitive-patterns.json \
      --known-values docs/<svc>/<run>/variables.json \
      --extra-fields "msisdn,pin" --out sensitive-scan.md --json sensitive-scan.json
Exit 0 always; findings are in the outputs.
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mask import mask, is_secret_key, is_pii_key  # noqa: E402


def luhn_ok(num: str) -> bool:
    digits = [int(d) for d in num if d.isdigit()]
    if len(digits) < 13:
        return False
    checksum, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", nargs="+", required=True)
    ap.add_argument("--patterns", required=True)
    ap.add_argument("--known-values", help="variables.json; secret/PII values are searched literally")
    ap.add_argument("--extra-fields", default="", help="comma list of field names to treat as sensitive")
    ap.add_argument("--out", required=True)
    ap.add_argument("--json", required=True)
    a = ap.parse_args()

    cfg = json.load(open(a.patterns, encoding="utf-8"))
    patterns = [(p["name"], p.get("severity", "HIGH"), re.compile(p["regex"]), p.get("note", "")) for p in cfg["patterns"]]
    allowed_masked = cfg.get("allowed_masked_examples", [])

    for fld in [f.strip() for f in a.extra_fields.split(",") if f.strip()]:
        patterns.append((f"field_{fld}", "HIGH", re.compile(rf"(?i)\b{re.escape(fld)}\"?\s*[:=]\s*\"?([^\s\",}}]{{3,}})"), "field from variables.log_sensitive_fields"))

    known = {}   # key -> (value, compiled boundary regex)
    if a.known_values and os.path.exists(a.known_values):
        V = json.load(open(a.known_values, encoding="utf-8"))
        for k, v in V.items():
            if isinstance(v, str) and len(v) >= 4 and (is_secret_key(k) or is_pii_key(k)):
                # short values (PIN/OTP) must stand alone, long ones may be embedded
                rx = re.compile(rf"(?<![A-Za-z0-9]){re.escape(v)}(?![A-Za-z0-9])") if len(v) < 8 else re.compile(re.escape(v))
                known[k] = (v, rx)

    def sanitize(text: str) -> str:
        """Mask every known value and every pattern match inside an excerpt (not just the one that triggered)."""
        for _, (v, rx) in sorted(known.items(), key=lambda kv: -len(kv[1][0])):
            text = rx.sub(mask(v), text)
        for _, _, rx, _ in patterns:
            text = rx.sub(lambda m: mask(m.group(0)), text)
        return text

    files = []
    for g in a.logs:
        files += glob.glob(g)
    files = sorted(set(files))

    findings = defaultdict(list)   # (name, severity) -> [(file, line_no, masked_excerpt)]
    structure = {"files": len(files), "lines": 0, "json_lines": 0, "with_traceid": 0, "levels": Counter(),
                 "exceptions": Counter(), "stack_trace_lines": 0, "sql_lines": 0, "missing_fields": Counter(),
                 "qa_run_tagged": 0}
    expected_fields = ["timestamp", "level", "logger", "traceId", "message"]
    lvl_re = re.compile(r"\b(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\b")
    exc_re = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Exception|Error))\b")
    trace_re = re.compile(r"(?i)trace[_-]?id|x-request-id|correlation")

    for fp in files:
        with open(fp, encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f, 1):
                structure["lines"] += 1
                s = line.strip()
                if not s:
                    continue
                # structure
                js = None
                try:
                    body = s.split(" ", 1)[1] if re.match(r"^\d{4}-\d\d-\d\dT", s) and " {" in s else s  # kubectl --timestamps prefix
                    js = json.loads(body) if body.startswith("{") else None
                except Exception:
                    js = None
                if js is not None:
                    structure["json_lines"] += 1
                    for fld in expected_fields:
                        if not any(k.lower() == fld.lower() or k.lower().replace("_", "") == fld.lower() for k in js):
                            structure["missing_fields"][fld] += 1
                    lv = str(js.get("level") or js.get("severity") or "").upper()
                    if lv:
                        structure["levels"][lv] += 1
                else:
                    m = lvl_re.search(s)
                    if m:
                        structure["levels"][m.group(1)] += 1
                if trace_re.search(s):
                    structure["with_traceid"] += 1
                if "X-QA-Run" in s or "x-qa-run" in s.lower():
                    structure["qa_run_tagged"] += 1
                for e in exc_re.findall(s):
                    structure["exceptions"][e] += 1
                if re.search(r"\bat [a-z]+(\.[A-Za-z0-9_$]+)+\(", s):
                    structure["stack_trace_lines"] += 1
                if re.search(r"(?i)\b(select|insert|update|delete)\b.*\b(from|into|set)\b", s):
                    structure["sql_lines"] += 1

                # sensitive patterns
                for name, sev, rx, note in patterns:
                    for m in rx.finditer(s):
                        hit = m.group(0)
                        if name == "card_pan" and not luhn_ok(hit):
                            continue
                        if any(am in hit for am in allowed_masked):
                            continue
                        if name == "email" and re.search(r"\*{2,}", hit):
                            continue
                        start, end = max(0, m.start() - 40), min(len(s), m.end() + 40)
                        findings[(name, sev)].append((os.path.basename(fp), n, sanitize(s[start:end])))
                        break  # one hit per pattern per line is enough
                # known literal values (strongest signal)
                for k, (v, rx) in known.items():
                    m = rx.search(s)
                    if m:
                        start, end = max(0, m.start() - 40), min(len(s), m.end() + 40)
                        findings[(f"known_value:{k}", "CRITICAL")].append((os.path.basename(fp), n, sanitize(s[start:end])))

    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    total = sum(len(v) for v in findings.values())
    out = [f"# Sensitive-data scan — {len(files)} log file(s), {structure['lines']} lines", "",
           f"**Total hits: {total}**  ·  by severity: " + ", ".join(
               f"{sv} {sum(len(v) for (n, s), v in findings.items() if s == sv)}" for sv in sev_order), "",
           "| pattern | severity | hits | first occurrences (masked) |", "|---|---|---|---|"]
    for (name, sev), hits in sorted(findings.items(), key=lambda kv: (sev_order.get(kv[0][1], 9), -len(kv[1]))):
        samples = "<br>".join(f"`{f}:{ln}` {ex.replace('|', '/')}" for f, ln, ex in hits[:3])
        out.append(f"| {name} | {sev} | {len(hits)} | {samples} |")
    if not findings:
        out.append("| — | — | 0 | no sensitive data detected |")

    pct = lambda x: f"{(100.0 * x / structure['lines']):.1f}%" if structure["lines"] else "n/a"
    out += ["", "# Log structure", "",
            f"- JSON lines: {structure['json_lines']} ({pct(structure['json_lines'])})",
            f"- lines with traceId/correlation: {structure['with_traceid']} ({pct(structure['with_traceid'])})",
            f"- X-QA-Run tagged lines: {structure['qa_run_tagged']}",
            f"- levels: " + ", ".join(f"{k} {v}" for k, v in structure["levels"].most_common()),
            f"- stack-trace lines: {structure['stack_trace_lines']} ; SQL statements logged: {structure['sql_lines']}",
            f"- top exceptions: " + ", ".join(f"{k} ({v})" for k, v in structure["exceptions"].most_common(8)),
            f"- missing fields in JSON lines: " + ", ".join(f"{k} ({v})" for k, v in structure["missing_fields"].most_common()), ""]
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    structure["levels"] = dict(structure["levels"]); structure["exceptions"] = dict(structure["exceptions"].most_common(30))
    structure["missing_fields"] = dict(structure["missing_fields"])
    with open(a.json, "w", encoding="utf-8") as f:
        json.dump({"findings": [{"pattern": n, "severity": s, "count": len(h),
                                 "samples": [{"file": f_, "line": ln, "excerpt": ex} for f_, ln, ex in h[:20]]}
                                for (n, s), h in findings.items()],
                   "structure": structure}, f, indent=2, ensure_ascii=False)
    print("\n".join(out[:12]))


if __name__ == "__main__":
    main()
