"""Bounded evidence-package builder for the Gemini interpreter (Stage 07).

Converts a persisted EvidenceAssessment into a size-limited, sanitized
package. Observations are labeled UNTRUSTED so the model treats website
content as quoted data, never instructions. Sensitive values were already
redacted at Stage 06 persistence time; this layer applies prompt-level
bounds and reports omissions instead of silently dropping material.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from storage.models import EvidenceAssessment

# Hard cap on the serialized evidence JSON sent to the model.
MAX_EVIDENCE_PACKAGE_CHARS = 24_000
MAX_OBSERVATION_VALUE_CHARS = 800
MAX_OBSERVATIONS_PER_TOOL = 15
MAX_ERROR_TEXT_CHARS = 200


@dataclass
class EvidencePackage:
    """A bounded, sanitized snapshot of one assessment's evidence."""
    assessment_id: str
    target_hostname: str = ""
    assessment_status: str = ""
    started_at: str = ""
    completed_at: str = ""
    execution_order: list[str] = field(default_factory=list)
    tool_runs: list[dict] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    omissions: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({
            "assessment_id": self.assessment_id,
            "target_hostname": self.target_hostname,
            "assessment_status": self.assessment_status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "execution_order": self.execution_order,
            "tool_runs": self.tool_runs,
            "omissions": self.omissions,
        }, indent=2)


def _truncate_value(value: Any, max_chars: int = MAX_OBSERVATION_VALUE_CHARS) -> Any:
    """Bound a single observation value for prompt inclusion."""
    if isinstance(value, str):
        return value[:max_chars]
    if isinstance(value, list):
        return [_truncate_value(v, max_chars // 2) for v in value[:20]]
    if isinstance(value, dict):
        return {k: _truncate_value(v, max_chars // 2) for k, v in list(value.items())[:10]}
    return value


def build_evidence_package(assessment: EvidenceAssessment) -> EvidencePackage:
    """Build a bounded evidence package from a persisted assessment.

    - Evidence IDs are deterministic: "<assessment_id>:<tool_id>".
    - Observations are bounded per value and per count.
    - Body text never reaches the model (already excluded in Stage 06).
    - Omissions are recorded and surfaced in the prompt.
    """
    package = EvidencePackage(
        assessment_id=assessment.assessment_id,
        target_hostname=assessment.target_hostname,
        assessment_status=assessment.status,
        started_at=assessment.started_at,
        completed_at=assessment.completed_at,
        execution_order=list(assessment.execution_order),
    )

    for run in assessment.tool_runs:
        evidence_id = f"{assessment.assessment_id}:{run.tool_id}"
        package.evidence_ids.append(evidence_id)

        bounded_observations = {}
        excluded_keys: list[str] = []
        for key, value in list(run.observations.items())[:MAX_OBSERVATIONS_PER_TOOL]:
            # Defense-in-depth: full page bodies never reach the model,
            # even if an older/unsanitized record slipped through.
            if key == "body_text":
                excluded_keys.append(key)
                continue
            bounded_observations[key] = _truncate_value(value)
        if excluded_keys:
            package.omissions.append(
                f"{run.tool_id}: excluded key(s) {', '.join(sorted(excluded_keys))}"
            )

        omitted_keys = len(run.observations) - MAX_OBSERVATIONS_PER_TOOL
        if omitted_keys > 0:
            package.omissions.append(
                f"{run.tool_id}: {omitted_keys} observation key(s) omitted for size"
            )

        package.tool_runs.append({
            "evidence_id": evidence_id,
            "tool_id": run.tool_id,
            "status": run.status,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "observations": bounded_observations,
            "errors": [e[:MAX_ERROR_TEXT_CHARS] for e in run.errors[:3]],
            "limits_applied": run.limits_applied[:5],
        })

    # Whole-package size guard: drop tool runs from the end until within budget.
    while len(package.to_json()) > MAX_EVIDENCE_PACKAGE_CHARS and package.tool_runs:
        dropped = package.tool_runs.pop()
        dropped_id = dropped["evidence_id"]
        if dropped_id in package.evidence_ids:
            package.evidence_ids.remove(dropped_id)
        package.omissions.append(
            f"tool run {dropped['tool_id']} omitted entirely (package size limit)"
        )

    return package