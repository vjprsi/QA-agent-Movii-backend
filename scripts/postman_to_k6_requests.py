#!/usr/bin/env python3
"""Export selected Postman requests (variables resolved) into requests.json for k6_ladder.js.

  --select "ALL_GET+MAIN_POST"   (default)  → every GET + requests whose name contains 'transfer|payment|create|register'
  --select "Login,Get balance"              → by request name (comma list)
Body placeholders: any value equal to a test_data msisdn/account etc. stays; the literal string ${uniq}
can be put in the Postman body (or added here via --uniq-field) to make each iteration unique.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def walk(items, folder=""):
    for it in items or []:
        if "item" in it:
            yield from walk(it["item"], f"{folder}/{it.get('name', '')}")
        elif "request" in it:
            yield folder, it


def resolve(text, env):
    def rep(m):
        k = m.group(1)
        return str(env.get(k, env.get(k.lower(), m.group(0))))
    return re.sub(r"{{\s*([A-Za-z0-9_.\-]+)\s*}}", rep, text or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", required=True)
    ap.add_argument("--env", required=True, help="newman env.json")
    ap.add_argument("--select", default="ALL_GET+MAIN_POST")
    ap.add_argument("--uniq-field", default="", help="JSON body field to replace with ${uniq} (e.g. externalId)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    col = json.load(open(a.collection, encoding="utf-8"))
    env = {v["key"]: v["value"] for v in json.load(open(a.env, encoding="utf-8")).get("values", [])}
    env.update({k.lower(): v for k, v in list(env.items())})

    names = None if a.select.startswith("ALL_GET") else [s.strip().lower() for s in a.select.split(",")]
    main_post = re.compile(r"(?i)transfer|payment|pago|create|register|recarga|withdraw|retiro|send")
    reqs = []
    for folder, it in walk(col.get("item", [])):
        r = it["request"]
        method = (r.get("method") or "GET").upper()
        name = it.get("name", "")
        url = r.get("url", {})
        raw = url.get("raw") if isinstance(url, dict) else url
        pick = (names is None and (method == "GET" or (method == "POST" and main_post.search(name)))) or \
               (names is not None and name.lower() in names)
        if not pick:
            continue
        headers = {h["key"]: resolve(h.get("value", ""), env) for h in (r.get("header") or []) if not h.get("disabled")}
        auth = r.get("auth") or col.get("auth")
        if auth and auth.get("type") == "bearer" and "Authorization" not in headers:
            tok = next((x.get("value") for x in auth.get("bearer", []) if x.get("key") == "token"), "{{token}}")
            headers["Authorization"] = "Bearer " + resolve(tok, env)
        body = ""
        if r.get("body", {}).get("mode") == "raw":
            body = resolve(r["body"].get("raw", ""), env)
            if a.uniq_field:
                body = re.sub(rf'("{re.escape(a.uniq_field)}"\s*:\s*)"[^"]*"', r'\1"${uniq}"', body)
        reqs.append({"name": name, "folder": folder, "method": method, "url": resolve(raw, env),
                     "headers": headers, "body": body, "weight": 1})
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump({"requests": reqs}, open(a.out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"{len(reqs)} requests → {a.out}: " + ", ".join(f"{r['method']} {r['name']}" for r in reqs))


if __name__ == "__main__":
    main()
