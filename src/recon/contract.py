"""Shared tool-result contract for all reconnaissance tools.

Every recon tool returns a ToolResult so the orchestrator (Stage 05)
can collect, persist, and report results uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ToolStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    ERROR = "error"
    SKIPPED = "skipped"


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string (second precision)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ToolResult:
    """Structured result returned by every reconnaissance tool."""

    tool_name: str
    status: ToolStatus
    source_url: str = ""
    started_at: str = ""
    completed_at: str = ""
    observations: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    limits_applied: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.started_at:
            self.started_at = now_iso()
        if not self.completed_at:
            self.completed_at = now_iso()

    def mark_completed(self):
        self.completed_at = now_iso()
