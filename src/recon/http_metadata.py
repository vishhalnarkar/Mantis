"""Tool 4.1 — HTTP metadata and redirect inspection.

Collects initial/final URL, status code, redirect chain, response time,
content type, selected headers, and approximate response size.

Safety:
- Requires a ValidatedTarget (Stage 03).
- Revalidates every redirect before following it.
- Respects redirect limit, timeout, and response-size limits.
- Read-only GET requests; no form submission or state changes.
- TLS verification is never disabled.
"""

from __future__ import annotations

import time

import requests

from config import config
from logger import get_logger
from target import ValidatedTarget, validate_redirect
from recon.contract import ToolResult, ToolStatus

log = get_logger("recon.http_metadata")

TOOL_NAME = "http_metadata"

SELECTED_HEADERS = (
    "server",
    "content-type",
    "content-length",
    "date",
    "last-modified",
    "x-powered-by",
    "via",
)

MAX_BODY_READ = config.recon.max_response_size


def run_http_metadata(target: ValidatedTarget) -> ToolResult:
    """Perform a bounded, scope-aware GET and record HTTP metadata."""
    result = ToolResult(tool_name=TOOL_NAME, status=ToolStatus.ERROR,
                        source_url=target.parsed.normalized_url)

    url = target.parsed.normalized_url
    timeout = config.recon.request_timeout
    max_redirects = config.recon.max_redirects

    redirect_chain: list[str] = []
    redirect_count = 0

    try:
        current_url = url
        session = requests.Session()
        response = None
        elapsed = 0.0

        while True:
            start = time.perf_counter()
            response = session.get(
                current_url,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
                headers={"User-Agent": "Mantis-Recon/1.0 (bounded, read-only)"},
            )
            elapsed = time.perf_counter() - start

            # Not a redirect -> done
            if response.status_code < 300 or response.status_code >= 400:
                break

            # It's a redirect
            location = response.headers.get("Location", "")
            if not location:
                result.errors.append("Redirect response missing Location header.")
                break

            # Resolve relative redirects
            if not location.startswith(("http://", "https://")):
                base = f"{target.parsed.scheme}://{target.parsed.hostname}:{target.parsed.port}"
                location = base + ("" if location.startswith("/") else "/") + location

            redirect_count += 1
            is_valid, reason = validate_redirect(
                location, target, redirect_count=redirect_count, max_redirects=max_redirects
            )
            if not is_valid:
                result.errors.append(f"Redirect blocked: {reason}")
                result.limits_applied.append("redirect_scope_blocked")
                result.status = ToolStatus.BLOCKED
                response.close()
                result.mark_completed()
                return result

            redirect_chain.append(current_url)
            current_url = location
            response.close()

        # Read body up to size limit. The body text is kept so the
        # orchestrator can reuse it for link discovery and tech
        # fingerprinting without a second request.
        body_chunks: list[bytes] = []
        body_size = 0
        truncated = False
        for chunk in response.iter_content(chunk_size=8192):
            if body_size + len(chunk) > MAX_BODY_READ:
                truncated = True
                result.limits_applied.append(f"response_size_capped_at_{MAX_BODY_READ}")
                break
            body_size += len(chunk)
            body_chunks.append(chunk)
        response.close()
        body_text = b"".join(body_chunks).decode("utf-8", errors="replace")

        # Collect observations
        headers_lower = {k.lower(): v for k, v in response.headers.items()}
        selected = {k: headers_lower.get(k, "") for k in SELECTED_HEADERS if headers_lower.get(k)}

        result.observations = {
            "initial_url": url,
            "final_url": current_url,
            "status_code": response.status_code,
            "redirect_chain": redirect_chain,
            "redirect_count": redirect_count,
            "response_time_ms": round(elapsed * 1000, 2),
            "content_type": headers_lower.get("content-type", ""),
            "response_size_bytes": body_size,
            "truncated": truncated,
            "selected_headers": selected,
            "all_headers": dict(response.headers),
            "body_text": body_text,
        }

        if result.errors:
            result.status = ToolStatus.PARTIAL
        else:
            result.status = ToolStatus.SUCCESS

    except requests.exceptions.SSLError as e:
        result.status = ToolStatus.ERROR
        result.errors.append(f"TLS error: {e}")
        log.warning("TLS error for %s: %s", url, e)
    except requests.exceptions.ConnectTimeout as e:
        result.status = ToolStatus.ERROR
        result.errors.append(f"Connection timeout: {e}")
        log.warning("Timeout for %s: %s", url, e)
    except requests.exceptions.ConnectionError as e:
        result.status = ToolStatus.ERROR
        result.errors.append(f"Connection error: {e}")
        log.warning("Connection error for %s: %s", url, e)
    except requests.exceptions.RequestException as e:
        result.status = ToolStatus.ERROR
        result.errors.append(f"Request failed: {e}")
        log.warning("Request failed for %s: %s", url, e)

    result.mark_completed()
    return result
