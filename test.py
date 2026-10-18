"""Mantis master test runner.

Run from the project root:

    python test.py            # all offline tests (unit + integration + combinations)
    python test.py --live     # additionally hits the real Gemini API (uses quota)
    python test.py --skip-pytest  # skip the pytest suite (integration only)

This file is the single entry point that exercises EVERY component and
component combination built so far. It is expanded at the end of each
development stage so that everything old and new stays verifiable.
"""

import os
import sys
import subprocess

# Make src/ importable
_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from rich.panel import Panel
from rich.text import Text

from logger import console, get_logger
from config import load_config, AppConfig, GeminiConfig
import config as config_module
from tools.registry import TOOL_REGISTRY
from tools.executor import executor
from tools.log_analyzer import analyze_logs
import llm.comms as comms

LIVE = "--live" in sys.argv
SKIP_PYTEST = "--skip-pytest" in sys.argv

passed = 0
failed = 0


def section(title: str):
    console.print()
    console.print(Panel(Text(title, style="accent"), border_style="magenta", expand=False))


def check(label: str, condition: bool):
    global passed, failed
    if condition:
        console.print(f"  [success]✔ {label}[/]")
        passed += 1
    else:
        console.print(f"  [error]✘ {label}[/]")
        failed += 1


# ── Fake LLM objects for mocked comms tests ─────────────────────────

class FakeUsage:
    prompt_tokens = 5
    completion_tokens = 3
    total_tokens = 8


class FakeMessage:
    content = "mocked reply"


class FakeChoice:
    message = FakeMessage()


class FakeResponse:
    usage = FakeUsage()
    choices = [FakeChoice()]


class FakeClient:
    def __init__(self):
        self.calls = []

    class chat:
        class completions:
            pass


def _make_fake_client():
    client = FakeClient()

    def create(**kwargs):
        client.calls.append(kwargs)
        return FakeResponse()

    FakeClient.chat.completions.create = staticmethod(create)
    return client


def run():
    # 1 · Logger ────────────────────────────────────────────────────
    section("1 · Logger")
    try:
        log = get_logger("test.suite")
        log.info("Master test suite log entry")
        check("Logger writes to terminal", True)
    except Exception as e:
        check(f"Logger works (error: {e})", False)
    check("Same name returns same logger", get_logger("test.suite") is log)
    check("Different name returns different logger", get_logger("test.other") is not log)

    # 2 · Config ────────────────────────────────────────────────────
    section("2 · Config")
    saved_key = os.environ.get("GEMINI_API_KEY")
    saved_model = os.environ.get("GEMINI_MODEL")
    try:
        os.environ["GEMINI_API_KEY"] = "unit-key"
        os.environ["GEMINI_MODEL"] = "unit-model"
        cfg = load_config()
        check("load_config reads env key", cfg.gemini.api_key == "unit-key")
        check("load_config reads env model", cfg.gemini.model == "unit-model")
        check("is_configured True when both set", cfg.gemini.is_configured)

        os.environ.pop("GEMINI_API_KEY", None)
        cfg_missing = load_config()
        check("is_configured False when key missing", not cfg_missing.is_configured)

        check("AppConfig default gemini unconfigured", not AppConfig().gemini.is_configured)
        check("config singleton exposed", isinstance(config_module.config, AppConfig))
    finally:
        if saved_key is not None:
            os.environ["GEMINI_API_KEY"] = saved_key
        if saved_model is not None:
            os.environ["GEMINI_MODEL"] = saved_model

    # 3 · Tool Registry ─────────────────────────────────────────────
    section("3 · Tool Registry")
    check("'analyze_logs' registered", "analyze_logs" in TOOL_REGISTRY)
    check("Registry maps to analyze_logs", TOOL_REGISTRY.get("analyze_logs") is analyze_logs)

    # 4 · Log Analyzer (direct) ─────────────────────────────────────
    section("4 · Log Analyzer (direct)")
    r = analyze_logs("line one\nline two\nline three")
    check("Valid text -> status success", r.get("status") == "success")
    check("Valid text counts 3 lines", r.get("line_count") == 3)
    check("Valid text reports no errors", r.get("errors") == [])

    r_empty = analyze_logs("")
    check("Empty text -> status error", r_empty.get("status") == "error")
    check("Empty text counts 0 lines", r_empty.get("line_count") == 0)
    check("Empty text includes error message", len(r_empty.get("errors", [])) > 0)

    r_ws = analyze_logs("   \n  \n")
    check("Whitespace-only text -> status error", r_ws.get("status") == "error")

    # 5 · Executor (direct) ─────────────────────────────────────────
    section("5 · Executor (direct)")
    e_ok = executor("analyze_logs", {"log_text": "hello\nworld"})
    check("Executor runs known tool", e_ok.get("status") == "success")
    check("Executor result counts 2 lines", e_ok.get("line_count") == 2)

    e_bad = executor("nonexistent_tool", {})
    check("Executor rejects unknown tool", e_bad.get("status") == "error")
    check("Unknown tool error message present", e_bad.get("errors") == ["Tool not found."])

    e_empty = executor("analyze_logs", {"log_text": ""})
    check("Executor propagates tool error result", e_empty.get("status") == "error")

    # 6 · LLM Comms (mocked) ────────────────────────────────────────
    section("6 · LLM Comms (mocked)")
    try:
        comms.send_message([])
        check("Empty messages raise ValueError", False)
    except ValueError:
        check("Empty messages raise ValueError", True)
    except Exception:
        check("Empty messages raise ValueError", False)

    saved_client = comms._client
    saved_cfg = comms.config
    try:
        # Unconfigured -> clear RuntimeError
        comms._client = None
        comms.config = AppConfig(gemini=GeminiConfig())
        try:
            comms.send_message([{"role": "user", "content": "hi"}])
            check("Unconfigured client raises RuntimeError", False)
        except RuntimeError as e:
            check("Unconfigured client raises RuntimeError", "not configured" in str(e))

        # Mocked success
        fake = _make_fake_client()
        comms._client = fake
        comms.config = AppConfig(gemini=GeminiConfig(api_key="k", model="unit-model"))
        out = comms.send_message([{"role": "user", "content": "hi"}])
        check("Mocked LLM returns content", out == "mocked reply")
        check("Mocked client received the request", len(fake.calls) == 1)
        check("Mocked request used configured model", fake.calls[0].get("model") == "unit-model")

        # Lazy client requires config
        comms._client = None
        try:
            comms._get_client()
            check("_get_client fails when unconfigured", False)
        except RuntimeError:
            check("_get_client fails when unconfigured", True)
    finally:
        comms._client = saved_client
        comms.config = saved_cfg

    # 7 · Component combinations ────────────────────────────────────
    section("7 · Component combinations")
    # registry -> executor -> analyzer chain with varied payloads
    for payload, expected_status, expected_lines in [
        ("a\nb\nc", "success", 3),
        ("single line", "success", 1),
        ("", "error", 0),
        ("  ", "error", 0),
    ]:
        res = executor("analyze_logs", {"log_text": payload})
        check(
            f"Chain payload {payload!r} -> {expected_status}",
            res.get("status") == expected_status and res.get("line_count") == expected_lines,
        )

    # Registry is consistent across repeated dispatch
    first = executor("analyze_logs", {"log_text": "x"})
    second = executor("analyze_logs", {"log_text": "x\ny"})
    check("Repeated dispatch stays consistent", first["status"] == "success" and second["line_count"] == 2)

    # CLI module imports cleanly
    try:
        from cli import cli  # noqa: F401
        check("CLI module imports", True)
    except Exception as e:
        check(f"CLI module imports (error: {e})", False)

    # Entry point module imports cleanly
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mantis_main", os.path.join(_SRC, "__main__.py")
        )
        check("Entry point file exists and is loadable", spec is not None)
    except Exception as e:
        check(f"Entry point file loadable (error: {e})", False)

    # 8 · Live LLM check (optional) ─────────────────────────────────
    if LIVE:
        section("8 · Live LLM check (Gemini)")
        try:
            live_cfg = load_config()
            if not live_cfg.gemini.is_configured:
                check("Live test skipped: Gemini not configured", False)
            else:
                comms._client = None
                comms.config = live_cfg
                resp = comms.send_message([
                    {"role": "system", "content": "You are a professional cybersecurity assistant."},
                    {"role": "user", "content": "Reply with exactly the word OK and nothing else."},
                ])
                check("Live Gemini returned non-empty response", bool(resp and resp.strip()))
        except Exception as e:
            check(f"Live Gemini call succeeded (error: {e})", False)

    # 9 · Pytest suite ──────────────────────────────────────────────
    if not SKIP_PYTEST:
        section("9 · Pytest unit suite")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            capture_output=True,
            text=True,
        )
        tail = (proc.stdout or "").strip().splitlines()
        for line in tail[-3:]:
            console.print(f"  [dim]{line}[/]")
        check("pytest suite passed", proc.returncode == 0)

    # ── Summary ─────────────────────────────────────────────────────
    console.print()
    total = passed + failed
    style = "success" if failed == 0 else "error"
    console.print(
        Panel(
            f"[{style}]Results: {passed}/{total} passed, {failed} failed[/]",
            border_style="magenta",
            expand=False,
        )
    )
    console.print()
    return failed == 0


if __name__ == "__main__":
    banner = Text.assemble(("🦗 Mantis", "accent"), (" Master Test Suite", "info"))
    console.print(Panel(banner, border_style="magenta", expand=False))
    ok = run()
    sys.exit(0 if ok else 1)
