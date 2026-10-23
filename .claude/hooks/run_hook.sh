#!/usr/bin/env bash
# Launcher for the QA-agent PreToolUse hooks. Fail-CLOSED:
#   * picks a working Python 3 (python3 / python / py -3) — on Windows `python3`
#     is often the Microsoft Store stub, which exits 49 without running anything
#   * if no interpreter works, or the guard crashes, the call is BLOCKED (exit 2).
#     Claude Code treats any exit code other than 2 as "allow", so a broken
#     guard would otherwise silently disable the safety layer.
# Usage: bash run_hook.sh <guard_name.py>

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="$HOOK_DIR/$1"

PY=""
for cand in "python3" "python" "py -3"; do
  if $cand -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" </dev/null >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done

if [ -z "$PY" ]; then
  echo "BLOCKED by QA-agent guard: no working Python 3.10+ found for hook $1. Install Python 3.10+ (see README)." >&2
  exit 2
fi

$PY "$GUARD"
rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then
  echo "BLOCKED by QA-agent guard: hook $1 crashed (exit $rc); refusing the call (fail-closed)." >&2
  exit 2
fi
exit "$rc"
