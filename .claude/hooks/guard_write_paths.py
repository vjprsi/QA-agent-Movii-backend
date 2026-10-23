#!/usr/bin/env python3
"""PreToolUse guard for Write/Edit: the agent may only write under
workspace/<service>/ (but NOT its src/), test-cases/, docs/.
It must never edit the service's source code or the agent's own harness."""
import os
from _common import read_payload, block, allow, PROJECT_DIR

payload = read_payload()
path = (payload.get("tool_input") or {}).get("file_path", "") or ""
if not path:
    allow()

abs_path = os.path.abspath(os.path.join(PROJECT_DIR, path)) if not os.path.isabs(path) else os.path.abspath(path)
try:
    rel = os.path.relpath(abs_path, PROJECT_DIR)
except ValueError:  # Windows: different drive than the agent folder
    block(f"writing outside the agent folder is not allowed: {path}")

ALLOWED_ROOTS = ("test-cases", "docs", "workspace")
if rel.startswith(".."):
    block(f"writing outside the agent folder is not allowed: {path}")

root = rel.split(os.sep)[0]
if root not in ALLOWED_ROOTS:
    block(f"writes are only allowed under {ALLOWED_ROOTS}; refused: {rel}")

# inside a cloned repo, only the qa/ scratch folder may be written
if root == "workspace":
    parts = rel.split(os.sep)
    # workspace/<service>/qa/...  is OK ; anything else inside the repo is not
    if len(parts) < 3 or parts[2] != "qa":
        block(f"inside workspace/<service>/ you may only write under qa/ (never the service's source): {rel}")

allow()
