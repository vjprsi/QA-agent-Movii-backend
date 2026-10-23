#!/usr/bin/env python3
"""Preflight gate: tools, repo/docs, variables, cluster, DB, service. Writes preflight.md. Never fails (exit 0)."""
import argparse
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from fnmatch import fnmatch
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TOOLS_REQUIRED = ["git", "java", "node", "newman", "k6", "kubectl", "mysql", "python3", "jq"]
TOOLS_OPTIONAL = ["mvn", "gradle", "semgrep", "gitleaks", "trivy", "az", "oci", "docker"]
INSTALL_HINT = {
    "newman": "npm i -g newman newman-reporter-htmlextra",
    "k6": "https://grafana.com/docs/k6/latest/set-up/install-k6/",
    "kubectl": "https://kubernetes.io/docs/tasks/tools/",
    "mysql": "apt/brew install mysql-client",
    "jq": "apt/brew install jq",
    "semgrep": "pip install semgrep", "gitleaks": "brew install gitleaks", "trivy": "brew install trivy",
    "az": "https://learn.microsoft.com/cli/azure/install-azure-cli", "oci": "pip install oci-cli",
}

rows = []  # (status, area, item, detail)


def add(status, area, item, detail=""):
    rows.append((status, area, item, detail))


def run(cmd, timeout=20, env=None):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--vars", required=True, help="variables.json")
    ap.add_argument("--env-file", default="context/environments.json")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    env_cfg = {}
    try:
        env_cfg = json.load(open(a.env_file, encoding="utf-8"))
    except Exception as e:
        add("WARN", "config", "context/environments.json", f"not readable: {e}")

    # ---- tools
    for t in TOOLS_REQUIRED:
        add("READY" if shutil.which(t) else "MISSING", "tools", t, "" if shutil.which(t) else INSTALL_HINT.get(t, ""))
    for t in TOOLS_OPTIONAL:
        add("READY" if shutil.which(t) else "WARN", "tools", f"{t} (optional)", "" if shutil.which(t) else INSTALL_HINT.get(t, ""))
    try:
        import openpyxl  # noqa
        add("READY", "tools", "python openpyxl")
    except ImportError:
        add("MISSING", "tools", "python openpyxl", "pip install openpyxl")

    # ---- repo & docs
    if os.path.isdir(os.path.join(a.repo, ".git")):
        rc, out = run(f"git -C '{a.repo}' log -1 --format='%h %s' && git -C '{a.repo}' rev-parse --abbrev-ref HEAD")
        add("READY", "repo", "cloned", out.strip().replace("\n", " | "))
    else:
        add("MISSING", "repo", "cloned", f"{a.repo} is not a git checkout")
    docs = os.path.join(a.repo, "docs")
    if os.path.isdir(docs):
        files = [os.path.relpath(p, docs) for p in glob.glob(os.path.join(docs, "**", "*"), recursive=True) if os.path.isfile(p)]
        add("READY", "docs", "/docs folder", f"{len(files)} files")
        specs = [f for f in files if re.search(r"\.(md|pdf|docx|pptx|png|jpg|svg|drawio|puml|txt)$", f, re.I)]
        add("READY" if specs else "WARN", "docs", "specification files", ", ".join(specs[:10]) + (" ..." if len(specs) > 10 else ""))
        pm = [f for f in files if "postman" in f.lower() and f.lower().endswith(".json")]
        add("READY" if pm else "MISSING", "docs", "postman collection", ", ".join(pm) or "no *postman*.json under /docs")
        xl = [f for f in files if re.search(r"variable.*\.xlsx?$", f, re.I)]
        add("READY" if xl else "MISSING", "docs", "variables.xlsx", ", ".join(xl) or "no variables*.xlsx under /docs")
    else:
        add("MISSING", "docs", "/docs folder", "repo has no /docs — spec traceability unavailable")
    for p in ("pom.xml", "build.gradle", "build.gradle.kts"):
        if os.path.exists(os.path.join(a.repo, p)):
            add("READY", "repo", "build file", p)
            break
    else:
        add("WARN", "repo", "build file", "no pom.xml / build.gradle found")

    # ---- variables
    V = {}
    try:
        V = json.load(open(a.vars, encoding="utf-8"))
        chk_path = os.path.join(os.path.dirname(a.vars), "variables-check.json")
        chk = json.load(open(chk_path, encoding="utf-8")) if os.path.exists(chk_path) else {}
        for k in chk.get("missing_required", []):
            add("MISSING", "variables", k, "required (see context/variables-schema.md)")
        for k in chk.get("missing_for_stress", []):
            add("MISSING", "variables", k, "required for stress tests only")
        for k in chk.get("unresolved_postman_vars", []):
            add("MISSING", "variables", f"postman {{{{{k}}}}}", "used by the collection, not in variables.xlsx/test_data")
        add("READY" if chk.get("deployed") in ("yes", "no") else "MISSING", "variables", "deployed", f"= {chk.get('deployed')}")
        if not chk.get("missing_required") and not chk.get("unresolved_postman_vars"):
            add("READY", "variables", "all required present")
    except Exception as e:
        add("MISSING", "variables", "variables.json", str(e))

    # ---- allowlist
    def allowed(host, patterns):
        return any(fnmatch(host, p) for p in patterns)

    base = V.get("base_url", "")
    host = urlparse(base).hostname if base else None
    if host:
        ok = allowed(host, env_cfg.get("allowed_api_hosts", []))
        add("READY" if ok else "MISSING", "allowlist", "base_url host", f"{host} {'in' if ok else 'NOT in'} allowed_api_hosts")
    if V.get("db_host"):
        ok = allowed(V["db_host"], env_cfg.get("allowed_db_hosts", []))
        add("READY" if ok else "MISSING", "allowlist", "db_host", f"{V['db_host']} {'in' if ok else 'NOT in'} allowed_db_hosts")
    if V.get("k8s_namespace"):
        ok = allowed(V["k8s_namespace"], env_cfg.get("kubernetes", {}).get("allowed_namespaces", []))
        add("READY" if ok else "MISSING", "allowlist", "k8s_namespace", f"{V['k8s_namespace']} {'in' if ok else 'NOT in'} kubernetes.allowed_namespaces")

    # ---- kubernetes
    ctx = os.environ.get("K8S_CONTEXT_TEST") or env_cfg.get("kubernetes", {}).get("context", "")
    ns, dep = V.get("k8s_namespace"), V.get("k8s_deployment") or V.get("service_name")
    if shutil.which("kubectl") and ns:
        rc, out = run(f"kubectl --context '{ctx}' -n '{ns}' get deploy '{dep}' -o wide 2>&1", 25)
        add("READY" if rc == 0 else "MISSING", "kubernetes", f"deployment {dep} in {ns}", out.strip().splitlines()[-1][:160] if out.strip() else "")
        rc2, out2 = run(f"kubectl --context '{ctx}' -n '{ns}' get pods -l app='{dep}' --no-headers 2>&1", 25)
        add("READY" if rc2 == 0 and out2.strip() else "WARN", "kubernetes", "pods", out2.strip()[:300])
        rc3, _ = run(f"kubectl --context '{ctx}' top pod -n '{ns}' 2>&1", 25)
        add("READY" if rc3 == 0 else "WARN", "kubernetes", "metrics (kubectl top)", "" if rc3 == 0 else "metrics-server not available → stress monitoring degraded")
    else:
        add("MISSING", "kubernetes", "access", "kubectl missing or k8s_namespace unknown")

    # ---- mysql
    if shutil.which("mysql") and V.get("db_host"):
        u, p = os.environ.get("MYSQL_TEST_RO_USER", ""), os.environ.get("MYSQL_TEST_RO_PASS", "")
        rc, out = run(f"mysql -h '{V['db_host']}' -P '{V.get('db_port', '3306')}' -u '{u}' -p'{p}' --connect-timeout=8 -N -e 'SELECT 1' 2>&1", 20)
        add("READY" if rc == 0 else "MISSING", "mysql", "connection (read-only user)", "" if rc == 0 else out.strip()[:160].replace(p, "<redacted>") if p else out.strip()[:160])
        if rc == 0:
            rc, out = run(f"mysql -h '{V['db_host']}' -P '{V.get('db_port', '3306')}' -u '{u}' -p'{p}' -N -e 'SHOW GRANTS' 2>&1", 20)
            writes = re.search(r"\b(INSERT|UPDATE|DELETE|ALL PRIVILEGES)\b", out or "", re.I)
            add("WARN" if writes else "READY", "mysql", "user is read-only", "user has write grants — ask DBA for SELECT-only" if writes else "SELECT-only grants")
            for s in re.split(r"[,\s;]+", V.get("db_schema", "")):
                if not s:
                    continue
                rc, out = run(f"mysql -h '{V['db_host']}' -P '{V.get('db_port', '3306')}' -u '{u}' -p'{p}' -N -e \"SHOW DATABASES LIKE '{s}'\" 2>&1", 20)
                add("READY" if s in (out or "") else "MISSING", "mysql", f"schema {s}", "" if s in (out or "") else "not visible to the RO user")
    else:
        add("MISSING", "mysql", "access", "mysql client missing or db_host unknown")

    # ---- service health (only meaningful if deployed)
    if base:
        try:
            socket.getaddrinfo(host, 443)
            add("READY", "service", "base_url DNS", host)
        except Exception as e:
            add("WARN", "service", "base_url DNS", f"{host}: {e}")
        rc, out = run(f"curl -sk -m 10 -o /dev/null -w '%{{http_code}}' '{base.rstrip('/')}{V.get('health_path', '/actuator/health')}'", 15)
        add("READY" if out.strip() == "200" else "WARN", "service", "health endpoint", f"HTTP {out.strip() or 'no response'} (expected 200 once deployed)")

    # ---- Azure DevOps env
    add("READY" if os.environ.get("ADO_PAT") else "MISSING", "azure-devops", "ADO_PAT env var", "needed for git clone")
    add("READY" if os.environ.get("ADO_PAT_B64") else "MISSING", "azure-devops", "ADO_PAT_B64 env var", "needed by the MCP server")
    if V.get("deployed", "").lower() in ("no", "false", "0", ""):
        add("READY" if V.get("deploy_pipeline") else "MISSING", "azure-devops", "deploy_pipeline", "name/id of the TEST deploy pipeline (deployed=no)")

    # ---- write report
    order = {"MISSING": 0, "WARN": 1, "READY": 2}
    counts = {k: sum(1 for r in rows if r[0] == k) for k in order}
    out = [f"# Preflight — {a.service} — run {a.run}", "",
           f"**READY {counts['READY']} · WARN {counts['WARN']} · MISSING {counts['MISSING']}**", "",
           "| status | area | item | detail |", "|---|---|---|---|"]
    for st, area, item, det in sorted(rows, key=lambda r: (order[r[0]], r[1])):
        out.append(f"| {st} | {area} | {item} | {det.replace('|', '/')} |")
    out += ["", "## Agent to complete", "- MCP checks: azure-devops (core_list_projects), kubernetes (pods_list_in_namespace), mysql (SELECT 1); MOVii plugins (VPN): movii-oci, mcp-movii-logs, mcp-movii-metrics, mcp-movii-traces, rag-qa (estado_rag) (optional)",
            "- Map each MISSING item → blocked test ids (from index.csv `requires_vars`)", ""]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    with open(a.out.replace(".md", ".json"), "w", encoding="utf-8") as f:
        json.dump([dict(status=s, area=ar, item=i, detail=d) for s, ar, i, d in rows], f, indent=2)
    print("\n".join(out))


if __name__ == "__main__":
    main()
