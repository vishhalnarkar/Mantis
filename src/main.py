"""Mantis – integration smoke test.

Run from the project root:
    python src/main.py
"""

import sys
from rich.panel import Panel
from rich.text import Text

# Ensure `src/` is on the path so local imports work when running directly
import os as _os
_src_dir = _os.path.dirname(_os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from logger import console, get_logger
from tools.registry import TOOL_REGISTRY
from tools.executor import executor
from tools.log_analyzer import analyze_logs
from llm.comms import send_message

log = get_logger("main.test")


def section(title: str):
    """Print a styled section header."""
    console.print()
    console.print(Panel(Text(title, style="accent"), border_style="magenta", expand=False))


def run_tests():
    passed = 0
    failed = 0

    def check(label: str, condition: bool):
        nonlocal passed, failed
        if condition:
            console.print(f"  [success]✔ {label}[/]")
            passed += 1
        else:
            console.print(f"  [error]✘ {label}[/]")
            failed += 1

    # ── 1. Logger ───────────────────────────────────────────────────
    section("1 · Logger")
    try:
        log.info("Smoke-test log entry from main.py")
        check("Logger initialises and writes to terminal", True)
    except Exception as e:
        check(f"Logger works (error: {e})", False)

    # ── 2. Tool Registry ───────────────────────────────────────────
    section("2 · Tool Registry")
    check("'analyze_logs' is registered", "analyze_logs" in TOOL_REGISTRY)
    check("Registry maps to the correct callable", TOOL_REGISTRY.get("analyze_logs") is analyze_logs)

    # ── 3. Log Analyzer (direct call) ──────────────────────────────
    section("3 · Log Analyzer (direct)")

    result_ok = analyze_logs("line one\nline two\nline three")
    check("Returns status 'success'", result_ok.get("status") == "success")
    check("Counts 3 lines", result_ok.get("line_count") == 3)
    check("No errors reported", result_ok.get("errors") == [])

    result_empty = analyze_logs("")
    check("Empty input returns status 'error'", result_empty.get("status") == "error")
    check("Empty input reports 0 lines", result_empty.get("line_count") == 0)
    check("Empty input includes error message", len(result_empty.get("errors", [])) > 0)

    # ── 4. Executor ────────────────────────────────────────────────
    section("4 · Executor")

    exec_ok = executor("analyze_logs", {"log_text": "hello\nworld"})
    check("Executor returns success for valid tool", exec_ok.get("status") == "success")
    check("Executor counts 2 lines", exec_ok.get("line_count") == 2)

    exec_bad = executor("nonexistent_tool", {})
    check("Executor returns error for unknown tool", exec_bad.get("status") == "error")

    # ── 5. LLM Communication ───────────────────────────────────────
    section("5 · LLM Communication")
    try:
        messages = [
            {"role": "system", "content": "You are a professional cybersecurity assistant."},
            {"role": "user", "content": "Reply with exactly the word OK and nothing else."},
        ]
        console.print("  [dim]Sending test request (watch the thinking animation)...[/]")
        response = send_message(messages)
        check("LLM returned a non-empty response", bool(response and response.strip()))
        console.print(f"  [dim]Response preview: {response[:120]}...[/]")
    except Exception as e:
        check(f"LLM call succeeded (error: {e})", False)

    # ── Summary ────────────────────────────────────────────────────
    console.print()
    total = passed + failed
    summary_style = "success" if failed == 0 else "error"
    console.print(
        Panel(
            f"[{summary_style}]Results: {passed}/{total} passed, {failed} failed[/]",
            border_style="magenta",
            expand=False,
        )
    )
    console.print()

    return failed == 0


if __name__ == "__main__":
    banner = Text.assemble(("🦗 Mantis", "accent"), (" Test Suite", "info"))
    console.print(Panel(banner, border_style="magenta", expand=False))

    success = run_tests()
    sys.exit(0 if success else 1)
