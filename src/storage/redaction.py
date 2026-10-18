"""Redaction and data-minimization utilities for evidence persistence.

Ensures no secrets, sensitive headers, or oversized payloads reach
the storage layer. Applied BEFORE any write.
"""

from __future__ import annotations

import re

# Headers that must never be persisted
SENSITIVE_HEADERS = frozenset({
    "authorization",
    "cookie",
    "set-cookie",
    "proxy-authorization",
    "www-authenticate",
    "x-api-key",
})

# Maximum lengths for persisted string fields
MAX_URL_LENGTH = 2048
MAX_ERROR_LENGTH = 500
MAX_OBSERVATION_VALUE_LENGTH = 10_000
MAX_BODY_PERSIST_LENGTH = 5000  # We do NOT persist full page bodies


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Remove sensitive headers and truncate values."""
    redacted = {}
    for key, value in headers.items():
        if key.lower() in SENSITIVE_HEADERS:
            continue
        redacted[key] = str(value)[:200]
    return redacted


def sanitize_url(url: str) -> str:
    """Truncate URL and strip query parameters that might contain tokens."""
    if not url:
        return ""
    # Remove query string entirely for persistence (may contain tokens)
    base = url.split("?")[0]
    return base[:MAX_URL_LENGTH]


def sanitize_error(error: str) -> str:
    """Truncate error messages; strip potential credential patterns."""
    if not error:
        return ""
    # Remove anything that looks like an API key or token
    sanitized = re.sub(r"[A-Za-z0-9_-]{32,}", "[REDACTED]", error)
    return sanitized[:MAX_ERROR_LENGTH]


def bound_value(value, max_length: int = MAX_OBSERVATION_VALUE_LENGTH):
    """Bound a value for persistence. Truncates strings, caps lists."""
    if isinstance(value, str):
        return value[:max_length]
    if isinstance(value, list):
        return value[:50]  # Cap list length
    if isinstance(value, dict):
        return {k: bound_value(v, max_length // 2) for k, v in list(value.items())[:20]}
    return value


def prepare_observations_for_storage(observations: dict) -> dict:
    """Prepare tool observations for safe persistence.

    - Removes body_text (too large, not needed for evidence).
    - Redacts sensitive headers.
    - Bounds all values.
    """
    prepared = {}
    for key, value in observations.items():
        if key == "body_text":
            continue  # Never persist full page bodies
        if key == "all_headers":
            prepared[key] = redact_headers(value) if isinstance(value, dict) else {}
        elif key == "selected_headers":
            prepared[key] = redact_headers(value) if isinstance(value, dict) else {}
        else:
            prepared[key] = bound_value(value)
    return prepared