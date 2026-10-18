"""Evidence data model for Stage 06 persistence.

Defines validated, versioned structures for assessments, tool runs,
and evidence items. All timestamps are UTC ISO-8601.

Schema version 1 is the initial version. Loading a record with an
unknown version raises SchemaVersionError.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from recon.contract import ToolStatus, now_iso
from recon.assessment import AssessmentStatus

SCHEMA_VERSION = 1
MAX_EVIDENCE_ITEMS_PER_TOOL = 50
MAX_ASSESSMENTS_STORED = 100


class SchemaVersionError(Exception):
    """Raised when a record has an unsupported schema version."""
    pass


class ValidationError(Exception):
    """Raised when evidence data fails validation."""
    pass


@dataclass
class EvidenceItem:
    """A single observation/evidence entry from a tool run."""
    evidence_id: str
    assessment_id: str
    tool_id: str
    evidence_type: str  # e.g. "http_status", "header", "dns_record", "link"
    observed_value: Any
    source_url: str = ""
    observed_at: str = ""
    collection_method: str = "http_get"
    notes: str = ""

    def __post_init__(self):
        if not self.observed_at:
            self.observed_at = now_iso()

    def validate(self) -> None:
        if not self.evidence_id:
            raise ValidationError("EvidenceItem.evidence_id is required.")
        if not self.assessment_id:
            raise ValidationError("EvidenceItem.assessment_id is required.")
        if not self.tool_id:
            raise ValidationError("EvidenceItem.tool_id is required.")
        if not self.evidence_type:
            raise ValidationError("EvidenceItem.evidence_type is required.")


@dataclass
class EvidenceToolRun:
    """Record of one tool's execution within an assessment."""
    tool_id: str
    status: str  # ToolStatus value
    started_at: str = ""
    completed_at: str = ""
    errors: list[str] = field(default_factory=list)
    limits_applied: list[str] = field(default_factory=list)
    observations: dict[str, Any] = field(default_factory=dict)
    evidence_count: int = 0

    def validate(self) -> None:
        if not self.tool_id:
            raise ValidationError("EvidenceToolRun.tool_id is required.")
        valid_statuses = {s.value for s in ToolStatus}
        if self.status not in valid_statuses:
            raise ValidationError(f"Invalid tool status: {self.status}")


@dataclass
class EvidenceAssessment:
    """Top-level persisted assessment record."""
    assessment_id: str
    schema_version: int = SCHEMA_VERSION
    target_url: str = ""
    target_hostname: str = ""
    status: str = ""  # AssessmentStatus value
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    execution_order: list[str] = field(default_factory=list)
    tool_runs: list[EvidenceToolRun] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    limits_applied: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.assessment_id:
            raise ValidationError("EvidenceAssessment.assessment_id is required.")
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Unsupported schema version: {self.schema_version} "
                f"(expected {SCHEMA_VERSION})"
            )
        valid_statuses = {s.value for s in AssessmentStatus}
        if self.status and self.status not in valid_statuses:
            raise ValidationError(f"Invalid assessment status: {self.status}")
        for run in self.tool_runs:
            run.validate()

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return {
            "assessment_id": self.assessment_id,
            "schema_version": self.schema_version,
            "target_url": self.target_url,
            "target_hostname": self.target_hostname,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "execution_order": self.execution_order,
            "tool_runs": [
                {
                    "tool_id": r.tool_id,
                    "status": r.status,
                    "started_at": r.started_at,
                    "completed_at": r.completed_at,
                    "errors": r.errors,
                    "limits_applied": r.limits_applied,
                    "observations": r.observations,
                    "evidence_count": r.evidence_count,
                }
                for r in self.tool_runs
            ],
            "errors": self.errors,
            "warnings": self.warnings,
            "limits_applied": self.limits_applied,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceAssessment":
        """Deserialize from a dict. Validates schema version."""
        version = data.get("schema_version", 0)
        if version != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Unsupported schema version: {version} (expected {SCHEMA_VERSION})"
            )

        tool_runs = []
        for run_data in data.get("tool_runs", []):
            tool_runs.append(EvidenceToolRun(
                tool_id=run_data.get("tool_id", ""),
                status=run_data.get("status", "error"),
                started_at=run_data.get("started_at", ""),
                completed_at=run_data.get("completed_at", ""),
                errors=run_data.get("errors", []),
                limits_applied=run_data.get("limits_applied", []),
                observations=run_data.get("observations", {}),
                evidence_count=run_data.get("evidence_count", 0),
            ))

        assessment = cls(
            assessment_id=data.get("assessment_id", ""),
            schema_version=version,
            target_url=data.get("target_url", ""),
            target_hostname=data.get("target_hostname", ""),
            status=data.get("status", ""),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            duration_seconds=data.get("duration_seconds", 0.0),
            execution_order=data.get("execution_order", []),
            tool_runs=tool_runs,
            errors=data.get("errors", []),
            warnings=data.get("warnings", []),
            limits_applied=data.get("limits_applied", []),
        )
        assessment.validate()
        return assessment