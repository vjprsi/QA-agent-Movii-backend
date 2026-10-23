#!/usr/bin/env python3
"""PreToolUse guard for the MOVii marketplace MCP servers (movii-oci, Loki logs,
Mimir metrics, Tempo traces, movii-backend, rag-qa): read-only, never prod/staging.
The servers are read-only by design; this is the second line of defence.

Read tools (list_*, get_*, search_*, describe_*, summarize_*, query_*) pass.
Anything whose name looks like a mutation is blocked, and so is any input that
names a forbidden environment marker (prod, prd, ...)."""
import json
import re
from _common import read_payload, load_env, block, allow, contains_forbidden_marker

payload = read_payload()
tool = payload.get("tool_name", "")
tool_input = payload.get("tool_input") or {}
env = load_env()

# tool name after the last "__", e.g. mcp__plugin_movii-oci-mcp_movii-oci__list_instances -> list_instances
action = tool.rsplit("__", 1)[-1].lower()

WRITE_VERBS = (
    "create", "delete", "update", "terminate", "launch", "stop", "start", "reboot",
    "reset", "put", "patch", "post", "attach", "detach", "change", "move", "remove",
    "add", "upload", "restore", "scale", "cancel", "rotate", "enable", "disable",
    "run", "execute", "invoke", "apply", "import", "copy", "write", "deploy", "send",
    # the MOVii servers name some tools in Spanish
    "crear", "eliminar", "borrar", "actualizar", "modificar", "ejecutar", "desplegar",
    "enviar", "guardar", "insertar", "editar", "cambiar", "agregar", "reiniciar",
)
if re.search(rf"(^|_)({'|'.join(WRITE_VERBS)})(_|$)", action):
    block(f"{tool} looks like a write operation. The QA agent is read-only on the MOVii MCP servers.")

# generic "call any OCI API" tools: inspect the requested operation/method too
blob = json.dumps(tool_input).lower()
for key in ("operation", "method", "command", "api", "action", "http_method"):
    val = str(tool_input.get(key, "")).lower()
    if val and re.search(rf"(^|[^a-z])({'|'.join(WRITE_VERBS)})([^a-z]|$)", val) \
            and not re.search(r"(^|[^a-z])(get|list|search|summarize)([^a-z]|$)", val):
        block(f"{tool} requested '{val}', which looks like a write operation. The MOVii MCP servers are read-only for the QA agent.")

marker = contains_forbidden_marker(blob, env)
if marker:
    block(f"{tool} input references '{marker}', which looks like a non-TEST environment.")

allow()
