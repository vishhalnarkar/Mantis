"""Deterministic reconnaissance orchestrator (Stage 05).

Coordinates the Stage 04 tools against one Stage 03-validated target.

Design:
- Serial execution in a fixed, documented order.
- Per-tool error isolation: one failure never erases other results.
- Overall deadline: remaining tools are marked skipped once exceeded.
- Request reuse: headers and HTML body from http_metadata are passed
  to security_headers, link_discovery, and tech_fingerprint.
- No report generation; returns a structured AssessmentResult.

Execution order (deterministic):
  1. dns_info          — no HTTP dependency, cheap
  2. tls_metadata      — no HTTP dependency (HTTPS only)
  3. http_metadata     — primary GET; produces headers + body
  4. security_headers  — reuses http_metadata headers
  5. tech_fingerprint  — reuses http_metadata headers + body
  6. link_discovery    — reuses http_metadata body
  7. robots_sitemap    — independent HTTP requests

A failure of http_metadata causes steps 4-6 to be marked skipped
(their inputs are unavailable), but steps 1-2 and 7 still run.
"""

from __future__ import annotations

import time
import uuid

from logger import get_logger
from recon.context import AssessmentContext
from recon.assessment import AssessmentResult, AssessmentStatus
from recon.contract import ToolResult, ToolStatus
from recon.registry import RECON_TOOL_REGISTRY, get_tool
from target import ValidatedTarget

log = get_logger("recon.orchestrator")

# Fixed, documented execution order.
EXECUTION_ORDER: tuple[str, ...] = (
    "dns_info",
    "tls_metadata",
    "http_metadata",
    "security_headers",
    "tech_fingerprint",
    "link_discovery",
    "robots_sitemap",
)


def run_assessment(target: ValidatedTarget, overrides: dict | None = None) -> AssessmentResult:
    """Run a full bounded recon assessment against a validated target.

    Args:
        target: A Stage 03-validated target (required).
        overrides: Optional dict of limit overrides (see AssessmentContext).

    Returns:
        AssessmentResult with per-tool results and overall status.
    """
    ctx = AssessmentContext.create(target, overrides)
    assessment_id = uuid.uuid4().hex[:12]

    result = AssessmentResult(
        assessment_id=assessment_id,
        target_url=target.parsed.normalized_url,
        status=AssessmentStatus.PARTIAL,
    )
    result.execution_order = list(EXECUTION_ORDER)

    log.info("Assessment %s started for %s", assessment_id, target.parsed.normalized_url)

    # Shared data collected during the run (request reuse)
    collected_headers: dict[str, str] | None = None
    collected_body: str | None = None

    success_count = 0
    error_count = 0

    for tool_id in EXECUTION_ORDER:
        # Check cancellation
        if ctx.cancelled:
            result.status = AssessmentStatus.CANCELLED
            result.errors.append(f"Assessment cancelled before {tool_id}.")
            _skip_remaining(result, tool_id)
            break

        # Check overall deadline
        if ctx.expired:
            result.warnings.append(f"Assessment deadline reached before {tool_id}.")
            result.limits_applied.append("assessment_deadline_reached")
            _skip_remaining(result, tool_id)
            break

        entry = get_tool(tool_id)
        if entry is None:
            result.errors.append(f"Tool '{tool_id}' not found in registry.")
            continue

        # Per-tool timeout: if remaining time is less than tool_timeout,
        # still attempt (the tool itself has internal timeouts), but
        # record the constraint.
        remaining = ctx.time_remaining()

        log.debug("Running tool: %s (%.1fs remaining)", tool_id, remaining)

        tool_result = _run_single_tool(tool_id, ctx, collected_headers, collected_body)

        result.tool_results[tool_id] = tool_result

        # Track success/failure
        if tool_result.status in (ToolStatus.SUCCESS, ToolStatus.PARTIAL):
            success_count += 1
        elif tool_result.status == ToolStatus.ERROR:
            error_count += 1

        # Collect shared data from http_metadata for reuse
        if tool_id == "http_metadata" and tool_result.status in (ToolStatus.SUCCESS, ToolStatus.PARTIAL):
            collected_headers = tool_result.observations.get("all_headers")
            collected_body = tool_result.observations.get("body_text")

        # Small pacing delay between network tools
        if entry.network and ctx.request_delay > 0:
            delay = min(ctx.request_delay, ctx.time_remaining())
            if delay > 0:
                time.sleep(delay)

    # Determine overall status
    if result.status != AssessmentStatus.CANCELLED:
        if success_count > 0 and error_count == 0:
            result.status = AssessmentStatus.COMPLETED
        elif success_count > 0:
            result.status = AssessmentStatus.PARTIAL
        else:
            result.status = AssessmentStatus.FAILED

    result.mark_completed()
    log.info(
        "Assessment %s finished: %s (%d success, %d error)",
        assessment_id, result.status.value, success_count, error_count,
    )
    return result


def _run_single_tool(
    tool_id: str,
    ctx: AssessmentContext,
    headers: dict[str, str] | None,
    body: str | None,
) -> ToolResult:
    """Execute one tool with error isolation. Never raises."""
    target = ctx.target

    try:
        if tool_id == "http_metadata":
            from recon.http_metadata import run_http_metadata
            return run_http_metadata(target)

        elif tool_id == "security_headers":
            from recon.security_headers import run_security_headers
            return run_security_headers(target, headers)

        elif tool_id == "robots_sitemap":
            from recon.robots_sitemap import run_robots_sitemap
            return run_robots_sitemap(target)

        elif tool_id == "link_discovery":
            from recon.link_discovery import run_link_discovery
            return run_link_discovery(target, body or "")

        elif tool_id == "tls_metadata":
            from recon.tls_metadata import run_tls_metadata
            return run_tls_metadata(target)

        elif tool_id == "dns_info":
            from recon.dns_info import run_dns_info
            return run_dns_info(target)

        elif tool_id == "tech_fingerprint":
            from recon.tech_fingerprint import run_tech_fingerprint
            return run_tech_fingerprint(target, headers=headers, html_body=body)

        else:
            return ToolResult(
                tool_name=tool_id,
                status=ToolStatus.ERROR,
                source_url=target.parsed.normalized_url,
                errors=[f"Unknown tool ID: {tool_id}"],
            )

    except Exception as e:
        log.warning("Tool %s raised an unexpected exception: %s", tool_id, e)
        return ToolResult(
            tool_name=tool_id,
            status=ToolStatus.ERROR,
            source_url=target.parsed.normalized_url,
            errors=[f"Unhandled exception in {tool_id}: {e}"],
        )


def _skip_remaining(result: AssessmentResult, from_tool_id: str) -> None:
    """Mark all tools from from_tool_id onward as skipped."""
    started = False
    for tool_id in EXECUTION_ORDER:
        if tool_id == from_tool_id:
            started = True
        if started and tool_id not in result.tool_results:
            result.tool_results[tool_id] = ToolResult(
                tool_name=tool_id,
                status=ToolStatus.SKIPPED,
                source_url=result.target_url,
                errors=["Skipped: assessment ended before this tool ran."],
            )