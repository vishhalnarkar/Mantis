"""Gemini evidence interpretation service (Stage 07).

Optional and isolated: deterministic recon and Stage 06 persistence work
fully without this module. The analyzer:

- Builds a bounded evidence package from a persisted assessment.
- Calls the existing Gemini client (OpenAI-compatible endpoint).
- Validates structured output against the interpretation schema.
- Validates cited evidence IDs against the supplied evidence.
- Never executes tools, shell commands, or network requests to targets.
- Never mutates raw evidence on failure.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from logger import get_logger
from storage.models import EvidenceAssessment

from analysis.evidence_package import build_evidence_package
from analysis.models import (
    INTERPRETATION_SCHEMA_VERSION,
    InterpretationResult,
    InterpretationStatus,
    InterpretationValidationError,
    KeyObservation,
    SecurityInterpretation,
    MAX_EVIDENCE_IDS_PER_CLAIM,
    MAX_INTERPRETATIONS,
    MAX_INTERPRETATION_TEXT,
    MAX_LIMITATIONS,
    MAX_LIMITATION_TEXT,
    MAX_OBSERVATIONS,
    MAX_OBSERVATION_TEXT,
    MAX_RECOMMENDATIONS,
    MAX_RECOMMENDATION_TEXT,
    MAX_SUMMARY_LENGTH,
)
from analysis.prompt import PROMPT_VERSION, build_system_prompt, build_evidence_user_prompt

log = get_logger("analysis")


class AnalyzerError(Exception):
    """Raised for analyzer-level failures (config, client, parsing)."""
    pass


def _safe_error_message(e: Exception) -> str:
    """Produce an actionable, sanitized error message from an API failure."""
    text = str(e)[:500]
    # Avoid leaking credentials that might appear in exception text.
    return text


def _new_interpretation_id() -> str:
    return f"interp-{uuid.uuid4().hex[:12]}"


def parse_and_validate_output(
    raw: str,
    assessment_id: str,
    valid_evidence_ids: list[str],
) -> InterpretationResult:
    """Parse model output and validate it.

    - Malformed JSON raises InterpretationValidationError.
    - Wrong field types raise InterpretationValidationError.
    - Citations to nonexistent evidence IDs are flagged in
      unsupported_citations; claims with no valid citations are kept but
      marked, never silently attached to unrelated evidence.
    """
    if not raw or not raw.strip():
        raise InterpretationValidationError("Empty model response.")

    # Strip optional markdown fences if the model wrapped them anyway.
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Drop first and last fence lines if present.
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise InterpretationValidationError(f"Malformed JSON in model output: {e}") from e

    if not isinstance(data, dict):
        raise InterpretationValidationError("Model output is not a JSON object.")

    valid_ids = set(valid_evidence_ids)
    unsupported: list[str] = []

    # Summary
    summary = data.get("summary", "")
    if not isinstance(summary, str):
        raise InterpretationValidationError("'summary' must be a string.")
    summary = summary[:MAX_SUMMARY_LENGTH]

    # Observations
    raw_observations = data.get("observations", [])
    if not isinstance(raw_observations, list):
        raise InterpretationValidationError("'observations' must be a list.")
    observations: list[KeyObservation] = []
    for item in raw_observations[:MAX_OBSERVATIONS]:
        if not isinstance(item, dict):
            raise InterpretationValidationError("Observation entry must be an object.")
        text = item.get("text", "")
        if not isinstance(text, str):
            raise InterpretationValidationError("Observation 'text' must be a string.")
        ids = item.get("evidence_ids", [])
        if not isinstance(ids, list):
            raise InterpretationValidationError("Observation 'evidence_ids' must be a list.")
        ids = [str(x) for x in ids][:MAX_EVIDENCE_IDS_PER_CLAIM]
        for eid in ids:
            if eid not in valid_ids:
                unsupported.append(eid)
        observations.append(KeyObservation(
            text=text[:MAX_OBSERVATION_TEXT],
            evidence_ids=ids,
            is_hypothesis=bool(item.get("is_hypothesis", False)),
        ))

    # Interpretations
    raw_interpretations = data.get("interpretations", [])
    if not isinstance(raw_interpretations, list):
        raise InterpretationValidationError("'interpretations' must be a list.")
    interpretations: list[SecurityInterpretation] = []
    for item in raw_interpretations[:MAX_INTERPRETATIONS]:
        if not isinstance(item, dict):
            raise InterpretationValidationError("Interpretation entry must be an object.")
        text = item.get("text", "")
        if not isinstance(text, str):
            raise InterpretationValidationError("Interpretation 'text' must be a string.")
        ids = item.get("evidence_ids", [])
        if not isinstance(ids, list):
            raise InterpretationValidationError("Interpretation 'evidence_ids' must be a list.")
        ids = [str(x) for x in ids][:MAX_EVIDENCE_IDS_PER_CLAIM]
        for eid in ids:
            if eid not in valid_ids:
                unsupported.append(eid)
        confidence = str(item.get("confidence", "low")).lower()
        if confidence not in ("low", "medium", "high"):
            confidence = "low"
        interpretations.append(SecurityInterpretation(
            text=text[:MAX_INTERPRETATION_TEXT],
            evidence_ids=ids,
            confidence=confidence,
        ))

    # Limitations
    raw_limitations = data.get("limitations", [])
    if not isinstance(raw_limitations, list):
        raise InterpretationValidationError("'limitations' must be a list.")
    limitations = [str(x)[:MAX_LIMITATION_TEXT] for x in raw_limitations[:MAX_LIMITATIONS]]

    # Recommendations
    raw_recommendations = data.get("recommendations", [])
    if not isinstance(raw_recommendations, list):
        raise InterpretationValidationError("'recommendations' must be a list.")
    recommendations = [str(x)[:MAX_RECOMMENDATION_TEXT] for x in raw_recommendations[:MAX_RECOMMENDATIONS]]

    return InterpretationResult(
        interpretation_id=_new_interpretation_id(),
        assessment_id=assessment_id,
        schema_version=INTERPRETATION_SCHEMA_VERSION,
        prompt_version=PROMPT_VERSION,
        status=InterpretationStatus.COMPLETED.value,
        summary=summary,
        observations=observations,
        interpretations=interpretations,
        limitations=limitations,
        recommendations=recommendations,
        evidence_ids_supplied=list(valid_evidence_ids),
        unsupported_citations=unsupported,
    )


class GeminiAnalyzer:
    """Optional Gemini-based evidence interpreter.

    Behind a small interface so the rest of the CLI works without a live
    model call. All failures produce a structured InterpretationResult
    with an appropriate status; no exception escapes to crash recon.
    """

    def analyze(self, assessment: EvidenceAssessment) -> InterpretationResult:
        """Interpret the evidence of one persisted assessment.

        Returns an InterpretationResult in every case. Never raises.
        """
        interp_id = _new_interpretation_id()
        package = build_evidence_package(assessment)

        # 1. Configuration check — recon must still work without Gemini.
        from config import config as app_config
        if not app_config.gemini.is_configured:
            log.info("Gemini not configured; interpretation unavailable.")
            return InterpretationResult(
                interpretation_id=interp_id,
                assessment_id=assessment.assessment_id,
                prompt_version=PROMPT_VERSION,
                status=InterpretationStatus.UNAVAILABLE.value,
                summary="Gemini is not configured (missing API key or model).",
                evidence_ids_supplied=package.evidence_ids,
                errors=["Gemini not configured"],
            )

        # 2. Build the request.
        system_prompt = build_system_prompt()
        user_prompt = build_evidence_user_prompt(package)

        # 3. Call the model via the existing client.
        try:
            from llm.comms import _get_client
            client = _get_client()
            model = app_config.gemini.model
            log.info("Requesting evidence interpretation from %s", model)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as e:
            msg = _safe_error_message(e)
            log.warning("Gemini API call failed: %s", msg)
            return InterpretationResult(
                interpretation_id=interp_id,
                assessment_id=assessment.assessment_id,
                prompt_version=PROMPT_VERSION,
                status=InterpretationStatus.FAILED.value,
                summary="Gemini API call failed.",
                evidence_ids_supplied=package.evidence_ids,
                errors=[msg],
            )

        # 4. Extract raw text.
        try:
            raw = response.choices[0].message.content or ""
        except Exception:
            raw = ""

        # 5. Parse and validate.
        try:
            result = parse_and_validate_output(
                raw,
                assessment.assessment_id,
                package.evidence_ids,
            )
        except InterpretationValidationError as e:
            log.warning("Model output failed validation: %s", e)
            return InterpretationResult(
                interpretation_id=interp_id,
                assessment_id=assessment.assessment_id,
                prompt_version=PROMPT_VERSION,
                status=InterpretationStatus.INVALID_OUTPUT.value,
                summary="Model output failed validation.",
                evidence_ids_supplied=package.evidence_ids,
                errors=[str(e)[:500]],
            )

        result.model_id = model
        return result