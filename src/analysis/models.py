"""Validated, versioned interpretation output model (Stage 07).

Interpretations are kept strictly separate from raw evidence. Every
claim cites evidence IDs, and citations are validated against the
assessment that was analyzed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from recon.contract import now_iso

INTERPRETATION_SCHEMA_VERSION = 1

MAX_SUMMARY_LENGTH = 1000
MAX_OBSERVATIONS = 10
MAX_OBSERVATION_TEXT = 400
MAX_EVIDENCE_IDS_PER_CLAIM = 5
MAX_INTERPRETATIONS = 10
MAX_INTERPRETATION_TEXT = 400
MAX_LIMITATIONS = 10
MAX_LIMITATION_TEXT = 200
MAX_RECOMMENDATIONS = 10
MAX_RECOMMENDATION_TEXT = 300
MAX_ERROR_LENGTH = 500


class InterpretationStatus(str, Enum):
    COMPLETED = "completed"           # model call succeeded, output validated
    UNAVAILABLE = "unavailable"       # Gemini not configured (missing key/model)
    INVALID_OUTPUT = "invalid-output" # model responded but output failed validation
    FAILED = "failed"                 # API/network/timeout/other error


class InterpretationValidationError(Exception):
    """Raised when model output fails structural or semantic validation."""
    pass


@dataclass
class KeyObservation:
    """A factual observation the model extracted from the evidence."""
    text: str
    evidence_ids: list[str]
    is_hypothesis: bool = False


@dataclass
class SecurityInterpretation:
    """A labeled interpretation (not a confirmed fact)."""
    text: str
    evidence_ids: list[str]
    confidence: str = "low"  # low | medium | high


@dataclass
class InterpretationResult:
    """Validated interpretation of one assessment's evidence."""
    interpretation_id: str
    assessment_id: str
    schema_version: int = INTERPRETATION_SCHEMA_VERSION
    prompt_version: str = ""
    status: str = InterpretationStatus.INVALID_OUTPUT.value
    summary: str = ""
    observations: list[KeyObservation] = field(default_factory=list)
    interpretations: list[SecurityInterpretation] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    evidence_ids_supplied: list[str] = field(default_factory=list)
    unsupported_citations: list[str] = field(default_factory=list)
    model_id: str = ""
    generated_at: str = field(default_factory=now_iso)
    errors: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.interpretation_id:
            raise InterpretationValidationError("interpretation_id is required.")
        if not self.assessment_id:
            raise InterpretationValidationError("assessment_id is required.")
        if self.schema_version != INTERPRETATION_SCHEMA_VERSION:
            raise InterpretationValidationError(
                f"Unsupported interpretation schema version: {self.schema_version}"
            )
        valid_statuses = {s.value for s in InterpretationStatus}
        if self.status not in valid_statuses:
            raise InterpretationValidationError(f"Invalid interpretation status: {self.status}")

    def to_dict(self) -> dict:
        return {
            "interpretation_id": self.interpretation_id,
            "assessment_id": self.assessment_id,
            "schema_version": self.schema_version,
            "prompt_version": self.prompt_version,
            "status": self.status,
            "summary": self.summary,
            "observations": [
                {
                    "text": o.text,
                    "evidence_ids": o.evidence_ids,
                    "is_hypothesis": o.is_hypothesis,
                }
                for o in self.observations
            ],
            "interpretations": [
                {
                    "text": i.text,
                    "evidence_ids": i.evidence_ids,
                    "confidence": i.confidence,
                }
                for i in self.interpretations
            ],
            "limitations": self.limitations,
            "recommendations": self.recommendations,
            "evidence_ids_supplied": self.evidence_ids_supplied,
            "unsupported_citations": self.unsupported_citations,
            "model_id": self.model_id,
            "generated_at": self.generated_at,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InterpretationResult":
        observations = []
        for o in data.get("observations", []):
            if not isinstance(o, dict):
                raise InterpretationValidationError("Malformed observation entry.")
            observations.append(KeyObservation(
                text=str(o.get("text", ""))[:MAX_OBSERVATION_TEXT],
                evidence_ids=[str(x) for x in o.get("evidence_ids", [])][:MAX_EVIDENCE_IDS_PER_CLAIM],
                is_hypothesis=bool(o.get("is_hypothesis", False)),
            ))

        interpretations = []
        for i in data.get("interpretations", []):
            if not isinstance(i, dict):
                raise InterpretationValidationError("Malformed interpretation entry.")
            interpretations.append(SecurityInterpretation(
                text=str(i.get("text", ""))[:MAX_INTERPRETATION_TEXT],
                evidence_ids=[str(x) for x in i.get("evidence_ids", [])][:MAX_EVIDENCE_IDS_PER_CLAIM],
                confidence=str(i.get("confidence", "low")),
            ))

        result = cls(
            interpretation_id=str(data.get("interpretation_id", "")),
            assessment_id=str(data.get("assessment_id", "")),
            schema_version=int(data.get("schema_version", 0)),
            prompt_version=str(data.get("prompt_version", "")),
            status=str(data.get("status", "")),
            summary=str(data.get("summary", ""))[:MAX_SUMMARY_LENGTH],
            observations=observations,
            interpretations=interpretations,
            limitations=[str(x)[:MAX_LIMITATION_TEXT] for x in data.get("limitations", [])][:MAX_LIMITATIONS],
            recommendations=[str(x)[:MAX_RECOMMENDATION_TEXT] for x in data.get("recommendations", [])][:MAX_RECOMMENDATIONS],
            evidence_ids_supplied=[str(x) for x in data.get("evidence_ids_supplied", [])],
            unsupported_citations=[str(x) for x in data.get("unsupported_citations", [])],
            model_id=str(data.get("model_id", "")),
            generated_at=str(data.get("generated_at", "")),
            errors=[str(x)[:MAX_ERROR_LENGTH] for x in data.get("errors", [])],
        )
        result.validate()
        return result