#!/usr/bin/env python3
"""
variables_request.py - turn "BLOCKED: missing input" into a question for the team.

WHY THIS EXISTS
---------------
Cases that need a credential or test datum (client key, MSISDN, PIN/MPIN,
password, OTP, encrypted Authorization, document ids, ...) used to be marked
BLOCKED silently. That hides work the team could unblock in 30 seconds by
handing over a value. This script reads the designed cases, collects the inputs
they declare in the `requires_vars` column of index.csv, subtracts what is
already known (variables.json), and writes a single consolidated request:
what is needed, what for, the format, and exactly which test IDs each value
unblocks. Phase D shows this to the tester and ASKS before calling anything
blocked.

index.csv `requires_vars`: a semicolon-separated list of variable keys per case,
e.g. `client_key;registered_msisdn;mpin`. Chained values obtained during the run
(e.g. an OTP delivered by SMS in a prior step) use the `derived:` prefix, e.g.
`derived:otp` - these are reported as "obtained during the run", not asked for.

Usage:
  python3 -I scripts/variables_request.py --cases-dir test-cases/<svc>/<run> \
      [--variables docs/<svc>/<run>/variables.json] \
      --out docs/<svc>/<run>/variables-request.md
"""
import argparse, csv, json, os

# Catalog of common MOVii prerequisite variables: key -> (purpose, format/example, sensitive)
CATALOG = {
    "client_key":        ("Certification X-Client-Key whose SHA-256 is registered in the QA clientsConfig - gates every business endpoint",
                          "UUID, e.g. 3f2a...-...-...-...-...  (TEST/cert key only)", True),
    "registered_msisdn": ("Phone number of a TEST user that already exists, for login/balance/change-password/forget-password happy paths",
                          "10 digits starting with 3, e.g. 3001234567", False),
    "unregistered_msisdn":("Phone number guaranteed NOT registered, for negative/enumeration cases",
                          "10 digits starting with 3", False),
    "mpin":              ("Current PIN/MPIN of the TEST user (login, change-password 'current')",
                          "the user's PIN (TEST account)", True),
    "password":          ("Current password of the TEST user where distinct from MPIN",
                          ">=8 chars, upper+lower+digit+symbol", True),
    "new_password":      ("A valid NEW password for change-password / forget-password-pin",
                          ">=8 chars, upper+lower+digit+symbol", True),
    "authorization":     ("Pre-built X-Authorization for login = AES-CBC(phoneNumber:pin), OR the crypt key+IV so the harness can build it",
                          "base64 ciphertext, or {key,iv} for TEST only", True),
    "crypt_key_iv":      ("The TEST AES key + IV used to encrypt Authorization / mpin fields (so the harness can craft valid encrypted inputs)",
                          "{key, initialization-vector} for the QA build", True),
    "otp":               ("One-time code for a flow - normally delivered by SMS mid-run",
                          "6 digits (usually derived during the run)", True),
    "document_type":     ("Document type for sign-up (CC/CE/PPT...)", "CC | CE | PPT", False),
    "identification_number":("Document number for sign-up (unused in TEST black/PEP lists)", "digits", False),
    "dob":               ("Date of birth for sign-up", "YYYY-MM-DD", False),
    "bearer_jwt":        ("Bearer JWT for services that require it", "eyJ... (TEST token)", True),
    "db_readonly_user":  ("Read-only qa_* / *_test MySQL user to verify data-at-rest (hash/ciphertext)",
                          "user+password with SELECT on the TEST schema", True),
}


def describe(key):
    if key in CATALOG:
        return CATALOG[key]
    return (f"(describe: input required by the cases below)", "(provide value / format)", True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases-dir", required=True)
    ap.add_argument("--variables")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    # what we already have
    have = set()
    if args.variables and os.path.exists(args.variables):
        try:
            v = json.load(open(args.variables, encoding="utf-8"))
            have = {k for k, val in (v.items() if isinstance(v, dict) else [])
                    if val not in (None, "", [], {})}
        except Exception:
            pass

    # collect requires_vars per case
    idx = os.path.join(args.cases_dir, "index.csv")
    need = {}      # var -> [test ids]
    derived = {}   # var -> [test ids]
    blocked_novars = []  # cases blocked but declaring no vars (env issues etc.)
    n_cases = 0
    with open(idx, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            n_cases += 1
            rv = (row.get("requires_vars") or "").strip()
            status = (row.get("status") or "").upper()
            tid = row.get("id")
            if not rv:
                if status.startswith("BLOCKED"):
                    blocked_novars.append(tid)
                continue
            for raw in rv.split(";"):
                k = raw.strip()
                if not k:
                    continue
                if k.startswith("derived:"):
                    derived.setdefault(k[len("derived:"):], []).append(tid)
                elif k in have:
                    continue  # already satisfied
                else:
                    need.setdefault(k, []).append(tid)

    lines = []
    lines.append(f"# Variables required to run the test cases\n")
    lines.append(f"Cases scanned: {n_cases}. The agent needs the inputs marked "
                 f"**NEED** below before it can run the dependent cases. "
                 f"**TEST environment only** - never production credentials, never "
                 f"a real customer's PIN. Reply with the values (or add them to "
                 f"`variables.json`) and the agent will run the cases listed and "
                 f"replace BLOCKED with a real result.\n")
    if need:
        lines.append("## NEED - please provide\n")
        lines.append("| Variable | Purpose | Format / example | Sensitive | Unblocks (test IDs) |")
        lines.append("|---|---|---|---|---|")
        for k in sorted(need):
            purpose, fmt, sens = describe(k)
            ids = ", ".join(sorted(set(need[k])))
            lines.append(f"| `{k}` | {purpose} | {fmt} | {'yes' if sens else 'no'} | {ids} |")
        lines.append("")
    else:
        lines.append("## NEED\n\nNothing outstanding - every declared variable is already available.\n")

    if derived:
        lines.append("## Obtained during the run (no action needed)\n")
        lines.append("| Variable | How it is obtained | Used by |")
        lines.append("|---|---|---|")
        for k in sorted(derived):
            purpose, fmt, _ = describe(k)
            ids = ", ".join(sorted(set(derived[k])))
            lines.append(f"| `{k}` | {purpose} | {ids} |")
        lines.append("")

    if blocked_novars:
        lines.append("## Blocked for non-variable reasons (environment/config)\n")
        lines.append("These are not fixed by a value - usually an environment or "
                     "deployment fix:\n")
        lines.append(", ".join(sorted(set(blocked_novars))) + "\n")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Wrote {args.out}")
    print(f"NEED: {len(need)} variable(s)" + (": " + ", ".join(sorted(need)) if need else ""))
    if derived:
        print(f"Derived during run: {', '.join(sorted(derived))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
