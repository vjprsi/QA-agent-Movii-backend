#!/usr/bin/env python3
"""PreToolUse guard for Bash.

Blocks:
  * anything that writes to git remotes or the cluster
  * mysql CLI calls that are not read-only
  * commands that mention a forbidden environment marker (prod, prd, ...)
  * hosts that are not in the TEST allowlist (for curl / mysql / newman / k6)
"""
import re
from _common import read_payload, load_env, block, allow, matches_any, contains_forbidden_marker

payload = read_payload()
cmd = (payload.get("tool_input") or {}).get("command", "") or ""
env = load_env()
low = cmd.lower()

# 1. absolute no-go commands
NO_GO = [
    r"\bgit\b[^|;&\n]*\b(push|commit|reset\s+--hard|rebase|merge|tag\s+-|branch\s+-[dD]|filter-branch)\b",
    r"\bkubectl\s+(apply|delete|scale|edit|exec|patch|create|replace|drain|cordon|rollout\s+restart)\b",
    r"\bhelm\s+(install|upgrade|uninstall|rollback)\b",
    r"\brm\s+-rf\b", r"\bsudo\b", r"\bmkfs\b", r"\bdd\s+if=",
    r"\boci\s+\S+\s+(create|delete|update|terminate|launch)\b",
    r"\baz\s+(aks|vm|group)\s+delete\b",
]
for pat in NO_GO:
    if re.search(pat, low):
        block(f"command matches forbidden pattern /{pat}/. The QA agent is read-only on git remotes, Kubernetes and cloud.")

# 2. mysql CLI must be read-only
if re.search(r"(^|[\s|;&])mysql(\s|$)", low):
    if re.search(r"\b(insert|update|delete|drop|alter|truncate|create|replace|grant|revoke|lock|call|load\s+data|set\s+global)\b", low):
        block("mysql command contains a write/DDL statement. Only SELECT/SHOW/DESCRIBE/EXPLAIN are allowed.")

# 3. forbidden environment markers anywhere in the command
marker = contains_forbidden_marker(cmd, env)
if marker:
    block(f"command references '{marker}', which looks like a non-TEST environment. Only TEST targets from context/environments.json are allowed.")

# 4. host allowlist for network-facing tools
NET_TOOLS = r"\b(curl|wget|newman|k6|mysql|nc|telnet|http|httpie)\b"
if re.search(NET_TOOLS, low):
    allowed = (env.get("allowed_api_hosts") or []) + (env.get("allowed_db_hosts") or []) \
              + ["localhost", "127.0.0.1", "0.0.0.0"]
    hosts = set()
    hosts.update(re.findall(r"https?://([a-z0-9.\-_]+)", low))
    # case-sensitive on the original command: mysql uses -h/--host, while curl's -H is a header
    hosts.update(h.lower() for h in re.findall(r"(?:^|\s)(?:-h|--host)\s*=?\s*([A-Za-z0-9.\-_]+)", cmd))
    for h in hosts:
        if not matches_any(h, [a.lower() for a in allowed]):
            block(f"host '{h}' is not in the TEST allowlist (context/environments.json → allowed_api_hosts / allowed_db_hosts).")

# 5. k6 / newman must run against TEST only — also check env var style BASE_URL=...
m = re.search(r"base_url\s*=\s*['\"]?https?://([a-z0-9.\-_]+)", low)
if m:
    allowed = [a.lower() for a in env.get("allowed_api_hosts", [])] + ["localhost", "127.0.0.1"]
    if not matches_any(m.group(1), allowed):
        block(f"BASE_URL host '{m.group(1)}' is not in allowed_api_hosts.")

allow()
