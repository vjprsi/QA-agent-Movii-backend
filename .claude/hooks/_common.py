"""Shared helpers for the QA agent hooks.

Hook contract (Claude Code PreToolUse):
  stdin  : JSON {"tool_name": ..., "tool_input": {...}, "cwd": ...}
  exit 0 : allow
  exit 2 : BLOCK — stderr text is shown to the model as the reason
"""
import json
import os
import re
import sys
from fnmatch import fnmatch

PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
ENV_FILE = os.path.join(PROJECT_DIR, "context", "environments.json")


def read_payload():
    try:
        return json.load(sys.stdin)
    except Exception:
        # fail closed: an unreadable payload must not turn into "allow"
        block("hook received an unreadable tool payload; refusing the call.")


def load_env():
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def block(reason: str):
    sys.stderr.write(f"BLOCKED by QA-agent guard: {reason}\n")
    sys.exit(2)


def allow():
    sys.exit(0)


def matches_any(value: str, patterns):
    return any(fnmatch(value, p) for p in patterns)


def contains_forbidden_marker(text: str, env: dict) -> str | None:
    """Return the marker found (e.g. 'prod') or None."""
    markers = env.get("forbidden_markers", ["prod", "prd", "production", "live"])
    low = text.lower()
    for m in markers:
        # match as a word/segment: prod, -prod, prod-, .prod., _prod
        if re.search(rf"(^|[^a-z0-9]){re.escape(m.lower())}([^a-z0-9]|$)", low):
            return m
    return None
