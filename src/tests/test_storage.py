"""Tests for Stage 06 — Evidence Model & Persistence.

All tests use temporary databases. No network access required.
"""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from recon.contract import ToolResult, ToolStatus
from recon.assessment import AssessmentResult, AssessmentStatus
from storage.models import (
    EvidenceAssessment,
    EvidenceToolRun,
    EvidenceItem,
    SchemaVersionError,
    ValidationError,
    SCHEMA_VERSION,
)
from storage.redaction import (
    redact_headers,
    sanitize_url,
    sanitize_error,
    prepare_observations_for_storage,
)
from storage.store import (
    EvidenceStore,
    StorageError,
    AssessmentNotFoundError,
    assessment_result_to_evidence,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """Provide a temporary database path."""
    return tmp_path / "test_evidence.db"


@pytest.fixture
def store(tmp_db):
    """Provide an EvidenceStore with a temp database."""
    return EvidenceStore(db_path=tmp_db)


@pytest.fixture
def sample_assessment():
    """A valid EvidenceAssessment for testing."""
    return EvidenceAssessment(
        assessment_id="test-abc-123",
        schema_version=SCHEMA_VERSION,
        target_url="https://example.com/",
        target_hostname="example.com",
        status="completed",
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:01:00+00:00",
        duration_seconds=60.0,
        execution_order=["dns_info", "http_metadata"],
        tool_runs=[
            EvidenceToolRun(
                tool_id="dns_info",
                status="success",
                started_at="2026-01-01T00:00:00+00:00",
                completed_at="2026-01-01T00:00:05+00:00",
                observations={"a_records": ["93.184.216.34"]},
                evidence_count=1,
            ),
            EvidenceToolRun(
                tool_id="http_metadata",
                status="success",
                started_at="2026-01-01T00:00:05+00:00",
                completed_at="2026-01-01T00:01:00+00:00",
                observations={"status_code": 200, "all_headers": {"Server": "nginx"}},
                evidence_count=2,
            ),
        ],
        errors=[],
        warnings=[],
        limits_applied=["response_size_capped_at_512000"],
    )


@pytest.fixture
def sample_orchestrator_result():
    """A Stage 05 AssessmentResult for conversion testing."""
    result = AssessmentResult(
        assessment_id="orch-xyz-789",
        target_url="https://example.com/page?token=secret123",
        status=AssessmentStatus.COMPLETED,
        started_at="2026-01-01T10:00:00+00:00",
        completed_at="2026-01-01T10:02:00+00:00",
    )
    result.execution_order = ["dns_info", "http_metadata", "security_headers"]
    result.tool_results = {
        "dns_info": ToolResult(
            tool_name="dns_info",
            status=ToolStatus.SUCCESS,
            source_url="https://example.com/page?token=secret123",
            observations={"a_records": ["93.184.216.34"], "aaaa_records": []},
        ),
        "http_metadata": ToolResult(
            tool_name="http_metadata",
            status=ToolStatus.SUCCESS,
            source_url="https://example.com/page?token=secret123",
            observations={
                "status_code": 200,
                "all_headers": {
                    "Server": "nginx",
                    "Authorization": "Bearer super-secret-token",
                    "Cookie": "session=abc123",
                    "Content-Type": "text/html",
                },
                "body_text": "<html>" + "x" * 10000 + "</html>",
            },
        ),
        "security_headers": ToolResult(
            tool_name="security_headers",
            status=ToolStatus.SUCCESS,
            source_url="https://example.com/page?token=secret123",
            observations={"present_count": 2, "missing_count": 4},
        ),
    }
    result.errors = []
    result.warnings = []
    result.limits_applied = ["response_size_capped_at_512000"]
    return result


# ── Model Validation Tests ──────────────────────────────────────────────────

class TestEvidenceModels:
    def test_valid_assessment_passes_validation(self, sample_assessment):
        sample_assessment.validate()  # Should not raise

    def test_missing_assessment_id_fails(self):
        a = EvidenceAssessment(assessment_id="", status="completed")
        with pytest.raises(ValidationError):
            a.validate()

    def test_wrong_schema_version_fails(self, sample_assessment):
        sample_assessment.schema_version = 99
        with pytest.raises(SchemaVersionError):
            sample_assessment.validate()

    def test_invalid_status_fails(self, sample_assessment):
        sample_assessment.status = "nonexistent_status"
        with pytest.raises(ValidationError):
            sample_assessment.validate()

    def test_tool_run_validation(self):
        run = EvidenceToolRun(tool_id="", status="success")
        with pytest.raises(ValidationError):
            run.validate()

    def test_tool_run_invalid_status(self):
        run = EvidenceToolRun(tool_id="dns_info", status="bogus")
        with pytest.raises(ValidationError):
            run.validate()

    def test_evidence_item_validation(self):
        item = EvidenceItem(
            evidence_id="",
            assessment_id="a1",
            tool_id="t1",
            evidence_type="http_status",
            observed_value=200,
        )
        with pytest.raises(ValidationError):
            item.validate()

    def test_serialization_round_trip(self, sample_assessment):
        d = sample_assessment.to_dict()
        restored = EvidenceAssessment.from_dict(d)
        assert restored.assessment_id == sample_assessment.assessment_id
        assert restored.status == sample_assessment.status
        assert len(restored.tool_runs) == len(sample_assessment.tool_runs)
        assert restored.tool_runs[0].tool_id == "dns_info"

    def test_from_dict_rejects_wrong_version(self):
        data = {"assessment_id": "x", "schema_version": 99, "status": "completed"}
        with pytest.raises(SchemaVersionError):
            EvidenceAssessment.from_dict(data)


# ── Redaction Tests ─────────────────────────────────────────────────────────

class TestRedaction:
    def test_sensitive_headers_removed(self):
        headers = {
            "Server": "nginx",
            "Authorization": "Bearer secret",
            "Cookie": "session=abc",
            "Set-Cookie": "id=xyz",
            "Content-Type": "text/html",
        }
        redacted = redact_headers(headers)
        assert "Server" in redacted
        assert "Content-Type" in redacted
        assert "Authorization" not in redacted
        assert "Cookie" not in redacted
        assert "Set-Cookie" not in redacted

    def test_url_query_stripped(self):
        url = "https://example.com/page?token=abc&session=xyz"
        sanitized = sanitize_url(url)
        assert "token" not in sanitized
        assert "session" not in sanitized
        assert sanitized == "https://example.com/page"

    def test_error_long_string_truncated(self):
        error = "x" * 1000
        sanitized = sanitize_error(error)
        assert len(sanitized) <= 500

    def test_error_credentials_redacted(self):
        error = "Failed with key ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789012"
        sanitized = sanitize_error(error)
        assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789012" not in sanitized

    def test_body_text_not_persisted(self):
        observations = {
            "status_code": 200,
            "body_text": "<html>large content</html>",
            "all_headers": {"Server": "nginx"},
        }
        prepared = prepare_observations_for_storage(observations)
        assert "body_text" not in prepared
        assert "status_code" in prepared

    def test_sensitive_headers_in_observations_redacted(self):
        observations = {
            "all_headers": {
                "Server": "nginx",
                "Authorization": "Bearer token",
            },
        }
        prepared = prepare_observations_for_storage(observations)
        assert "Authorization" not in prepared["all_headers"]
        assert "Server" in prepared["all_headers"]


# ── Store Tests ─────────────────────────────────────────────────────────────

class TestEvidenceStore:
    def test_save_and_retrieve(self, store, sample_assessment):
        store.save_assessment(sample_assessment)
        loaded = store.get_assessment("test-abc-123")
        assert loaded.assessment_id == "test-abc-123"
        assert loaded.status == "completed"
        assert loaded.target_hostname == "example.com"
        assert len(loaded.tool_runs) == 2

    def test_round_trip_preserves_fields(self, store, sample_assessment):
        store.save_assessment(sample_assessment)
        loaded = store.get_assessment("test-abc-123")
        assert loaded.started_at == sample_assessment.started_at
        assert loaded.completed_at == sample_assessment.completed_at
        assert loaded.duration_seconds == sample_assessment.duration_seconds
        assert loaded.execution_order == sample_assessment.execution_order
        assert loaded.limits_applied == sample_assessment.limits_applied

    def test_missing_assessment_raises_not_found(self, store):
        with pytest.raises(AssessmentNotFoundError):
            store.get_assessment("nonexistent-id")

    def test_multiple_assessments_isolated(self, store):
        a1 = EvidenceAssessment(
            assessment_id="iso-1", status="completed",
            target_url="https://a.com/", target_hostname="a.com",
        )
        a2 = EvidenceAssessment(
            assessment_id="iso-2", status="partial",
            target_url="https://b.com/", target_hostname="b.com",
        )
        store.save_assessment(a1)
        store.save_assessment(a2)

        loaded1 = store.get_assessment("iso-1")
        loaded2 = store.get_assessment("iso-2")
        assert loaded1.target_hostname == "a.com"
        assert loaded2.target_hostname == "b.com"

    def test_list_assessments_ordered(self, store):
        for i in range(5):
            a = EvidenceAssessment(
                assessment_id=f"list-{i}", status="completed",
                target_url=f"https://site{i}.com/", target_hostname=f"site{i}.com",
                started_at=f"2026-01-0{i+1}T00:00:00+00:00",
                completed_at=f"2026-01-0{i+1}T00:01:00+00:00",
            )
            store.save_assessment(a)

        listed = store.list_assessments(limit=10)
        assert len(listed) == 5
        # Most recent first
        assert listed[0]["assessment_id"] == "list-4"

    def test_list_respects_limit(self, store):
        for i in range(10):
            a = EvidenceAssessment(
                assessment_id=f"lim-{i}", status="completed",
                target_url=f"https://s{i}.com/", target_hostname=f"s{i}.com",
            )
            store.save_assessment(a)

        listed = store.list_assessments(limit=3)
        assert len(listed) == 3

    def test_duplicate_id_overwrites(self, store, sample_assessment):
        store.save_assessment(sample_assessment)
        # Save again with same ID but different status
        sample_assessment.status = "partial"
        store.save_assessment(sample_assessment)
        loaded = store.get_assessment("test-abc-123")
        assert loaded.status == "partial"

    def test_delete_assessment(self, store, sample_assessment):
        store.save_assessment(sample_assessment)
        assert store.delete_assessment("test-abc-123") is True
        with pytest.raises(AssessmentNotFoundError):
            store.get_assessment("test-abc-123")

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete_assessment("nope") is False

    def test_corrupt_json_raises_storage_error(self, store, tmp_db):
        """Manually corrupt a record and verify safe failure."""
        store.save_assessment(EvidenceAssessment(
            assessment_id="corrupt-1", status="completed",
            target_url="https://x.com/", target_hostname="x.com",
        ))
        # Corrupt the tool_runs JSON
        conn = sqlite3.connect(str(tmp_db))
        conn.execute(
            "UPDATE assessments SET tool_runs = 'NOT_JSON' WHERE assessment_id = 'corrupt-1'"
        )
        conn.commit()
        conn.close()

        with pytest.raises(StorageError):
            store.get_assessment("corrupt-1")


# ── Conversion Tests ────────────────────────────────────────────────────────

class TestConversion:
    def test_assessment_result_to_evidence(self, sample_orchestrator_result):
        evidence = assessment_result_to_evidence(sample_orchestrator_result)
        assert evidence.assessment_id == "orch-xyz-789"
        assert evidence.status == "completed"
        assert evidence.target_hostname == "example.com"
        assert len(evidence.tool_runs) == 3

    def test_url_query_stripped_in_conversion(self, sample_orchestrator_result):
        evidence = assessment_result_to_evidence(sample_orchestrator_result)
        assert "token" not in evidence.target_url
        assert "secret" not in evidence.target_url

    def test_sensitive_headers_redacted_in_conversion(self, sample_orchestrator_result):
        evidence = assessment_result_to_evidence(sample_orchestrator_result)
        http_run = next(r for r in evidence.tool_runs if r.tool_id == "http_metadata")
        assert "Authorization" not in http_run.observations.get("all_headers", {})
        assert "Cookie" not in http_run.observations.get("all_headers", {})

    def test_body_text_not_in_conversion(self, sample_orchestrator_result):
        evidence = assessment_result_to_evidence(sample_orchestrator_result)
        http_run = next(r for r in evidence.tool_runs if r.tool_id == "http_metadata")
        assert "body_text" not in http_run.observations

    def test_partial_assessment_converts(self):
        result = AssessmentResult(
            assessment_id="partial-1",
            target_url="https://example.com/",
            status=AssessmentStatus.PARTIAL,
        )
        result.tool_results = {
            "dns_info": ToolResult(
                tool_name="dns_info", status=ToolStatus.SUCCESS,
                observations={"a_records": ["1.2.3.4"]},
            ),
            "http_metadata": ToolResult(
                tool_name="http_metadata", status=ToolStatus.ERROR,
                errors=["Connection timeout"],
            ),
        }
        evidence = assessment_result_to_evidence(result)
        assert evidence.status == "partial"
        assert len(evidence.tool_runs) == 2

    def test_failed_assessment_converts(self):
        result = AssessmentResult(
            assessment_id="failed-1",
            target_url="https://example.com/",
            status=AssessmentStatus.FAILED,
        )
        result.errors = ["All tools failed"]
        evidence = assessment_result_to_evidence(result)
        assert evidence.status == "failed"
        assert len(evidence.errors) == 1


# ── Integration: Save + Load + CLI workflow ─────────────────────────────────

class TestIntegration:
    def test_full_save_load_cycle(self, store, sample_orchestrator_result):
        """Simulate: orchestrator -> convert -> save -> load -> verify."""
        evidence = assessment_result_to_evidence(sample_orchestrator_result)
        store.save_assessment(evidence)

        loaded = store.get_assessment("orch-xyz-789")
        assert loaded.assessment_id == "orch-xyz-789"
        assert loaded.status == "completed"
        assert loaded.target_hostname == "example.com"
        assert len(loaded.tool_runs) == 3

        # Verify redaction survived round-trip
        http_run = next(r for r in loaded.tool_runs if r.tool_id == "http_metadata")
        assert "Authorization" not in http_run.observations.get("all_headers", {})
        assert "body_text" not in http_run.observations

    def test_persistence_failure_surfaces(self, tmp_path):
        """Writing to a valid path works."""
        store = EvidenceStore(db_path=tmp_path / "valid.db")
        a = EvidenceAssessment(assessment_id="pf-1", status="completed",
                               target_url="https://x.com/", target_hostname="x.com")
        store.save_assessment(a)  # Should work
        loaded = store.get_assessment("pf-1")
        assert loaded.assessment_id == "pf-1"