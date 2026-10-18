"""Structured assessment result returned by the orchestrator.

The orchestrator returns this object to the caller; it does not
generate any narrative report (that is Stage 08).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from recon.contract import ToolResult, now_iso


class AssessmentStatus(str, Enum):
    COMPLETED = "completed"   # all tools ran, none errored
    PARTIAL = "partial"       # some tools ran successfully, some errored/skipped
    FAILED = "failed"         # nothing useful could be collected
    CANCELLED = "cancelled"   # stopped early by user/cancellation


@dataclass
class AssessmentResult:
    """Structured, in-memory result of one bounded recon assessment."""

    assessment_id: str
    target_url: str
    status: AssessmentStatus
    started_at: str = field(default_factory=now_iso)
    completed_at: str = ""
    execution_order: list[str] = field(default_factory=list)
    tool_results: dict[str, ToolResult] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    limits_applied: list[str] = field(default_factory=list)

    def mark_completed(self) -> None:
        self.completed_at = now_iso()
