#!/usr/bin/env python3
"""Build a Postman/Newman environment file from variables.json (+ test_data.json).

Maps common {{var}} names to our variable keys (same alias table as read_variables.py),
and exposes every variables.json key and every test_data row as td_<label>_<field>.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from read_variables import POSTMAN_ALIASES  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vars", required=True)
    ap.add_argument("--test-data", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="qa-agent TEST env")
    a = ap.parse_args()

    V = json.load(open(a.vars, encoding="utf-8"))
    values = {}
    for k, v in V.items():
        values[k] = v
    # aliases: postman name → our key
    for pm_name, key in POSTMAN_ALIASES.items():
        if key in V and pm_name not in values:
            values[pm_name] = V[key]
    # camelCase convenience
    if "base_url" in V:
        values.setdefault("baseUrl", V["base_url"])
    if a.test_data and os.path.exists(a.test_data):
        for row in json.load(open(a.test_data, encoding="utf-8")):
            label = row.get("label", "row")
            for f, v in row.items():
                values[f"td_{label}_{f}"] = v
    env = {"name": a.name,
           "values": [{"key": k, "value": v, "type": "secret" if any(h in k.lower() for h in ("pass", "pin", "secret", "token", "otp", "key")) else "default", "enabled": True}
                      for k, v in values.items()],
           "_postman_variable_scope": "environment"}
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(env, open(a.out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"wrote {a.out} with {len(values)} variables (do not commit; contains secrets)")


if __name__ == "__main__":
    main()
