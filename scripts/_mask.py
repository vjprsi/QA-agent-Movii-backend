"""Masking helpers shared by the QA agent scripts."""
import re

SECRET_KEY_HINTS = ("pass", "pwd", "pin", "secret", "token", "api_key", "apikey", "otp", "cvv", "credential")
PII_KEY_HINTS = ("msisdn", "phone", "celular", "cedula", "document", "email", "card", "pan", "account", "cuenta")


def is_secret_key(key: str) -> bool:
    k = key.lower()
    return any(h in k for h in SECRET_KEY_HINTS)


def is_pii_key(key: str) -> bool:
    k = key.lower()
    return any(h in k for h in PII_KEY_HINTS)


def mask(value) -> str:
    """ab****yz — keep 2+2 chars; short values fully masked."""
    s = str(value) if value is not None else ""
    if len(s) <= 4:
        return "*" * len(s) if s else ""
    return f"{s[:2]}{'*' * min(len(s) - 4, 8)}{s[-2:]}"


def mask_in_text(text: str, values) -> str:
    """Replace every occurrence of each known value with its masked form."""
    for v in sorted({str(x) for x in values if x and len(str(x)) >= 4}, key=len, reverse=True):
        text = text.replace(v, mask(v))
    return text


def mask_json_like(obj, parent_key=""):
    """Recursively mask values whose key looks secret/PII."""
    if isinstance(obj, dict):
        return {k: (mask(v) if (is_secret_key(k) or is_pii_key(k)) and not isinstance(v, (dict, list)) else mask_json_like(v, k))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_json_like(x, parent_key) for x in obj]
    return obj
