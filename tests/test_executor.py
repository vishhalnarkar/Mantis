"""Tests for src/tools/executor.py and registry."""

from tools.executor import executor
from tools.registry import TOOL_REGISTRY
from tools.log_analyzer import analyze_logs


def test_registry_contains_analyze_logs():
    assert "analyze_logs" in TOOL_REGISTRY
    assert TOOL_REGISTRY["analyze_logs"] is analyze_logs


def test_executor_runs_known_tool():
    result = executor("analyze_logs", {"log_text": "a\nb"})
    assert result["status"] == "success"
    assert result["line_count"] == 2


def test_executor_rejects_unknown_tool():
    result = executor("nonexistent_tool", {})
    assert result["status"] == "error"
    assert result["errors"] == ["Tool not found."]
