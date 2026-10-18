"""Tests for Stage 04 — Reconnaissance Tool Toolkit.

All tests use mocks/fixtures. No live network access required.
"""

import socket
import ssl
from unittest.mock import patch, MagicMock

import pytest

from target import ValidatedTarget, ParsedTarget, ResolutionResult, IPClassification
from recon.contract import ToolResult, ToolStatus
from recon.http_metadata import run_http_metadata
from recon.security_headers import run_security_headers
from recon.robots_sitemap import run_robots_sitemap
from recon.link_discovery import run_link_discovery
from recon.tls_metadata import run_tls_metadata
from recon.dns_info import run_dns_info
from recon.tech_fingerprint import run_tech_fingerprint


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_target(scheme="https", hostname="example.com", port=443, path="/"):
    """Create a ValidatedTarget for testing."""
    parsed = ParsedTarget(
        original_url=f"{scheme}://{hostname}{path}",
        normalized_url=f"{scheme}://{hostname}{path}",
        scheme=scheme,
        hostname=hostname,
        port=port,
        path=path,
        query="",
    )
    resolution = ResolutionResult(
        hostname=hostname,
        addresses=("93.184.216.34",),
        blocked=False,
        classifications=(IPClassification(ip="93.184.216.34", is_public=True, reason="public"),),
    )
    return ValidatedTarget(parsed=parsed, resolution=resolution, allowed_origin=(scheme, hostname, port))


def _make_http_target():
    return _make_target(scheme="http", hostname="example.com", port=80)


class FakeResponse:
    def __init__(self, status_code=200, headers=None, content=b"", url=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self.url = url or "https://example.com/"

    def iter_content(self, chunk_size=8192):
        yield self.content

    def close(self):
        pass


# ── Tool Contract Tests ──────────────────────────────────────────────────────

class TestToolContract:
    def test_tool_result_has_required_fields(self):
        r = ToolResult(tool_name="test", status=ToolStatus.SUCCESS)
        assert r.tool_name == "test"
        assert r.status == ToolStatus.SUCCESS
        assert r.started_at != ""
        assert r.completed_at != ""
        assert isinstance(r.observations, dict)
        assert isinstance(r.errors, list)
        assert isinstance(r.limits_applied, list)

    def test_tool_status_values(self):
        assert ToolStatus.SUCCESS == "success"
        assert ToolStatus.PARTIAL == "partial"
        assert ToolStatus.UNAVAILABLE == "unavailable"
        assert ToolStatus.BLOCKED == "blocked"
        assert ToolStatus.ERROR == "error"


# ── 4.1 HTTP Metadata Tests ─────────────────────────────────────────────────

class TestHttpMetadata:
    @patch("recon.http_metadata.requests.Session")
    def test_successful_response(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = FakeResponse(
            status_code=200,
            headers={"Content-Type": "text/html", "Server": "nginx"},
            content=b"<html>hello</html>",
        )

        target = _make_target()
        result = run_http_metadata(target)

        assert result.tool_name == "http_metadata"
        assert result.status == ToolStatus.SUCCESS
        assert result.observations["status_code"] == 200
        assert result.observations["content_type"] == "text/html"

    @patch("recon.http_metadata.requests.Session")
    def test_timeout_returns_error(self, mock_session_cls):
        import requests
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.ConnectTimeout()

        target = _make_target()
        result = run_http_metadata(target)

        assert result.status == ToolStatus.ERROR
        assert any("timeout" in e.lower() for e in result.errors)

    @patch("recon.http_metadata.requests.Session")
    def test_connection_error(self, mock_session_cls):
        import requests
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.ConnectionError("refused")

        target = _make_target()
        result = run_http_metadata(target)

        assert result.status == ToolStatus.ERROR
        assert len(result.errors) > 0

    @patch("recon.http_metadata.requests.Session")
    @patch("target.socket.getaddrinfo")
    def test_redirect_within_scope(self, mock_getaddrinfo, mock_session_cls):
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        redirect_resp = FakeResponse(status_code=301, headers={"Location": "https://example.com/new"})
        final_resp = FakeResponse(status_code=200, headers={"Content-Type": "text/html"}, content=b"ok")
        mock_session.get.side_effect = [redirect_resp, final_resp]

        target = _make_target()
        result = run_http_metadata(target)

        assert result.status == ToolStatus.SUCCESS
        assert result.observations["redirect_count"] == 1

    @patch("recon.http_metadata.requests.Session")
    @patch("target.socket.getaddrinfo")
    def test_redirect_to_different_origin_blocked(self, mock_getaddrinfo, mock_session_cls):
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        redirect_resp = FakeResponse(status_code=302, headers={"Location": "https://evil.com/page"})
        mock_session.get.return_value = redirect_resp

        target = _make_target()
        result = run_http_metadata(target)

        assert result.status == ToolStatus.BLOCKED
        assert any("blocked" in e.lower() or "origin" in e.lower() for e in result.errors)

    @patch("recon.http_metadata.requests.Session")
    def test_ssl_error(self, mock_session_cls):
        import requests
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.SSLError("cert verify failed")

        target = _make_target()
        result = run_http_metadata(target)

        assert result.status == ToolStatus.ERROR
        assert any("tls" in e.lower() or "ssl" in e.lower() for e in result.errors)


# ── 4.2 Security Headers Tests ───────────────────────────────────────────────

class TestSecurityHeaders:
    def test_all_headers_present(self):
        headers = {
            "Strict-Transport-Security": "max-age=31536000",
            "Content-Security-Policy": "default-src 'self'",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "camera=()",
        }
        target = _make_target()
        result = run_security_headers(target, headers)

        assert result.status == ToolStatus.SUCCESS
        assert result.observations["present_count"] == 6
        assert result.observations["missing_count"] == 0

    def test_missing_headers(self):
        headers = {"Server": "nginx", "Content-Type": "text/html"}
        target = _make_target()
        result = run_security_headers(target, headers)

        assert result.status == ToolStatus.SUCCESS
        assert result.observations["missing_count"] == 6
        assert result.observations["present_count"] == 0

    def test_partial_headers(self):
        headers = {
            "Strict-Transport-Security": "max-age=31536000",
            "X-Frame-Options": "SAMEORIGIN",
        }
        target = _make_target()
        result = run_security_headers(target, headers)

        assert result.status == ToolStatus.SUCCESS
        assert result.observations["present_count"] == 2
        assert result.observations["missing_count"] == 4

    def test_no_headers_supplied(self):
        target = _make_target()
        result = run_security_headers(target, None)

        assert result.status == ToolStatus.UNAVAILABLE
        assert len(result.errors) > 0

    def test_case_insensitive_matching(self):
        headers = {"STRICT-TRANSPORT-SECURITY": "max-age=100"}
        target = _make_target()
        result = run_security_headers(target, headers)

        assert result.observations["present_count"] == 1
        assert "strict-transport-security" in result.observations["present_headers"]


# ── 4.3 Robots/Sitemap Tests ─────────────────────────────────────────────────

class TestRobotsSitemap:
    @patch("recon.robots_sitemap._bounded_get")
    def test_robots_found_with_sitemap(self, mock_get):
        robots_content = b"User-agent: *\nDisallow: /admin/\nSitemap: https://example.com/sitemap.xml\n"
        mock_get.return_value = FakeResponse(status_code=200, content=robots_content)

        target = _make_target()
        result = run_robots_sitemap(target)

        assert result.status == ToolStatus.SUCCESS
        assert result.observations["robots_status"] == 200
        assert len(result.observations["sitemap_urls"]) == 1
        assert "/admin/" in result.observations["disallow_paths"]

    @patch("recon.robots_sitemap._bounded_get")
    def test_robots_not_found(self, mock_get):
        mock_get.return_value = FakeResponse(status_code=404, content=b"")

        target = _make_target()
        result = run_robots_sitemap(target)

        assert result.status == ToolStatus.SUCCESS
        assert result.observations["robots_status"] == 404

    @patch("recon.robots_sitemap._bounded_get")
    def test_robots_unavailable(self, mock_get):
        mock_get.return_value = None

        target = _make_target()
        result = run_robots_sitemap(target)

        assert result.status == ToolStatus.UNAVAILABLE
        assert len(result.errors) > 0

    @patch("recon.robots_sitemap._bounded_get")
    def test_robots_empty_disallow(self, mock_get):
        robots_content = b"User-agent: *\nAllow: /\n"
        mock_get.return_value = FakeResponse(status_code=200, content=robots_content)

        target = _make_target()
        result = run_robots_sitemap(target)

        assert result.status == ToolStatus.SUCCESS
        assert result.observations["disallow_paths"] == []


# ── 4.4 Link Discovery Tests ─────────────────────────────────────────────────

class TestLinkDiscovery:
    def test_same_origin_links_extracted(self):
        html = """
        <html><body>
            <a href="/about">About</a>
            <a href="/contact">Contact</a>
            <a href="https://example.com/blog">Blog</a>
        </body></html>
        """
        target = _make_target()
        result = run_link_discovery(target, html)

        assert result.status == ToolStatus.SUCCESS
        assert result.observations["same_origin_count"] >= 3

    def test_other_origin_links_filtered(self):
        html = """
        <html><body>
            <a href="https://evil.com/page">Evil</a>
            <a href="https://other-site.org/">Other</a>
        </body></html>
        """
        target = _make_target()
        result = run_link_discovery(target, html)

        assert result.status == ToolStatus.SUCCESS
        assert result.observations["same_origin_count"] == 0
        assert result.observations["skipped_other_origin"] == 2

    def test_non_http_links_ignored(self):
        html = """
        <html><body>
            <a href="javascript:void(0)">JS</a>
            <a href="mailto:test@example.com">Mail</a>
            <a href="tel:+1234567890">Phone</a>
        </body></html>
        """
        target = _make_target()
        result = run_link_discovery(target, html)

        assert result.status == ToolStatus.SUCCESS
        assert result.observations["same_origin_count"] == 0
        assert result.observations["skipped_non_http"] == 3

    def test_fragments_removed(self):
        html = '<a href="/page#section1">Link</a>'
        target = _make_target()
        result = run_link_discovery(target, html)

        links = result.observations["same_origin_links"]
        assert all("#" not in link for link in links)

    def test_deduplication(self):
        html = """
        <a href="/page">A</a>
        <a href="/page">B</a>
        <a href="/page#top">C</a>
        """
        target = _make_target()
        result = run_link_discovery(target, html)

        links = result.observations["same_origin_links"]
        assert len(links) == len(set(links))

    def test_empty_html(self):
        target = _make_target()
        result = run_link_discovery(target, "")

        assert result.status == ToolStatus.UNAVAILABLE

    def test_relative_urls_resolved(self):
        html = '<a href="subpage">Sub</a>'
        target = _make_target()
        result = run_link_discovery(target, html)

        links = result.observations["same_origin_links"]
        assert any("subpage" in link for link in links)


# ── 4.5 TLS Metadata Tests ───────────────────────────────────────────────────

class TestTlsMetadata:
    def test_http_target_returns_unavailable(self):
        target = _make_http_target()
        result = run_tls_metadata(target)

        assert result.status == ToolStatus.UNAVAILABLE
        assert any("https" in e.lower() for e in result.errors)

    @patch("recon.tls_metadata.socket.create_connection")
    @patch("recon.tls_metadata.ssl.create_default_context")
    def test_successful_tls_connection(self, mock_ctx_factory, mock_conn):
        mock_cert = {
            "subject": ((("commonName", "example.com"),),),
            "issuer": ((("commonName", "Let's Encrypt"),),),
            "notBefore": "Jan  1 00:00:00 2026 GMT",
            "notAfter": "Dec 31 23:59:59 2026 GMT",
        }
        mock_ssock = MagicMock()
        mock_ssock.getpeercert.return_value = mock_cert
        mock_ssock.version.return_value = "TLSv1.3"
        mock_ssock.__enter__ = MagicMock(return_value=mock_ssock)
        mock_ssock.__exit__ = MagicMock(return_value=False)

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_sock

        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value = mock_ssock
        mock_ctx_factory.return_value = mock_ctx

        target = _make_target()
        result = run_tls_metadata(target)

        assert result.status == ToolStatus.SUCCESS
        assert result.observations["tls_version"] == "TLSv1.3"

    @patch("recon.tls_metadata.socket.create_connection")
    @patch("recon.tls_metadata.ssl.create_default_context")
    def test_tls_verification_error(self, mock_ctx_factory, mock_conn):
        mock_conn.side_effect = ssl.SSLCertVerificationError("certificate verify failed")

        target = _make_target()
        result = run_tls_metadata(target)

        assert result.status == ToolStatus.ERROR
        assert any("verification" in e.lower() for e in result.errors)

    @patch("recon.tls_metadata.socket.create_connection")
    def test_connection_timeout(self, mock_conn):
        mock_conn.side_effect = socket.timeout("timed out")

        target = _make_target()
        result = run_tls_metadata(target)

        assert result.status == ToolStatus.ERROR
        assert any("timeout" in e.lower() or "timed out" in e.lower() for e in result.errors)


# ── 4.6 DNS Info Tests ───────────────────────────────────────────────────────

class TestDnsInfo:
    @patch("recon.dns_info.socket.getaddrinfo")
    def test_a_and_aaaa_records(self, mock_getaddrinfo):
        def side_effect(host, port, family, socktype):
            if family == socket.AF_INET:
                return [(2, 1, 6, "", ("93.184.216.34", 0))]
            elif family == socket.AF_INET6:
                return [(10, 1, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0))]
            return []

        mock_getaddrinfo.side_effect = side_effect

        target = _make_target()
        result = run_dns_info(target)

        assert result.status == ToolStatus.SUCCESS
        assert "93.184.216.34" in result.observations["a_records"]
        assert len(result.observations["aaaa_records"]) > 0

    @patch("recon.dns_info.socket.getaddrinfo")
    def test_dns_failure(self, mock_getaddrinfo):
        mock_getaddrinfo.side_effect = socket.gaierror("Name resolution failed")

        target = _make_target()
        result = run_dns_info(target)

        assert result.status == ToolStatus.ERROR
        assert len(result.errors) > 0

    @patch("recon.dns_info.socket.getaddrinfo")
    def test_partial_records(self, mock_getaddrinfo):
        def side_effect(host, port, family, socktype):
            if family == socket.AF_INET:
                return [(2, 1, 6, "", ("93.184.216.34", 0))]
            raise socket.gaierror("No AAAA")

        mock_getaddrinfo.side_effect = side_effect

        target = _make_target()
        result = run_dns_info(target)

        assert result.status == ToolStatus.PARTIAL
        assert len(result.observations["a_records"]) > 0
        assert len(result.errors) > 0

    @patch("recon.dns_info.socket.getaddrinfo")
    def test_mx_ns_txt_marked_unavailable(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]

        target = _make_target()
        result = run_dns_info(target)

        assert result.observations["mx_records"] is None
        assert result.observations["ns_records"] is None
        assert result.observations["txt_records"] is None
        assert "dnspython" in result.observations.get("mx_note", "").lower()


# ── 4.7 Tech Fingerprint Tests ───────────────────────────────────────────────

class TestTechFingerprint:
    def test_nginx_detected_from_headers(self):
        headers = {"Server": "nginx/1.21.0", "Content-Type": "text/html"}
        target = _make_target()
        result = run_tech_fingerprint(target, headers=headers)

        assert result.status == ToolStatus.SUCCESS
        findings = result.observations["findings"]
        assert any(f["technology"] == "Nginx" for f in findings)
        assert all(f["confidence"] in ("likely", "possible") for f in findings)

    def test_wordpress_detected_from_html(self):
        html = '<html><body><script src="/wp-content/themes/x/style.css"></script></body></html>'
        target = _make_target()
        result = run_tech_fingerprint(target, html_body=html)

        assert result.status == ToolStatus.SUCCESS
        findings = result.observations["findings"]
        assert any(f["technology"] == "WordPress" for f in findings)

    def test_no_signals_returns_empty(self):
        headers = {"Content-Type": "application/json"}
        target = _make_target()
        result = run_tech_fingerprint(target, headers=headers, html_body="<html></html>")

        assert result.status == ToolStatus.SUCCESS
        assert result.observations["findings_count"] == 0

    def test_no_input_returns_unavailable(self):
        target = _make_target()
        result = run_tech_fingerprint(target, headers=None, html_body=None)

        assert result.status == ToolStatus.UNAVAILABLE

    def test_evidence_traceability(self):
        headers = {"Server": "Apache/2.4.41"}
        target = _make_target()
        result = run_tech_fingerprint(target, headers=headers)

        findings = result.observations["findings"]
        assert len(findings) > 0
        f = findings[0]
        assert "signal_source" in f
        assert "signal_value" in f
        assert "rationale" in f
        assert f["signal_source"] == "header:server"

    def test_no_certainty_claims(self):
        headers = {"Server": "nginx"}
        html = '<div data-reactroot>content</div>'
        target = _make_target()
        result = run_tech_fingerprint(target, headers=headers, html_body=html)

        findings = result.observations["findings"]
        for f in findings:
            assert f["confidence"] in ("likely", "possible")

    def test_multiple_technologies(self):
        headers = {"Server": "nginx", "X-Powered-By": "PHP/8.1"}
        target = _make_target()
        result = run_tech_fingerprint(target, headers=headers)

        findings = result.observations["findings"]
        techs = {f["technology"] for f in findings}
        assert "Nginx" in techs
        assert "PHP" in techs
