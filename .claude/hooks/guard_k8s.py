#!/usr/bin/env python3
"""PreToolUse guard for the Kubernetes MCP server: observe-only, TEST namespaces only."""
from _common import read_payload, load_env, block, allow, matches_any, contains_forbidden_marker

payload = read_payload()
tool = payload.get("tool_name", "")
tool_input = payload.get("tool_input") or {}
env = load_env()
k8s = env.get("kubernetes", {})

WRITE_TOOLS = (
    "pods_delete", "pods_exec", "pods_run",
    "resources_delete", "resources_create_or_update",
    "helm_install", "helm_uninstall",
)
if any(tool.endswith(w) for w in WRITE_TOOLS):
    block(f"{tool} changes the cluster. The QA agent is observe-only; deployments go through the Azure DevOps pipeline.")

ns = tool_input.get("namespace")
if ns:
    allowed_ns = k8s.get("allowed_namespaces", [])
    if allowed_ns and not matches_any(ns, allowed_ns):
        block(f"namespace '{ns}' is not in kubernetes.allowed_namespaces (context/environments.json).")
    marker = contains_forbidden_marker(ns, env)
    if marker:
        block(f"namespace '{ns}' contains forbidden marker '{marker}'.")

allow()
