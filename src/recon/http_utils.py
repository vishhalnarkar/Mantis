"""Shared scope-aware HTTP helpers for reconnaissance tools.

Provides bounded_get (GET with manual, scope-validated redirect
following) and read_body (size-capped body reading). Used by the
bounded crawler and robots/sitemap retrieval so every outbound request
goes through the same Stage 03 safety gate.
"""

from __future__ import annotations

import requests

from config import config
from logger import get_logger
from target import ValidatedTarget, validate_redirect

log = get_logger("recon.http_utils")

USER_AGENT = "Mantis-Recon/1.0 (bounded, read-only)"


def bounded_get(
    url: str,
    target: ValidatedTarget,
    timeout: float | None = None,
    max_redirects: int | None = None,
) -> requests.Response | None:
    """Scope-aware GET with manually validated redirects.

    Returns the final (non-redirect) response, or None when the request
    fails or any redirect violates the Stage 03 scope policy.
    """
    timeout = config.recon.request_timeout if timeout is None else timeout
    max_redirects = config.recon.max_redirects if max_redirects is None else max_redirects

    session = requests.Session()
    current = url
    for i in range(max_redirects + 1):
        try:
            resp = session.get(
                current,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
                headers={"User-Agent": USER_AGENT},
            )
        except requests.exceptions.RequestException as e:
            log.debug("bounded_get failed for %s: %s", current, e)
            return None

        # Not a redirect -> return for the caller to inspect
        if resp.status_code < 300 or resp.status_code >= 400:
            return resp

        location = resp.headers.get("Location", "")
        if not location:
            resp.close()
            return None

        # Resolve relative redirects against the target origin
        if not location.startswith(("http://", "https://")):
            base = f"{target.parsed.scheme}://{target.parsed.hostname}:{target.parsed.port}"
            location = base + ("" if location.startswith("/") else "/") + location

        ok, reason = validate_redirect(location, target, redirect_count=i + 1, max_redirects=max_redirects)
        resp.close()
        if not ok:
            log.debug("bounded_get redirect blocked for %s: %s", location, reason)
            return None
        current = location
    return None


def read_body(resp: requests.Response, max_bytes: int) -> tuple[str, bool]:
    """Read up to max_bytes from a streaming response.

    Returns (text, truncated). Always closes the response.
    """
    chunks: list[bytes] = []
    size = 0
    truncated = False
    for chunk in resp.iter_content(chunk_size=8192):
        if size + len(chunk) > max_bytes:
            truncated = True
            break
        size += len(chunk)
        chunks.append(chunk)
    resp.close()
    return b"".join(chunks).decode("utf-8", errors="replace"), truncated
