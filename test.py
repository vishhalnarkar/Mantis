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
import socket as _socket
import inspect
from unittest.mock import patch, MagicMock
import target as target_module
import cli as cli_module
from recon.contract import ToolResult, ToolStatus
from recon.http_metadata import run_http_metadata
from recon.security_headers import run_security_headers
from recon.robots_sitemap import run_robots_sitemap
from recon.link_discovery import run_link_discovery
from recon.tls_metadata import run_tls_metadata
from recon.dns_info import run_dns_info
from recon.tech_fingerprint import run_tech_fingerprint

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
        check("is_configured False when key missing", not cfg_missing.gemini.is_configured)

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
        comms.config = AppConfig(gemini=GeminiConfig())
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

    # 8 · Target Validation (Stage 03) ──────────────────────────────
    section("8 · Target Validation (Stage 03)")

    # Pure parsing / normalization
    p = target_module.parse_url("HTTP://EXAMPLE.com/Path#frag")
    check("parse: scheme lowercased", isinstance(p, target_module.ParsedTarget) and p.scheme == "http")
    check("parse: hostname lowercased", p.hostname == "example.com")
    check("parse: default port applied", p.port == 80)
    check("parse: fragment removed", "#" not in p.normalized_url)

    p2 = target_module.parse_url("https://example.com")
    check("parse: https default port 443", p2.port == 443)

    p3 = target_module.parse_url("https://example.com:8443/x?q=1")
    check("parse: explicit port kept", p3.port == 8443)
    check("parse: query preserved", p3.query == "q=1")

    for bad, expected_code in [
        ("", target_module.TargetErrorCode.MALFORMED_URL),
        ("example.com", target_module.TargetErrorCode.MISSING_SCHEME),
        ("ftp://example.com", target_module.TargetErrorCode.UNSUPPORTED_SCHEME),
        ("file:///etc/passwd", target_module.TargetErrorCode.UNSUPPORTED_SCHEME),
        ("http://user:pass@example.com", target_module.TargetErrorCode.EMBEDDED_CREDENTIALS),
        ("http://example.com:99999/", target_module.TargetErrorCode.INVALID_PORT),
        ("http://", target_module.TargetErrorCode.MISSING_HOST),
    ]:
        r = target_module.parse_url(bad)
        check(f"parse rejects {bad!r}", isinstance(r, target_module.TargetValidationError) and r.code == expected_code)

    # IP classification
    for ip, want_public, want_reason in [
        ("93.184.216.34", True, "public"),
        ("127.0.0.1", False, "loopback"),
        ("10.0.0.1", False, "private"),
        ("192.168.1.1", False, "private"),
        ("169.254.1.1", False, "link_local"),
        ("0.0.0.0", False, "unspecified"),
        ("224.0.0.1", False, "multicast"),
        ("::1", False, "loopback"),
        ("fe80::1", False, "link_local"),
    ]:
        c = target_module.classify_ip(ip)
        check(f"classify {ip} -> {want_reason}", c.is_public == want_public and c.reason == want_reason)

    # DNS resolution (mocked)
    with patch("target.socket.getaddrinfo") as gai:
        gai.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
        res = target_module.resolve_hostname("example.com")
        check("resolve: public host allowed", not res.blocked and res.addresses == ("93.184.216.34",))

    with patch("target.socket.getaddrinfo") as gai:
        gai.return_value = [(2, 1, 6, "", ("192.168.0.1", 0))]
        res = target_module.resolve_hostname("internal.example.com")
        check("resolve: private host blocked", res.blocked)

    with patch("target.socket.getaddrinfo") as gai:
        gai.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
            (2, 1, 6, "", ("10.0.0.5", 0)),
        ]
        res = target_module.resolve_hostname("mixed.example.com")
        check("resolve: mixed answers blocked", res.blocked)

    with patch("target.socket.getaddrinfo") as gai:
        gai.return_value = []
        res = target_module.resolve_hostname("empty.example.com")
        check("resolve: empty answer blocked", res.blocked)

    with patch("target.socket.getaddrinfo") as gai:
        gai.side_effect = _socket.gaierror("NXDOMAIN")
        res = target_module.resolve_hostname("nxdomain.example.com")
        check("resolve: NXDOMAIN blocked", res.blocked)

    res = target_module.resolve_hostname("127.0.0.1")
    check("resolve: loopback literal blocked (no DNS)", res.blocked)

    # Full validate_target + redirect policy (mocked DNS)
    with patch("target.socket.getaddrinfo") as gai:
        gai.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
        vt = target_module.validate_target("https://example.com/")
        check("validate_target: public target accepted", isinstance(vt, target_module.ValidatedTarget))
        check("validate_target: allowed origin set", vt.allowed_origin == ("https", "example.com", 443))

        ok, _ = target_module.validate_redirect("https://example.com/about", vt)
        check("redirect: same origin allowed", ok)
        ok, _ = target_module.validate_redirect("https://other.com/", vt)
        check("redirect: different host blocked", not ok)
        ok, _ = target_module.validate_redirect("https://example.com:8443/", vt)
        check("redirect: different port blocked", not ok)
        ok, _ = target_module.validate_redirect("http://example.com/", vt)
        check("redirect: scheme change blocked", not ok)
        ok, _ = target_module.validate_redirect("https://example.com/", vt, redirect_count=10, max_redirects=10)
        check("redirect: limit exceeded blocked", not ok)
        ok, _ = target_module.validate_redirect("ftp://example.com/", vt)
        check("redirect: invalid scheme blocked", not ok)

    vt_loopback = target_module.validate_target("http://127.0.0.1/")
    check("validate_target: loopback rejected", isinstance(vt_loopback, target_module.TargetValidationError))

    with patch("target.socket.getaddrinfo") as gai:
        gai.return_value = [(2, 1, 6, "", ("10.1.2.3", 0))]
        vt_priv = target_module.validate_target("https://internal.corp/")
        check("validate_target: private DNS rejected", isinstance(vt_priv, target_module.TargetValidationError))

    # CLI exposes the new menu option
    check("CLI menu offers target validation", "Validate Target URL" in inspect.getsource(cli_module.cli))

    # 9 · Recon Tools (Stage 04) ────────────────────────────────────
    section("9 · Recon Tools (Stage 04)")

    # Helper to create a test target
    from target import ParsedTarget, ResolutionResult, IPClassification, ValidatedTarget

    def _test_target(scheme="https", hostname="example.com", port=443):
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

    tt = _test_target()

    # Contract
    tr = ToolResult(tool_name="test", status=ToolStatus.SUCCESS)
    check("ToolResult has required fields", tr.tool_name == "test" and tr.started_at != "")
    check("ToolStatus enum values", ToolStatus.SUCCESS == "success" and ToolStatus.ERROR == "error")

    # Security headers (pure, no network)
    sh_result = run_security_headers(tt, {"Strict-Transport-Security": "max-age=31536000", "X-Frame-Options": "DENY"})
    check("security_headers: detects present headers", sh_result.status == ToolStatus.SUCCESS and sh_result.observations["present_count"] == 2)
    check("security_headers: detects missing headers", sh_result.observations["missing_count"] == 4)

    sh_none = run_security_headers(tt, None)
    check("security_headers: unavailable without input", sh_none.status == ToolStatus.UNAVAILABLE)

    # Link discovery (pure, no network)
    html = '<html><a href="/about">A</a><a href="https://evil.com">B</a><a href="javascript:void(0)">C</a></html>'
    ld_result = run_link_discovery(tt, html)
    check("link_discovery: same-origin links found", ld_result.status == ToolStatus.SUCCESS and ld_result.observations["same_origin_count"] >= 1)
    check("link_discovery: other-origin filtered", ld_result.observations["skipped_other_origin"] >= 1)
    check("link_discovery: non-http ignored", ld_result.observations["skipped_non_http"] >= 1)

    ld_empty = run_link_discovery(tt, "")
    check("link_discovery: empty HTML -> unavailable", ld_empty.status == ToolStatus.UNAVAILABLE)

    # Tech fingerprint (pure, no network)
    tf_result = run_tech_fingerprint(tt, headers={"Server": "nginx/1.21"}, html_body='<script src="/wp-content/themes/x/style.css"></script>')
    check("tech_fingerprint: detects nginx", tf_result.status == ToolStatus.SUCCESS and any(f["technology"] == "Nginx" for f in tf_result.observations["findings"]))
    check("tech_fingerprint: detects WordPress", any(f["technology"] == "WordPress" for f in tf_result.observations["findings"]))
    check("tech_fingerprint: confidence labels valid", all(f["confidence"] in ("likely", "possible") for f in tf_result.observations["findings"]))
    check("tech_fingerprint: evidence traceability", all("signal_source" in f and "rationale" in f for f in tf_result.observations["findings"]))

    tf_none = run_tech_fingerprint(tt, headers=None, html_body=None)
    check("tech_fingerprint: no input -> unavailable", tf_none.status == ToolStatus.UNAVAILABLE)

    # TLS metadata (HTTP target -> unavailable)
    http_target = _test_target(scheme="http", hostname="example.com", port=80)
    tls_result = run_tls_metadata(http_target)
    check("tls_metadata: HTTP target -> unavailable", tls_result.status == ToolStatus.UNAVAILABLE)

    # DNS info (uses real resolution for example.com — safe public host)
    dns_result = run_dns_info(tt)
    check("dns_info: returns structured result", dns_result.tool_name == "dns_info" and isinstance(dns_result.observations, dict))
    check("dns_info: A or AAAA records present", len(dns_result.observations.get("a_records", []) + dns_result.observations.get("aaaa_records", [])) > 0 or dns_result.status == ToolStatus.ERROR)
    check("dns_info: MX/NS/TXT marked unavailable", dns_result.observations.get("mx_records") is None)

    # HTTP metadata with mocked requests
    with patch("recon.http_metadata.requests.Session") as mock_sess_cls:
        mock_sess = MagicMock()
        mock_sess_cls.return_value = mock_sess

        class _FakeResp:
            status_code = 200
            headers = {"Content-Type": "text/html", "Server": "nginx"}
            content = b"<html>test</html>"
            url = "https://example.com/"
            def iter_content(self, chunk_size=8192):
                yield self.content
            def close(self): pass

        mock_sess.get.return_value = _FakeResp()
        hm_result = run_http_metadata(tt)
        check("http_metadata: mocked success", hm_result.status == ToolStatus.SUCCESS)
        check("http_metadata: status code captured", hm_result.observations.get("status_code") == 200)
        check("http_metadata: headers captured", "Server" in hm_result.observations.get("all_headers", {}))

    # 10 · Live LLM check (optional) ────────────────────────────────
    if LIVE:
        section("10 · Live LLM check (Gemini)")
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

    # 11 · Pytest suite ─────────────────────────────────────────────
    if not SKIP_PYTEST:
        section("11 · Pytest unit suite")
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
