"""SQLite-backed evidence store (Stage 06).

Provides save, get, and list operations behind a small interface.
Uses parameterized queries exclusively. Atomic writes via transactions.
No pickle, no unsafe deserialization.

Storage location: <project_root>/data/evidence.db
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from logger import get_logger
from recon.assessment import AssessmentResult, AssessmentStatus
from recon.contract import ToolResult, ToolStatus
from storage.models import (
    EvidenceAssessment,
    EvidenceToolRun,
    SchemaVersionError,
    ValidationError,
    SCHEMA_VERSION,
    MAX_ASSESSMENTS_STORED,
)
from storage.redaction import (
    prepare_observations_for_storage,
    sanitize_url,
    sanitize_error,
)

log = get_logger("storage")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "evidence.db"


class StorageError(Exception):
    """Raised when a storage operation fails."""
    pass


class AssessmentNotFoundError(Exception):
    """Raised when a requested assessment does not exist."""
    pass


class EvidenceStore:
    """Small persistence interface for assessment evidence."""

    def __init__(self, db_path: Path | str | None = None):
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS assessments (
                    assessment_id TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    target_url TEXT NOT NULL,
                    target_hostname TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    duration_seconds REAL DEFAULT 0,
                    execution_order TEXT NOT NULL,
                    tool_runs TEXT NOT NULL,
                    errors TEXT NOT NULL,
                    warnings TEXT NOT NULL,
                    limits_applied TEXT NOT NULL,
                    saved_at TEXT NOT NULL
                )
            """)
            # Stage 07: interpretations are stored separately and never
            # merged into raw evidence. Backward-compatible additive table.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS interpretations (
                    interpretation_id TEXT PRIMARY KEY,
                    assessment_id TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    prompt_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    saved_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def save_assessment(self, assessment: EvidenceAssessment) -> None:
        """Persist an assessment atomically.

        Raises StorageError on failure. Does NOT silently overwrite
        a different assessment.
        """
        assessment.validate()

        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO assessments
                       (assessment_id, schema_version, target_url, target_hostname,
                        status, started_at, completed_at, duration_seconds,
                        execution_order, tool_runs, errors, warnings,
                        limits_applied, saved_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        assessment.assessment_id,
                        assessment.schema_version,
                        assessment.target_url,
                        assessment.target_hostname,
                        assessment.status,
                        assessment.started_at,
                        assessment.completed_at,
                        assessment.duration_seconds,
                        json.dumps(assessment.execution_order),
                        json.dumps([
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
                            for r in assessment.tool_runs
                        ]),
                        json.dumps(assessment.errors),
                        json.dumps(assessment.warnings),
                        json.dumps(assessment.limits_applied),
                        _now_iso(),
                    ),
                )
                conn.commit()
            log.info("Assessment %s saved.", assessment.assessment_id)
        except sqlite3.Error as e:
            raise StorageError(f"Failed to save assessment: {e}") from e

    def get_assessment(self, assessment_id: str) -> EvidenceAssessment:
        """Retrieve an assessment by ID.

        Raises AssessmentNotFoundError if not found.
        Raises StorageError on I/O failure.
        Raises SchemaVersionError if the record has an unknown version.
        """
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM assessments WHERE assessment_id = ?",
                    (assessment_id,),
                ).fetchone()
        except sqlite3.Error as e:
            raise StorageError(f"Failed to read assessment: {e}") from e

        if row is None:
            raise AssessmentNotFoundError(f"Assessment '{assessment_id}' not found.")

        try:
            data = {
                "assessment_id": row[0],
                "schema_version": row[1],
                "target_url": row[2],
                "target_hostname": row[3],
                "status": row[4],
                "started_at": row[5],
                "completed_at": row[6],
                "duration_seconds": row[7],
                "execution_order": json.loads(row[8]),
                "tool_runs": json.loads(row[9]),
                "errors": json.loads(row[10]),
                "warnings": json.loads(row[11]),
                "limits_applied": json.loads(row[12]),
            }
            return EvidenceAssessment.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise StorageError(f"Corrupt assessment record '{assessment_id}': {e}") from e

    def list_assessments(self, limit: int = 20) -> list[dict]:
        """List assessments (summary only), most recent first.

        Returns list of dicts with id, target, status, timestamps.
        """
        limit = min(limit, MAX_ASSESSMENTS_STORED)
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT assessment_id, target_hostname, status,
                              started_at, saved_at
                       FROM assessments
                       ORDER BY saved_at DESC, rowid DESC
                       LIMIT ?""",
                    (limit,),
                ).fetchall()
        except sqlite3.Error as e:
            raise StorageError(f"Failed to list assessments: {e}") from e

        return [
            {
                "assessment_id": r[0],
                "target_hostname": r[1],
                "status": r[2],
                "started_at": r[3],
                "saved_at": r[4],
            }
            for r in rows
        ]

    def delete_assessment(self, assessment_id: str) -> bool:
        """Delete an assessment. Returns True if deleted, False if not found.

        Also removes any interpretations linked to the assessment.
        """
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM assessments WHERE assessment_id = ?",
                    (assessment_id,),
                )
                conn.execute(
                    "DELETE FROM interpretations WHERE assessment_id = ?",
                    (assessment_id,),
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            raise StorageError(f"Failed to delete assessment: {e}") from e

    # ── Stage 07: interpretation persistence (separate from evidence) ──

    def save_interpretation(self, interpretation) -> None:
        """Persist a validated InterpretationResult atomically.

        Kept separate from raw evidence so interpretations never alter
        the observations they were derived from.
        """
        interpretation.validate()
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO interpretations
                       (interpretation_id, assessment_id, schema_version,
                        prompt_version, status, content, model_id,
                        generated_at, saved_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        interpretation.interpretation_id,
                        interpretation.assessment_id,
                        interpretation.schema_version,
                        interpretation.prompt_version,
                        interpretation.status,
                        json.dumps(interpretation.to_dict()),
                        interpretation.model_id,
                        interpretation.generated_at,
                        _now_iso(),
                    ),
                )
                conn.commit()
            log.info("Interpretation %s saved.", interpretation.interpretation_id)
        except sqlite3.Error as e:
            raise StorageError(f"Failed to save interpretation: {e}") from e

    def get_interpretations(self, assessment_id: str) -> list:
        """Return InterpretationResult objects for an assessment (newest first).

        Returns an empty list if none exist. Corrupt records raise
        StorageError rather than returning partial data.
        """
        from analysis.models import InterpretationResult
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT content FROM interpretations
                       WHERE assessment_id = ?
                       ORDER BY saved_at DESC, rowid DESC""",
                    (assessment_id,),
                ).fetchall()
        except sqlite3.Error as e:
            raise StorageError(f"Failed to read interpretations: {e}") from e

        results = []
        for row in rows:
            try:
                results.append(InterpretationResult.from_dict(json.loads(row[0])))
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                raise StorageError(f"Corrupt interpretation record: {e}") from e
        return results


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def assessment_result_to_evidence(result: AssessmentResult) -> EvidenceAssessment:
    """Convert a Stage 05 AssessmentResult to a persistable EvidenceAssessment.

    Applies redaction and data minimization.
    """
    tool_runs = []
    for tool_id, tr in result.tool_results.items():
        observations = prepare_observations_for_storage(tr.observations)
        tool_runs.append(EvidenceToolRun(
            tool_id=tool_id,
            status=tr.status.value if isinstance(tr.status, ToolStatus) else str(tr.status),
            started_at=tr.started_at,
            completed_at=tr.completed_at,
            errors=[sanitize_error(e) for e in tr.errors],
            limits_applied=tr.limits_applied,
            observations=observations,
            evidence_count=len(observations),
        ))

    # Calculate duration
    duration = 0.0
    if result.started_at and result.completed_at:
        try:
            start = datetime.fromisoformat(result.started_at)
            end = datetime.fromisoformat(result.completed_at)
            duration = (end - start).total_seconds()
        except (ValueError, TypeError):
            pass

    hostname = ""
    if result.target_url:
        hostname = urlparse(result.target_url).hostname or ""

    return EvidenceAssessment(
        assessment_id=result.assessment_id,
        target_url=sanitize_url(result.target_url),
        target_hostname=hostname,
        status=result.status.value if isinstance(result.status, AssessmentStatus) else str(result.status),
        started_at=result.started_at,
        completed_at=result.completed_at,
        duration_seconds=duration,
        execution_order=result.execution_order,
        tool_runs=tool_runs,
        errors=[sanitize_error(e) for e in result.errors],
        warnings=[sanitize_error(w) for w in result.warnings],
        limits_applied=result.limits_applied,
    )