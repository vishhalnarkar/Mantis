"""Tests for src/target.py — Target Validation & Scope Control.

All DNS-dependent tests use mocks. No live network access required.
"""

import socket
from unittest.mock import patch, MagicMock

import pytest

from target import (
    parse_url,
    validate_target,
    validate_redirect,
    classify_ip,
    resolve_hostname,
    ParsedTarget,
    TargetValidationError,
    TargetErrorCode,
    ValidatedTarget,
    ResolutionResult,
    IPClassification,
)


# ── 5.1 URL Parsing Tests ─────────────────────────────────────────────────

class TestParseUrl:
    """Pure URL parsing and normalization (no network access)."""

    def test_valid_http_url(self):
        result = parse_url("http://example.com")
        assert isinstance(result, ParsedTarget)
        assert result.scheme == "http"
        assert result.hostname == "example.com"
        assert result.port == 80

    def test_valid_https_url(self):
        result = parse_url("https://example.com")
        assert isinstance(result, ParsedTarget)
        assert result.scheme == "https"
        assert result.hostname == "example.com"
        assert result.port == 443

    def test_uppercase_hostname_normalized(self):
        result = parse_url("https://EXAMPLE.COM/path")
        assert isinstance(result, ParsedTarget)
        assert result.hostname == "example.com"

    def test_explicit_port(self):
        result = parse_url("https://example.com:8443/page")
        assert isinstance(result, ParsedTarget)
        assert result.port == 8443

    def test_missing_scheme(self):
        result = parse_url("example.com/page")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.MISSING_SCHEME

    def test_unsupported_scheme_ftp(self):
        result = parse_url("ftp://example.com/file")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.UNSUPPORTED_SCHEME

    def test_unsupported_scheme_file(self):
        result = parse_url("file:///etc/passwd")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.UNSUPPORTED_SCHEME

    def test_unsupported_scheme_javascript(self):
        result = parse_url("javascript:alert(1)")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.UNSUPPORTED_SCHEME

    def test_missing_hostname(self):
        result = parse_url("http://")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.MISSING_HOST

    def test_empty_url(self):
        result = parse_url("")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.MALFORMED_URL

    def test_whitespace_only_url(self):
        result = parse_url("   ")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.MALFORMED_URL

    def test_embedded_credentials_rejected(self):
        result = parse_url("http://user:pass@example.com/")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.EMBEDDED_CREDENTIALS

    def test_embedded_username_only_rejected(self):
        result = parse_url("http://admin@example.com/")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.EMBEDDED_CREDENTIALS

    def test_fragment_removed(self):
        result = parse_url("https://example.com/page#section")
        assert isinstance(result, ParsedTarget)
        assert "#" not in result.normalized_url
        assert result.path == "/page"

    def test_query_string_preserved(self):
        result = parse_url("https://example.com/search?q=test&page=1")
        assert isinstance(result, ParsedTarget)
        assert result.query == "q=test&page=1"
        assert "q=test" in result.normalized_url

    def test_invalid_port_zero(self):
        result = parse_url("http://example.com:0/")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.INVALID_PORT

    def test_invalid_port_too_high(self):
        result = parse_url("http://example.com:99999/")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.INVALID_PORT

    def test_ipv4_literal(self):
        result = parse_url("http://93.184.216.34/")
        assert isinstance(result, ParsedTarget)
        assert result.hostname == "93.184.216.34"

    def test_ipv6_literal(self):
        result = parse_url("http://[2001:db8::1]/")
        assert isinstance(result, ParsedTarget)
        assert result.hostname == "2001:db8::1"

    def test_trailing_slash_path(self):
        result = parse_url("https://example.com/")
        assert isinstance(result, ParsedTarget)
        assert result.path == "/"

    def test_no_path_defaults_to_slash(self):
        result = parse_url("https://example.com")
        assert isinstance(result, ParsedTarget)
        assert result.path == "/"

    def test_default_port_not_in_normalized_url(self):
        result = parse_url("https://example.com/page")
        assert isinstance(result, ParsedTarget)
        assert ":443" not in result.normalized_url

    def test_non_default_port_in_normalized_url(self):
        result = parse_url("https://example.com:8443/page")
        assert isinstance(result, ParsedTarget)
        assert ":8443" in result.normalized_url


# ── 5.2 IP Classification Tests ───────────────────────────────────────────

class TestClassifyIp:
    """IP address classification."""

    def test_public_ipv4(self):
        c = classify_ip("93.184.216.34")
        assert c.is_public is True

    def test_loopback_ipv4(self):
        c = classify_ip("127.0.0.1")
        assert c.is_public is False
        assert c.reason == "loopback"

    def test_private_ipv4_10(self):
        c = classify_ip("10.0.0.1")
        assert c.is_public is False
        assert c.reason == "private"

    def test_private_ipv4_172(self):
        c = classify_ip("172.16.0.1")
        assert c.is_public is False
        assert c.reason == "private"

    def test_private_ipv4_192(self):
        c = classify_ip("192.168.1.1")
        assert c.is_public is False
        assert c.reason == "private"

    def test_link_local_ipv4(self):
        c = classify_ip("169.254.1.1")
        assert c.is_public is False
        assert c.reason == "link_local"

    def test_multicast_ipv4(self):
        c = classify_ip("224.0.0.1")
        assert c.is_public is False
        assert c.reason == "multicast"

    def test_unspecified_ipv4(self):
        c = classify_ip("0.0.0.0")
        assert c.is_public is False
        assert c.reason == "unspecified"

    def test_public_ipv6(self):
        c = classify_ip("2001:db8::1")
        # 2001:db8:: is documentation range, not global
        assert c.is_public is False

    def test_loopback_ipv6(self):
        c = classify_ip("::1")
        assert c.is_public is False
        assert c.reason == "loopback"

    def test_link_local_ipv6(self):
        c = classify_ip("fe80::1")
        assert c.is_public is False
        assert c.reason == "link_local"

    def test_unparseable_ip(self):
        c = classify_ip("not-an-ip")
        assert c.is_public is False
        assert c.reason == "unparseable"


# ── 5.2 DNS Resolution Tests (mocked) ─────────────────────────────────────

class TestResolveHostname:
    """DNS resolution with mocked socket.getaddrinfo."""

    def test_public_ip_literal_no_dns(self):
        result = resolve_hostname("93.184.216.34")
        assert result.blocked is False
        assert result.addresses == ("93.184.216.34",)

    def test_private_ip_literal_blocked(self):
        result = resolve_hostname("192.168.1.1")
        assert result.blocked is True
        assert "private" in result.reason

    def test_loopback_ip_literal_blocked(self):
        result = resolve_hostname("127.0.0.1")
        assert result.blocked is True
        assert "loopback" in result.reason

    @patch("target.socket.getaddrinfo")
    def test_public_hostname_resolves(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ]
        result = resolve_hostname("example.com")
        assert result.blocked is False
        assert "93.184.216.34" in result.addresses

    @patch("target.socket.getaddrinfo")
    def test_private_hostname_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("192.168.1.100", 0)),
        ]
        result = resolve_hostname("internal.local")
        assert result.blocked is True
        assert "private" in result.reason

    @patch("target.socket.getaddrinfo")
    def test_mixed_public_private_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
            (2, 1, 6, "", ("10.0.0.1", 0)),
        ]
        result = resolve_hostname("mixed.example.com")
        assert result.blocked is True
        assert "blocked_ips" in result.reason

    @patch("target.socket.getaddrinfo")
    def test_empty_dns_answer_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = []
        result = resolve_hostname("empty.example.com")
        assert result.blocked is True
        assert "empty_dns_answer" in result.reason

    @patch("target.socket.getaddrinfo")
    def test_dns_resolution_failure(self, mock_getaddrinfo):
        mock_getaddrinfo.side_effect = socket.gaierror("Name or service not known")
        result = resolve_hostname("nonexistent.invalid")
        assert result.blocked is True
        assert "dns_resolution_failed" in result.reason

    @patch("target.socket.getaddrinfo")
    def test_dns_timeout(self, mock_getaddrinfo):
        mock_getaddrinfo.side_effect = OSError("Connection timed out")
        result = resolve_hostname("timeout.example.com")
        assert result.blocked is True
        assert "dns_resolution_error" in result.reason

    @patch("target.socket.getaddrinfo")
    def test_loopback_hostname_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("127.0.0.1", 0)),
        ]
        result = resolve_hostname("localhost")
        assert result.blocked is True

    @patch("target.socket.getaddrinfo")
    def test_link_local_hostname_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("169.254.1.1", 0)),
        ]
        result = resolve_hostname("linklocal.example.com")
        assert result.blocked is True
        assert "link_local" in result.reason


# ── 5.3 Redirect and Scope Tests ──────────────────────────────────────────

class TestValidateRedirect:
    """Redirect validation against target scope."""

    def _make_target(self, scheme="https", hostname="example.com", port=443):
        parsed = ParsedTarget(
            original_url=f"{scheme}://{hostname}/",
            normalized_url=f"{scheme}://{hostname}/",
            scheme=scheme,
            hostname=hostname,
            port=port,
            path="/",
            query="",
        )
        resolution = ResolutionResult(
            hostname=hostname,
            addresses=("93.184.216.34",),
            blocked=False,
        )
        return ValidatedTarget(
            parsed=parsed,
            resolution=resolution,
            allowed_origin=(scheme, hostname, port),
        )

    @patch("target.resolve_hostname")
    def test_same_origin_redirect_allowed(self, mock_resolve):
        mock_resolve.return_value = ResolutionResult(
            hostname="example.com", addresses=("93.184.216.34",), blocked=False
        )
        target = self._make_target()
        valid, reason = validate_redirect("https://example.com/other", target)
        assert valid is True

    @patch("target.resolve_hostname")
    def test_different_hostname_blocked(self, mock_resolve):
        mock_resolve.return_value = ResolutionResult(
            hostname="evil.com", addresses=("1.2.3.4",), blocked=False
        )
        target = self._make_target()
        valid, reason = validate_redirect("https://evil.com/page", target)
        assert valid is False
        assert "different origin" in reason

    @patch("target.resolve_hostname")
    def test_different_port_blocked(self, mock_resolve):
        mock_resolve.return_value = ResolutionResult(
            hostname="example.com", addresses=("93.184.216.34",), blocked=False
        )
        target = self._make_target()
        valid, reason = validate_redirect("https://example.com:8443/page", target)
        assert valid is False
        assert "different origin" in reason

    @patch("target.resolve_hostname")
    def test_http_to_https_redirect_blocked(self, mock_resolve):
        mock_resolve.return_value = ResolutionResult(
            hostname="example.com", addresses=("93.184.216.34",), blocked=False
        )
        target = self._make_target(scheme="http", port=80)
        valid, reason = validate_redirect("https://example.com/page", target)
        assert valid is False
        assert "different origin" in reason

    @patch("target.resolve_hostname")
    def test_redirect_to_private_ip_blocked(self, mock_resolve):
        mock_resolve.return_value = ResolutionResult(
            hostname="internal.local", addresses=("192.168.1.1",), blocked=True,
            reason="private"
        )
        target = self._make_target()
        # Same origin check will fail first since hostname differs
        valid, reason = validate_redirect("https://internal.local/page", target)
        assert valid is False

    def test_redirect_limit_exceeded(self):
        target = self._make_target()
        valid, reason = validate_redirect(
            "https://example.com/page", target, redirect_count=10, max_redirects=10
        )
        assert valid is False
        assert "limit" in reason.lower()

    def test_malformed_redirect_url(self):
        target = self._make_target()
        valid, reason = validate_redirect("not-a-url", target)
        assert valid is False
        assert "invalid" in reason.lower()

    @patch("target.resolve_hostname")
    def test_redirect_to_loopback_blocked(self, mock_resolve):
        mock_resolve.return_value = ResolutionResult(
            hostname="localhost", addresses=("127.0.0.1",), blocked=True,
            reason="loopback"
        )
        target = self._make_target(hostname="localhost", port=443)
        valid, reason = validate_redirect("https://localhost/admin", target)
        assert valid is False
        assert "blocked" in reason.lower()


# ── Full validate_target tests ────────────────────────────────────────────

class TestValidateTarget:
    """End-to-end target validation."""

    @patch("target.socket.getaddrinfo")
    def test_valid_public_target(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ]
        result = validate_target("https://example.com")
        assert isinstance(result, ValidatedTarget)
        assert result.parsed.hostname == "example.com"
        assert result.allowed_origin == ("https", "example.com", 443)

    @patch("target.socket.getaddrinfo")
    def test_private_target_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("192.168.1.1", 0)),
        ]
        result = validate_target("http://internal.local")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.BLOCKED_IP

    def test_invalid_url_returns_error(self):
        result = validate_target("ftp://example.com")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.UNSUPPORTED_SCHEME

    @patch("target.socket.getaddrinfo")
    def test_block_private_can_be_disabled(self, mock_getaddrinfo):
        """Local-lab mode: block_private=False allows private IPs."""
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("192.168.1.1", 0)),
        ]
        result = validate_target("http://192.168.1.1", block_private=False)
        assert isinstance(result, ValidatedTarget)

    @patch("target.socket.getaddrinfo")
    def test_dns_failure_returns_error(self, mock_getaddrinfo):
        mock_getaddrinfo.side_effect = socket.gaierror("NXDOMAIN")
        result = validate_target("https://nonexistent.invalid")
        assert isinstance(result, TargetValidationError)
        assert result.code == TargetErrorCode.BLOCKED_IP
