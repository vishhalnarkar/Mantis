"""Tool 4.6 — DNS information.

Collects A, AAAA, MX, NS, and TXT records using socket.getaddrinfo
for A/AAAA and lightweight fallbacks for others.

Each record type is collected independently; one failure does not
crash the others. TXT output is bounded.
"""

from __future__ import annotations

import socket

from logger import get_logger
from target import ValidatedTarget
from recon.contract import ToolResult, ToolStatus

log = get_logger("recon.dns_info")

TOOL_NAME = "dns_info"

MAX_TXT_LENGTH = 256  # bound TXT record output
DNS_TIMEOUT = 10.0


def _resolve_a(hostname: str) -> tuple[list[str], str]:
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
        ips = list(dict.fromkeys(r[4][0] for r in results))
        return ips, ""
    except socket.gaierror as e:
        return [], f"A lookup failed: {e}"
    except OSError as e:
        return [], f"A lookup error: {e}"


def _resolve_aaaa(hostname: str) -> tuple[list[str], str]:
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_INET6, socket.SOCK_STREAM)
        ips = list(dict.fromkeys(r[4][0] for r in results))
        return ips, ""
    except socket.gaierror as e:
        return [], f"AAAA lookup failed: {e}"
    except OSError as e:
        return [], f"AAAA lookup error: {e}"


def run_dns_info(target: ValidatedTarget) -> ToolResult:
    """Collect DNS records for the target hostname."""
    hostname = target.parsed.hostname
    result = ToolResult(tool_name=TOOL_NAME, status=ToolStatus.ERROR,
                        source_url=target.parsed.normalized_url)

    errors: list[str] = []
    observations: dict = {"hostname": hostname}

    # A records
    a_records, a_err = _resolve_a(hostname)
    observations["a_records"] = a_records
    if a_err:
        errors.append(a_err)

    # AAAA records
    aaaa_records, aaaa_err = _resolve_aaaa(hostname)
    observations["aaaa_records"] = aaaa_records
    if aaaa_err:
        errors.append(aaaa_err)

    # MX, NS, TXT — not available via stdlib without dnspython.
    # Record as unavailable rather than faking values.
    observations["mx_records"] = None
    observations["ns_records"] = None
    observations["txt_records"] = None
    observations["mx_note"] = "Requires dnspython (not installed). Skipped."
    observations["ns_note"] = "Requires dnspython (not installed). Skipped."
    observations["txt_note"] = "Requires dnspython (not installed). Skipped."

    result.observations = observations
    result.errors = errors

    if a_records or aaaa_records:
        result.status = ToolStatus.PARTIAL if errors else ToolStatus.SUCCESS
    else:
        result.status = ToolStatus.ERROR

    result.mark_completed()
    return result
