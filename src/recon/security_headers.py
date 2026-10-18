"""Tool 4.2 — Security response-header inspection.

Inspects security-related headers from an already-collected HTTP response
(passed as a headers dict) to avoid duplicate requests.

Missing headers are recorded as observations, NOT as confirmed
vulnerabilities. Interpretation belongs to Stage 07.
"""

from __future__ import annotations

from logger import get_logger
from target import ValidatedTarget
from recon.contract import ToolResult, ToolStatus

log = get_logger("recon.security_headers")

TOOL_NAME = "security_headers"

SECURITY_HEADERS = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
)


def run_security_headers(target: ValidatedTarget, headers: dict[str, str] | None = None) -> ToolResult:
    """Analyse security headers from a previously collected response.

    Args:
        target: The validated target (for provenance).
        headers: Response headers dict (keys may be any case). If None,
                 the tool reports unavailable status.
    """
    result = ToolResult(tool_name=TOOL_NAME, status=ToolStatus.ERROR,
                        source_url=target.parsed.normalized_url)

    if headers is None:
        result.status = ToolStatus.UNAVAILABLE
        result.errors.append("No response headers supplied. Run http_metadata first.")
        result.mark_completed()
        return result

    headers_lower = {k.lower(): v for k, v in headers.items()}

    present: dict[str, str] = {}
    missing: list[str] = []

    for h in SECURITY_HEADERS:
        value = headers_lower.get(h)
        if value is not None:
            present[h] = value
        else:
            missing.append(h)

    result.observations = {
        "present_headers": present,
        "missing_headers": missing,
        "checked_count": len(SECURITY_HEADERS),
        "present_count": len(present),
        "missing_count": len(missing),
    }
    result.status = ToolStatus.SUCCESS
    result.mark_completed()
    return result
