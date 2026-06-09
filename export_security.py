"""Zentrale Redaction-Helfer für Debug-Exports und externe Response-Logs."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTION_VALUE = "***REDACTED***"
SENSITIVE_KEY_PARTS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASS",
    "PWD",
    "AUTH",
    "BEARER",
    "JWT",
    "API_KEY",
    "FTP",
    "MAIL",
    "SMTP",
    "GITHUB",
    "ANTHROPIC",
    "OPENAI",
)

_TEXT_ASSIGNMENT_RE = re.compile(
    r"(?im)(\b[A-Z0-9_.-]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS|PWD|AUTH|BEARER|JWT|FTP|MAIL|SMTP|GITHUB|ANTHROPIC|OPENAI)[A-Z0-9_.-]*\b\s*[:=]\s*)([^\s,'\"}]+|['\"][^'\"]*['\"])",
)
_AUTH_BEARER_RE = re.compile(r"(?im)(Authorization\s*:\s*Bearer\s+)([^\s]+)")
_BEARER_RE = re.compile(r"(?i)(\bBearer\s+)([A-Za-z0-9._~+/=-]+)")
_URL_QUERY_RE = re.compile(r"https?://[^\s'\"<>]+")


def is_sensitive_key(key: object) -> bool:
    upper = str(key).upper()
    return any(part in upper for part in SENSITIVE_KEY_PARTS)


def redact_url(url: str) -> str:
    if not url:
        return url
    try:
        parsed = urlsplit(str(url))
        if not parsed.query:
            return str(url)
        query = []
        changed = False
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if is_sensitive_key(key):
                query.append((key, REDACTION_VALUE))
                changed = True
            else:
                query.append((key, value))
        if not changed:
            return str(url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), parsed.fragment))
    except Exception:
        return str(url)


def redact_obj(value, depth: int = 0):
    if depth > 50:
        return value
    if isinstance(value, dict):
        return {
            key: REDACTION_VALUE if is_sensitive_key(key) else redact_obj(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_obj(item, depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_obj(item, depth + 1) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text: str) -> str:
    if text is None:
        return text
    result = str(text)
    result = _URL_QUERY_RE.sub(lambda m: redact_url(m.group(0)), result)
    result = _AUTH_BEARER_RE.sub(lambda m: m.group(1) + REDACTION_VALUE, result)
    result = _BEARER_RE.sub(lambda m: m.group(1) + REDACTION_VALUE, result)

    def repl(match: re.Match) -> str:
        prefix = match.group(1)
        raw_value = match.group(2)
        quote = raw_value[0] if raw_value.startswith(("'", '"')) else ""
        if quote:
            return f"{prefix}{quote}{REDACTION_VALUE}{quote}"
        return f"{prefix}{REDACTION_VALUE}"

    return _TEXT_ASSIGNMENT_RE.sub(repl, result)


def redact_json_text(text: str) -> str:
    try:
        parsed = json.loads(text)
    except Exception:
        return redact_text(text)
    return json.dumps(redact_obj(parsed), ensure_ascii=False, indent=2)
