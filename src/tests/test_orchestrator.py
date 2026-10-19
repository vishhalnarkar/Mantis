"""Tests for Stage 05 — Tool Registry & Recon Orchestrator.

All tests are offline: every network boundary is mocked.
"""

import contextlib
import dataclasses
from unittest.mock import patch

import pytest

from config import config
from target import ValidatedTarget, ParsedTarget, ResolutionResult, IPClassification
from recon.contract import ToolResult, ToolStatus
from recon.assessment import AssessmentResult, AssessmentStatus
from recon.context import AssessmentContext
from recon.registry import RECON_TOOL_REGISTRY, get_tool, enabled_tool_ids
from recon.orchestrator import run_assessment, _skip_remaining, EXECUTION_ORDER


EXPECTED_TOOL_IDS = {
    "http_metadata", "security_headers", "robots_sitemap",
    "link_discovery", "tls_metadata", "dns_info", "tech_fingerprint",
}

# Module paths of each tool callable (where the orchestrator imports from)
TOOL_PATHS = {
    "dns_info": "recon.dns_info.run_dns_info",
    "tls_metadata": "recon.tls_metadata.run_tls_metadata",
    "http_metadata": "recon.http_metadata.run_http_metadata",
    "security_headers": "recon.security_headers.run_security_headers",
    "tech_fingerprint": "recon.tech_fingerprint.run_tech_fingerprint",
    "link_discovery": "recon.link_discovery.run_link_discovery",
    "robots_sitemap": "recon.robots_sitemap.run_robots_sitemap",
}


def _make_target(scheme="https", hostname="example.com", port=443):
    parsed = ParsedTarget(
        original_url=f"{scheme}://{hostname}/",
        normalized_url=f"{scheme}://{hostname}/",
        scheme=scheme, hostname=hostname, port=port, path="/", query="",
    )
    resolution = ResolutionResult(
        hostname=hostname, addresses=("93.184.216.34",), blocked=False,
        classifications=(IPClassification(ip="93.184.216.34", is_public=True, reason="public"),),
    )
    return ValidatedTarget(parsed=parsed, resolution=resolution, allowed_origin=(scheme, hostname, port))


def _ok(name: str) -> ToolResult:
    return ToolResult(tool_name=name, status=ToolStatus.SUCCESS)


@pytest.fixture(autouse=True)
def no_sleep():
    """Never actually sleep during tests."""
    with patch("recon.orchestrator.time.sleep"):
        yield


# ── Registry tests ──────────────────────────────────────────────────────────

class TestRegistry:
    def test_registry_contains_exactly_stage04_tools(self):
        assert set(RECON_TOOL_REGISTRY.keys()) == EXPECTED_TOOL_IDS

    def test_registry_entries_have_metadata(self):
        for tid, entry in RECON_TOOL_REGISTRY.items():
            assert entry.id == tid
            assert callable(entry.fn)
            assert entry.description
            assert entry.enabled

    def test_enabled_tool_ids_matches_registry(self):
        assert set(enabled_tool_ids()) == EXPECTED_TOOL_IDS

    def test_get_tool_rejects_unknown_id(self):
        assert get_tool("nonexistent_tool") is None
        assert get_tool("__import__") is None
        assert get_tool("os.system") is None
        assert get_tool("") is None

    def test_get_tool_rejects_disabled_tool(self):
        entry = RECON_TOOL_REGISTRY["dns_info"]
        RECON_TOOL_REGISTRY["dns_info"] = dataclasses.replace(entry, enabled=False)
        try:
            assert get_tool("dns_info") is None
            assert "dns_info" not in enabled_tool_ids()
        finally:
            RECON_TOOL_REGISTRY["dns_info"] = entry

    def test_network_flags_marked(self):
        network_tools = {tid for tid, e in RECON_TOOL_REGISTRY.items() if e.network}
        assert network_tools == {"http_metadata", "robots_sitemap", "tls_metadata", "dns_info"}


# ── Assessment context tests ────────────────────────────────────────────────

class TestAssessmentContext:
    def test_defaults_come_from_config(self):
        ctx = AssessmentContext.create(_make_target())
        assert ctx.request_timeout == config.recon.request_timeout
        assert ctx.max_pages == config.recon.max_pages
        assert ctx.max_depth == config.recon.max_depth
        assert ctx.request_delay == config.recon.request_delay

    def test_overrides_applied(self):
        ctx = AssessmentContext.create(_make_target(), {"request_timeout": 1.5, "max_pages": 2})
        assert ctx.request_timeout == 1.5
        assert ctx.max_pages == 2

    def test_unknown_override_keys_ignored(self):
        ctx = AssessmentContext.create(_make_target(), {"bogus_key": 99, "__class__": None})
        assert not hasattr(ctx, "bogus_key")
        assert ctx.request_timeout == config.recon.request_timeout

    def test_expired_when_deadline_zero(self):
        ctx = AssessmentContext.create(_make_target(), {"assessment_deadline": 0})
        assert ctx.expired
        assert ctx.time_remaining() == 0.0

    def test_cancellation_flag(self):
        ctx = AssessmentContext.create(_make_target())
        assert not ctx.cancelled
        ctx.cancel()
        assert ctx.cancelled


# ── Orchestrator tests ──────────────────────────────────────────────────────

class TestOrchestrator:
    def _patch_all_tools(self, stack, record):
        """Patch every tool to record call order and return success."""
        def recorder(name):
            def _fn(*args, **kwargs):
                record.append((name, args, kwargs))
                return _ok(name)
            return _fn
        for name, path in TOOL_PATHS.items():
            stack.enter_context(patch(path, side_effect=recorder(name)))

    def test_execution_order_constant(self):
        assert list(EXECUTION_ORDER) == [
            "dns_info", "tls_metadata", "http_metadata", "security_headers",
            "tech_fingerprint", "link_discovery", "robots_sitemap",
        ]

    def test_all_tools_run_in_documented_order(self):
        record = []
        with contextlib.ExitStack() as stack:
            self._patch_all_tools(stack, record)
            result = run_assessment(_make_target())

        assert [name for name, _, _ in record] == list(EXECUTION_ORDER)
        assert result.status == AssessmentStatus.COMPLETED
        assert len(result.tool_results) == 7
        assert result.execution_order == list(EXECUTION_ORDER)
        assert result.assessment_id
        assert result.completed_at != ""

    def test_every_tool_receives_validated_target(self):
        record = []
        target = _make_target()
        with contextlib.ExitStack() as stack:
            self._patch_all_tools(stack, record)
            run_assessment(target)

        assert len(record) == 7
        for name, args, kwargs in record:
            assert args and args[0] is target, f"{name} did not receive the target"

    def test_reuse_headers_and_body_from_http_metadata(self):
        hm = _ok("http_metadata")
        hm.observations = {
            "all_headers": {"Server": "nginx"},
            "body_text": "<html>wp-content/</html>",
            "status_code": 200,
        }
        captured = {}

        def capture(name):
            def _fn(*args, **kwargs):
                captured[name] = (args, kwargs)
                return _ok(name)
            return _fn

        with contextlib.ExitStack() as stack:
            for name, path in TOOL_PATHS.items():
                if name == "http_metadata":
                    stack.enter_context(patch(path, return_value=hm))
                else:
                    stack.enter_context(patch(path, side_effect=capture(name)))
            result = run_assessment(_make_target())

        # security_headers received the reused headers positionally
        sh_args, _ = captured["security_headers"]
        assert sh_args[1] == {"Server": "nginx"}
        # tech_fingerprint received headers + body as kwargs
        tf_args, tf_kwargs = captured["tech_fingerprint"]
        assert tf_kwargs["headers"] == {"Server": "nginx"}
        assert tf_kwargs["html_body"] == "<html>wp-content/</html>"
        # link_discovery received the reused body
        ld_args, _ = captured["link_discovery"]
        assert ld_args[1] == "<html>wp-content/</html>"
        assert result.status == AssessmentStatus.COMPLETED

    def test_http_metadata_failure_degrades_dependents_honestly(self):
        """When http_metadata fails, dependent pure tools run with no data
        and report UNAVAILABLE rather than faking results."""
        hm_error = ToolResult(tool_name="http_metadata", status=ToolStatus.ERROR,
                              errors=["Connection error"])
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("recon.dns_info.run_dns_info", return_value=_ok("dns_info")))
            stack.enter_context(patch("recon.tls_metadata.run_tls_metadata", return_value=_ok("tls_metadata")))
            stack.enter_context(patch("recon.http_metadata.run_http_metadata", return_value=hm_error))
            stack.enter_context(patch("recon.robots_sitemap.run_robots_sitemap", return_value=_ok("robots_sitemap")))
            # security_headers, link_discovery, tech_fingerprint run for real
            result = run_assessment(_make_target())

        assert result.tool_results["security_headers"].status == ToolStatus.UNAVAILABLE
        assert result.tool_results["link_discovery"].status == ToolStatus.UNAVAILABLE
        assert result.tool_results["tech_fingerprint"].status == ToolStatus.UNAVAILABLE
        # Independent tools still succeeded
        assert result.tool_results["dns_info"].status == ToolStatus.SUCCESS
        assert result.status == AssessmentStatus.PARTIAL

    def test_tool_failure_does_not_erase_other_results(self):
        with contextlib.ExitStack() as stack:
            for name, path in TOOL_PATHS.items():
                if name == "tls_metadata":
                    stack.enter_context(patch(path, side_effect=RuntimeError("boom")))
                else:
                    stack.enter_context(patch(path, return_value=_ok(name)))
            result = run_assessment(_make_target())

        assert result.status == AssessmentStatus.PARTIAL
        assert result.tool_results["tls_metadata"].status == ToolStatus.ERROR
        assert any("boom" in e for e in result.tool_results["tls_metadata"].errors)
        assert result.tool_results["dns_info"].status == ToolStatus.SUCCESS
        assert result.tool_results["robots_sitemap"].status == ToolStatus.SUCCESS

    def test_zero_deadline_skips_everything(self):
        result = run_assessment(_make_target(), overrides={"assessment_deadline": 0})
        assert result.status == AssessmentStatus.FAILED
        assert all(tr.status == ToolStatus.SKIPPED for tr in result.tool_results.values())
        assert len(result.tool_results) == 7
        assert "assessment_deadline_reached" in result.limits_applied

    def test_cancellation_marks_remaining_skipped(self):
        real_create = AssessmentContext.create

        def cancelled_create(target, overrides=None):
            ctx = real_create(target, overrides)
            ctx.cancel()
            return ctx

        with patch("recon.orchestrator.AssessmentContext.create", side_effect=cancelled_create):
            result = run_assessment(_make_target())

        assert result.status == AssessmentStatus.CANCELLED
        assert all(tr.status == ToolStatus.SKIPPED for tr in result.tool_results.values())

    def test_skip_remaining_preserves_existing_results(self):
        res = AssessmentResult(assessment_id="x", target_url="https://e.com/",
                               status=AssessmentStatus.PARTIAL)
        res.tool_results["dns_info"] = _ok("dns_info")
        _skip_remaining(res, "tls_metadata")

        assert res.tool_results["dns_info"].status == ToolStatus.SUCCESS
        assert res.tool_results["tls_metadata"].status == ToolStatus.SKIPPED
        assert res.tool_results["robots_sitemap"].status == ToolStatus.SKIPPED
        assert "http_metadata" in res.tool_results

    def test_assessment_result_schema(self):
        res = AssessmentResult(assessment_id="abc", target_url="https://e.com/",
                               status=AssessmentStatus.COMPLETED)
        assert res.assessment_id == "abc"
        assert res.started_at != ""
        assert isinstance(res.tool_results, dict)
        assert isinstance(res.errors, list)
        assert isinstance(res.warnings, list)
        assert isinstance(res.limits_applied, list)
        res.mark_completed()
        assert res.completed_at != ""