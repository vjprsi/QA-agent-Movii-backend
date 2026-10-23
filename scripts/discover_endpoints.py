#!/usr/bin/env python3
"""
discover_endpoints.py - deterministic, exhaustive endpoint enumeration.

WHY THIS EXISTS
---------------
Phase A used to rely on a subagent's judgement to list endpoints in
endpoint-map.md, and the descriptor was filled from that. On the baas
orchestrator run that missed 4 of 6 controllers (forget-password-pin/otp,
change-password, balance) - they were in the repo but never enumerated, so
they were never designed or tested. This script removes the judgement call:
it scans every independent source of truth in the cloned repo and prints the
UNION, with provenance, so no exposed route can be silently dropped.

Sources scanned:
  1. Java controllers  - class-level @RequestMapping base path composed with
     method-level @Get/Post/Put/Delete/PatchMapping (and @RequestMapping(method=)).
  2. Postman collection(s) - every request's method + URL path.
  3. API-contract / OpenAPI / Swagger docs - METHOD /path lines and paths: blocks.

Usage:
  python3 -I scripts/discover_endpoints.py --repo workspace/<service> \
      [--descriptor docs/<service>/<run>/descriptor.json] \
      [--out docs/<service>/<run>/discovered-endpoints.json]

Exit code is always 0; it is a discovery aid, not a gate. When --descriptor is
given it prints a MISSING list: discovered routes not present in the descriptor.
That list is what Phase A must reconcile before moving on.
"""
import argparse, json, os, re, sys

HTTP_VERBS = ("GET", "POST", "PUT", "DELETE", "PATCH")

MAPPING_ANNO = {
    "GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
    "DeleteMapping": "DELETE", "PatchMapping": "PATCH",
}


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            return ""


def norm(path):
    """Normalise a route path: single leading slash, collapse doubles, strip trailing."""
    if not path:
        return ""
    path = path.strip().strip('"').strip("'")
    if not path.startswith("/"):
        path = "/" + path
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def _anno_value(text):
    """Pull the path string out of an annotation argument blob, if any."""
    # value = "..." or path = "..." or just "..."
    m = re.search(r'(?:value|path)\s*=\s*"([^"]*)"', text)
    if m:
        return m.group(1)
    m = re.search(r'"([^"]*)"', text)
    return m.group(1) if m else ""


def scan_java(repo):
    out = []
    for root, _dirs, files in os.walk(repo):
        if os.sep + ".git" in root:
            continue
        for fn in files:
            if not fn.endswith("Controller.java"):
                continue
            fp = os.path.join(root, fn)
            src = _read(fp)
            if "@RestController" not in src and "@Controller" not in src:
                continue
            rel = os.path.relpath(fp, repo)
            # class-level base path: first @RequestMapping before first method
            base = ""
            mcls = re.search(r'@RequestMapping\s*\(([^)]*)\)', src)
            if mcls:
                base = _anno_value(mcls.group(1))
            # method-level annotations
            for m in re.finditer(r'@(\w+Mapping)\s*(\(([^)]*)\))?', src):
                anno, args = m.group(1), m.group(3) or ""
                if anno == "RequestMapping" and m.start() == (mcls.start() if mcls else -1):
                    continue  # that's the class-level one
                verb = MAPPING_ANNO.get(anno)
                sub = _anno_value(args)
                if anno == "RequestMapping":
                    vm = re.search(r'method\s*=\s*RequestMethod\.(\w+)', args)
                    verb = vm.group(1) if vm else "GET"
                if verb is None:
                    continue
                full = norm((base.rstrip("/") + "/" + sub.lstrip("/")) if sub else base)
                out.append({"method": verb, "path": full, "source": f"java:{rel}"})
    return out


def scan_postman(repo):
    out = []
    for root, _dirs, files in os.walk(repo):
        if os.sep + ".git" in root:
            continue
        for fn in files:
            if "postman" not in fn.lower() or not fn.lower().endswith(".json"):
                continue
            fp = os.path.join(root, fn)
            try:
                coll = json.loads(_read(fp))
            except Exception:
                continue
            rel = os.path.relpath(fp, repo)

            def walk(items):
                for it in items or []:
                    if "item" in it:
                        walk(it["item"])
                    req = it.get("request")
                    if isinstance(req, dict):
                        method = (req.get("method") or "").upper()
                        url = req.get("url")
                        raw = ""
                        if isinstance(url, dict):
                            seg = url.get("path")
                            raw = "/".join(seg) if isinstance(seg, list) else (url.get("raw") or "")
                        elif isinstance(url, str):
                            raw = url
                        # strip scheme/host/query/variables
                        raw = re.sub(r"^\w+://[^/]+", "", raw)
                        raw = raw.split("?")[0]
                        raw = re.sub(r"\{\{[^}]*\}\}", "", raw)
                        if method and raw:
                            out.append({"method": method, "path": norm(raw),
                                        "source": f"postman:{rel}"})
            walk(coll.get("item", []))
    return out


def scan_docs(repo):
    out = []
    pat = re.compile(r'\b(GET|POST|PUT|DELETE|PATCH)\b\s+(/[\w/{}.\-]+)')
    for root, _dirs, files in os.walk(repo):
        if os.sep + ".git" in root:
            continue
        low = root.lower()
        looks_api = ("doc" in low or "contract" in low or "api" in low)
        for fn in files:
            flow = fn.lower()
            if not (flow.endswith(".md") or flow.endswith(".yaml") or flow.endswith(".yml")
                    or flow.endswith(".json")):
                continue
            if not (looks_api or "contract" in flow or "api" in flow
                    or "openapi" in flow or "swagger" in flow):
                continue
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, repo)
            txt = _read(fp)
            for m in pat.finditer(txt):
                out.append({"method": m.group(1), "path": norm(m.group(2)),
                            "source": f"doc:{rel}"})
    return out


def _param_blind(path):
    """Normalise {anything} path params to {} so {id} and {merchantFileCode} match."""
    return re.sub(r"\{[^}]*\}", "{}", path)


def load_descriptor_keys(descriptor):
    """Return the set of descriptor endpoints as (method, param-blind path).

    Descriptor paths may be stored relative to base_path (e.g. '/merchant-users'
    with base_path '/movii-api/<svc>') or absolute; accept BOTH forms so the
    MISSING check compares like with like and does not cry wolf.
    """
    try:
        d = json.loads(_read(descriptor))
    except Exception:
        return set()
    base = norm(d.get("base_path", "") or "")
    base = "" if base == "/" else base
    keys = set()
    for e in (d.get("contract") or {}).get("endpoints") or []:
        m = e.get("method", "").upper()
        p = norm(e.get("path", ""))
        keys.add((m, _param_blind(p)))
        if base and not p.startswith(base):
            keys.add((m, _param_blind(norm(base + p))))
    return keys


def load_excluded_paths(descriptor):
    """Param-blind paths the descriptor deliberately excludes (foreign/out-of-scope
    routes documented under `excluded_routes`). Any /path token in a route string
    counts; a discovered route matching one is reported as excluded, not missing."""
    try:
        d = json.loads(_read(descriptor))
    except Exception:
        return set()
    out = set()
    for ex in d.get("excluded_routes") or []:
        route = ex.get("route", "") if isinstance(ex, dict) else str(ex)
        for tok in re.findall(r"/[\w/{}.\-]+", route):
            out.add(_param_blind(norm(tok)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--descriptor")
    ap.add_argument("--out")
    args = ap.parse_args()

    if not os.path.isdir(args.repo):
        print(f"ERROR: repo not found: {args.repo}", file=sys.stderr)
        sys.exit(0)

    found = scan_java(args.repo) + scan_postman(args.repo) + scan_docs(args.repo)

    # merge by (method, path), collecting sources
    merged = {}
    for e in found:
        key = (e["method"], e["path"])
        if not e["path"] or e["path"] == "/":
            continue
        merged.setdefault(key, {"method": e["method"], "path": e["path"],
                                "sources": set()})["sources"].add(e["source"].split(":")[0])
    endpoints = sorted(
        ({"method": k[0], "path": k[1], "sources": sorted(v["sources"])}
         for k, v in merged.items()),
        key=lambda x: (x["path"], x["method"]))

    # a "controller route" is one proven by java OR postman (an actually exposed route),
    # as opposed to a doc-only mention.
    controller_routes = [e for e in endpoints
                         if ("java" in e["sources"] or "postman" in e["sources"])]

    print(f"Discovered {len(endpoints)} distinct method+path routes "
          f"({len(controller_routes)} proven by code/postman):\n")
    for e in endpoints:
        tag = "" if ("java" in e["sources"] or "postman" in e["sources"]) else "  (doc-only)"
        print(f"  {e['method']:6} {e['path']:60} [{','.join(e['sources'])}]{tag}")

    missing = []
    if args.descriptor:
        have = load_descriptor_keys(args.descriptor)
        excluded_paths = load_excluded_paths(args.descriptor)
        excluded = [e for e in controller_routes
                    if (e["method"], _param_blind(e["path"])) not in have
                    and _param_blind(e["path"]) in excluded_paths]
        missing = [e for e in controller_routes
                   if (e["method"], _param_blind(e["path"])) not in have
                   and _param_blind(e["path"]) not in excluded_paths]
        print("\n" + "=" * 60)
        if excluded:
            print(f"Excluded by descriptor (documented, {len(excluded)} routes):")
            for e in excluded:
                print(f"  {e['method']:6} {e['path']}")
        if missing:
            print(f"MISSING from descriptor ({len(missing)} exposed routes NOT in "
                  f"descriptor.json and NOT excluded - add them before leaving Phase A):")
            for e in missing:
                print(f"  {e['method']:6} {e['path']}")
        else:
            print("OK: every code/postman-proven route is in the descriptor or "
                  "documented as excluded.")

    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"endpoints": endpoints,
                       "controller_routes": controller_routes,
                       "missing_from_descriptor": missing}, f,
                      ensure_ascii=False, indent=2)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
