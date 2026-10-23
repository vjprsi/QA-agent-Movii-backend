#!/usr/bin/env python3
"""Static egress check: find every host/IP/URL the service could talk to and flag public ones.

  python3 -I scripts/check_egress.py --repo workspace/<svc> --allow context/environments.json --out docs/<svc>/<run>/security/egress.md
"""
import argparse
import ipaddress
import json
import os
import re
from collections import defaultdict
from fnmatch import fnmatch

SCAN_EXT = (".java", ".kt", ".yml", ".yaml", ".properties", ".json", ".xml", ".gradle", ".kts", "Dockerfile", ".sh", ".env", ".conf", ".toml")
URL_RE = re.compile(r"(?i)\b(https?|ftp|jdbc:mysql|amqp|kafka|redis|mongodb)://([A-Za-z0-9.\-_${}:]+)(?::(\d+))?")
IP_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
HOST_HINT_RE = re.compile(r"(?i)\b(host|url|endpoint|server|base-?url|uri)\s*[:=]\s*[\"']?([A-Za-z0-9.\-_]+\.[a-z]{2,})")
SDK_HINTS = [
    ("telemetry/analytics SDK", re.compile(r"(?i)(sentry|datadog|newrelic|segment\.com|mixpanel|amplitude|firebase|google-analytics|appinsights|applicationinsights)")),
    ("public Maven repo", re.compile(r"(?i)(repo1\.maven\.org|jcenter\.bintray|jitpack\.io|plugins\.gradle\.org)")),
    ("curl|sh in Dockerfile", re.compile(r"(?i)curl[^\n|]*\|\s*(ba)?sh")),
    ("http:// (cleartext)", re.compile(r"(?i)\bhttp://(?!localhost|127\.0\.0\.1|\$\{)")),
    ("webhook", re.compile(r"(?i)webhook")),
]
INTERNAL_TLDS = (".internal", ".local", ".svc", ".cluster.local", ".corp", ".lan", ".test")


def is_private_ip(ip):
    try:
        ipo = ipaddress.ip_address(ip)
        return ipo.is_private or ipo.is_loopback or ipo.is_link_local or ipo.is_reserved or ipo.is_unspecified
    except ValueError:
        return True  # not a real IP (e.g. version number) → ignore


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--allow", required=True, help="context/environments.json")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cfg = json.load(open(a.allow, encoding="utf-8"))
    allow_hosts = cfg.get("allowed_api_hosts", []) + cfg.get("allowed_db_hosts", []) + cfg.get("allowed_egress_hosts", [])

    hosts, ips, hints = defaultdict(set), defaultdict(set), defaultdict(set)
    for root, dirs, files in os.walk(a.repo):
        dirs[:] = [d for d in dirs if d not in (".git", "target", "build", "node_modules", "qa")]
        for fn in files:
            if not (fn.endswith(SCAN_EXT) or fn == "Dockerfile" or fn.startswith("Dockerfile")):
                continue
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, a.repo)
            try:
                text = open(fp, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                for m in URL_RE.finditer(line):
                    hosts[m.group(2).split(":")[0]].add(f"{rel}:{n}")
                for m in HOST_HINT_RE.finditer(line):
                    hosts[m.group(2)].add(f"{rel}:{n}")
                for m in IP_RE.finditer(line):
                    if not is_private_ip(m.group(1)) and not rel.endswith(("pom.xml",)):
                        ips[m.group(1)].add(f"{rel}:{n}")
                for label, rx in SDK_HINTS:
                    if rx.search(line):
                        hints[label].add(f"{rel}:{n}")

    def classify(h):
        hl = h.lower()
        if hl.startswith("${") or hl in ("localhost", "0.0.0.0"):
            return "placeholder/local"
        if hl.endswith(INTERNAL_TLDS) or "." not in hl:
            return "internal"
        if any(fnmatch(hl, p.lower()) for p in allow_hosts):
            return "allowlisted"
        if any(x in hl for x in ("w3.org", "xmlns", "schemas.", "maven.apache.org", "springframework.org", "example.com", "json-schema.org")):
            return "schema/namespace (benign)"
        return "PUBLIC"

    rows = []
    for h, locs in sorted(hosts.items()):
        rows.append((classify(h), h, len(locs), sorted(locs)[:4]))
    public_hosts = [r for r in rows if r[0] == "PUBLIC"]

    out = ["# Egress check (static)", "",
           f"Hosts found: {len(rows)} · PUBLIC (not allowlisted): **{len(public_hosts)}** · public IPs: **{len(ips)}**", "",
           "## Public / non-allowlisted hosts  → each is a finding (HIGH; CRITICAL if it carries data)", "",
           "| host | refs | where |", "|---|---|---|"]
    for cls, h, n, locs in public_hosts:
        out.append(f"| {h} | {n} | {'<br>'.join(locs)} |")
    if not public_hosts:
        out.append("| — | 0 | none |")
    out += ["", "## Public IP literals", "", "| ip | where |", "|---|---|"]
    for ip, locs in sorted(ips.items()):
        out.append(f"| {ip} | {'<br>'.join(sorted(locs)[:4])} |")
    if not ips:
        out.append("| — | none |")
    out += ["", "## Risk hints", "", "| hint | where |", "|---|---|"]
    for label, locs in sorted(hints.items()):
        out.append(f"| {label} | {'<br>'.join(sorted(locs)[:6])} |")
    if not hints:
        out.append("| — | none |")
    out += ["", "## All hosts (classified)", "", "| class | host | refs |", "|---|---|---|"]
    for cls, h, n, _ in sorted(rows):
        out.append(f"| {cls} | {h} | {n} |")
    out += ["", "Runtime follow-up: `kubectl get networkpolicy -n <ns>`, Service/Ingress types, OCI NSG/VCN flow logs for the TEST subnet."]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    open(a.out, "w", encoding="utf-8").write("\n".join(out))
    json.dump({"public_hosts": [dict(host=h, refs=n, where=l) for _, h, n, l in public_hosts],
               "public_ips": {k: sorted(v) for k, v in ips.items()},
               "hints": {k: sorted(v) for k, v in hints.items()}},
              open(a.out.replace(".md", ".json"), "w", encoding="utf-8"), indent=2)
    print("\n".join(out[:14]))


if __name__ == "__main__":
    main()
