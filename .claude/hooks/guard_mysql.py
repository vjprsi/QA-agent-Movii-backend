#!/usr/bin/env python3
"""PreToolUse guard for the MySQL MCP server: SELECT-only, TEST schemas only."""
import json
import re
from _common import read_payload, load_env, block, allow, matches_any

payload = read_payload()
tool_input = payload.get("tool_input") or {}
env = load_env()

sql = json.dumps(tool_input).upper()

# read-only statements only
if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|GRANT|REVOKE|LOCK|CALL|LOAD\s+DATA|RENAME|SET\s+GLOBAL|FLUSH|KILL)\b", sql):
    block("SQL contains a write/DDL/admin statement. The QA agent may only SELECT / SHOW / DESCRIBE / EXPLAIN.")

# schema allowlist (schema.table references)
allowed_schemas = [s.lower() for s in env.get("allowed_db_schemas", [])]
if allowed_schemas:
    # only qualified names after FROM/JOIN/... are schema.table; `u.id` in a
    # select list or WHERE clause is alias.column and must not be checked
    refs = re.findall(r"\b(?:FROM|JOIN|DESCRIBE|DESC|EXPLAIN|TABLE|INTO)\s+`?([A-Z0-9_]+)`?\.`?[A-Z0-9_]+", sql)
    refs += re.findall(r"\bUSE\s+`?([A-Z0-9_]+)", sql)
    refs += re.findall(r"\bSHOW\s+(?:FULL\s+)?TABLES\s+(?:FROM|IN)\s+`?([A-Z0-9_]+)", sql)
    for key in ("database", "schema", "db"):
        if tool_input.get(key):
            refs.append(str(tool_input[key]).upper())
    for schema in set(refs):
        s = schema.lower()
        if s in ("information_schema", "performance_schema", "mysql", "sys"):
            continue
        if not matches_any(s, allowed_schemas):
            block(f"schema '{s}' is not in allowed_db_schemas (context/environments.json).")

allow()
