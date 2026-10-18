"""Tests for src/tools/log_analyzer.py"""

from tools.log_analyzer import analyze_logs


def test_valid_log_text_returns_success():
    result = analyze_logs("line one\nline two\nline three")
    assert result["status"] == "success"
    assert result["line_count"] == 3
    assert result["errors"] == []


def test_empty_log_text_returns_error():
    result = analyze_logs("")
    assert result["status"] == "error"
    assert result["line_count"] == 0
    assert "Log text is empty." in result["errors"]


def test_whitespace_only_log_text_returns_error():
    result = analyze_logs("   \n  \n")
    assert result["status"] == "error"
    assert result["line_count"] == 0
