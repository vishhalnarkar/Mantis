"""Target validation and scope control for Mantis.

This module is the safety gate that ALL future reconnaissance tools must
pass through before making any network request. It provides:

1. URL parsing and normalization (pure, no network access).
2. Hostname resolution and IP classification (network-dependent, mockable).
3. Redirect/scope validation policy.

Design principles:
- Parsing is separated from resolution so behavior is testable.
- Only HTTP and HTTPS are permitted.
- Private, loopback, link-local, reserved, multicast, and unspecified
  destinations are blocked by default.
- Redirects are re-validated against the same scope policy.
- Structured errors; never crash on malformed input.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse, urlunparse

from logger import get_logger

log = get_logger("target")

# ── Constants ─────────────────────────────────────────────────────────────

ALLOWED_SCHEMES = frozenset({"http", "https"})
DEFAULT_PORTS = {"http": 80, "https": 443}
MAX_REDIRECTS_DEFAULT = 10


# ── Error codes ───────────────────────────────────────────────────────────

class TargetErrorCode(str, Enum):
    MALFORMED_URL = "malformed_url"
    MISSING_SCHEME = "missing_scheme"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    MISSING_HOST = "missing_host"
    INVALID_PORT = "invalid_port"
    EMBEDDED_CREDENTIALS = "embedded_credentials"
    DNS_RESOLUTION_FAILED = "dns_resolution_failed"
    BLOCKED_IP = "blocked_ip"
    MIXED_DNS_ANSWERS = "mixed_dns_answers"
    EMPTY_DNS_ANSWER = "empty_dns_answer"
    SCOPE_VIOLATION = "scope_violation"
    REDIRECT_LIMIT_EXCEEDED = "redirect_limit_exceeded"


@dataclass(frozen=True)
class TargetValidationError:
    """Structured validation failure."""
    code: TargetErrorCode
    message: str
    detail: str = ""


# ── Parsed target (no network access) ─────────────────────────────────────

@dataclass(frozen=True)
class ParsedTarget:
    """Result of pure URL parsing and normalization."""
    original_url: str
    normalized_url: str
    scheme: str
    hostname: str          # lowercase
    port: int              # effective port (default applied)
    path: str
    query: str             # preserved but not logged in detail
    # Scope identity: (scheme, hostname, port)
    @property
    def origin(self) -> tuple:
        return (self.scheme, self.hostname, self.port)


# ── IP classification ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class IPClassification:
    """Classification of a single IP address."""
    ip: str
    is_public: bool
    reason: str = ""


def classify_ip(ip_str: str) -> IPClassification:
    """Classify an IP address. Returns classification with reason."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return IPClassification(ip=ip_str, is_public=False, reason="unparseable")

    # Order matters: check specific categories before is_private,
    # because is_private is True for loopback, link-local, and unspecified too.
    if addr.is_unspecified:
        return IPClassification(ip=ip_str, is_public=False, reason="unspecified")
    if addr.is_loopback:
        return IPClassification(ip=ip_str, is_public=False, reason="loopback")
    if addr.is_link_local:
        return IPClassification(ip=ip_str, is_public=False, reason="link_local")
    if addr.is_multicast:
        return IPClassification(ip=ip_str, is_public=False, reason="multicast")
    if addr.is_reserved:
        return IPClassification(ip=ip_str, is_public=False, reason="reserved")
    if addr.is_private:
        return IPClassification(ip=ip_str, is_public=False, reason="private")

    # IPv4-mapped IPv6 or other non-global
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:
            return classify_ip(str(addr.ipv4_mapped))
        if not addr.is_global:
            return IPClassification(ip=ip_str, is_public=False, reason="non_global_ipv6")

    if isinstance(addr, ipaddress.IPv4Address) and not addr.is_global:
        return IPClassification(ip=ip_str, is_public=False, reason="non_global_ipv4")

    return IPClassification(ip=ip_str, is_public=True, reason="public")


# ── DNS resolution ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ResolutionResult:
    """Result of resolving a hostname to IPs."""
    hostname: str
    addresses: tuple[str, ...]
    blocked: bool
    reason: str = ""
    classifications: tuple[IPClassification, ...] = ()


def resolve_hostname(hostname: str) -> ResolutionResult:
    """Resolve a hostname and classify all resulting IPs.

    Uses socket.getaddrinfo. This function is isolated so it can be
    mocked in tests. It does NOT make HTTP requests.
    """
    # If the hostname is already an IP literal, classify directly
    try:
        ipaddress.ip_address(hostname)
        classification = classify_ip(hostname)
        return ResolutionResult(
            hostname=hostname,
            addresses=(hostname,),
            blocked=not classification.is_public,
            reason=classification.reason if not classification.is_public else "",
            classifications=(classification,),
        )
    except ValueError:
        pass  # Not an IP literal; proceed with DNS resolution

    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        log.warning("DNS resolution failed for %s: %s", hostname, e)
        return ResolutionResult(
            hostname=hostname,
            addresses=(),
            blocked=True,
            reason=f"dns_resolution_failed: {e}",
        )
    except OSError as e:
        log.warning("DNS resolution error for %s: %s", hostname, e)
        return ResolutionResult(
            hostname=hostname,
            addresses=(),
            blocked=True,
            reason=f"dns_resolution_error: {e}",
        )

    if not results:
        return ResolutionResult(
            hostname=hostname,
            addresses=(),
            blocked=True,
            reason="empty_dns_answer",
        )

    # Extract unique IPs
    ips = list(dict.fromkeys(addr[4][0] for addr in results))
    classifications = tuple(classify_ip(ip) for ip in ips)

    # Block if ANY resolved address is non-public
    non_public = [c for c in classifications if not c.is_public]
    if non_public:
        reasons = ", ".join(f"{c.ip}({c.reason})" for c in non_public)
        return ResolutionResult(
            hostname=hostname,
            addresses=tuple(ips),
            blocked=True,
            reason=f"blocked_ips: {reasons}",
            classifications=classifications,
        )

    return ResolutionResult(
        hostname=hostname,
        addresses=tuple(ips),
        blocked=False,
        classifications=classifications,
    )


# ── Validated target ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class ValidatedTarget:
    """A fully validated target that recon tools may operate on."""
    parsed: ParsedTarget
    resolution: ResolutionResult
    # Scope: only this origin is permitted
    allowed_origin: tuple  # (scheme, hostname, port)


# ── URL parsing (pure, no network) ────────────────────────────────────────

def parse_url(raw_url: str) -> ParsedTarget | TargetValidationError:
    """Parse and normalize a URL without any network access.

    Returns ParsedTarget on success, TargetValidationError on failure.
    """
    if not raw_url or not raw_url.strip():
        return TargetValidationError(
            code=TargetErrorCode.MALFORMED_URL,
            message="URL is empty.",
        )

    raw_url = raw_url.strip()

    try:
        parsed = urlparse(raw_url)
    except Exception as e:
        return TargetValidationError(
            code=TargetErrorCode.MALFORMED_URL,
            message="URL could not be parsed.",
            detail=str(e),
        )

    # Scheme check
    scheme = parsed.scheme.lower()
    if not scheme:
        return TargetValidationError(
            code=TargetErrorCode.MISSING_SCHEME,
            message="URL has no scheme. Use http:// or https://.",
        )
    if scheme not in ALLOWED_SCHEMES:
        return TargetValidationError(
            code=TargetErrorCode.UNSUPPORTED_SCHEME,
            message=f"Scheme '{scheme}' is not allowed. Only http and https are supported.",
        )

    # Hostname check
    hostname = parsed.hostname
    if not hostname:
        return TargetValidationError(
            code=TargetErrorCode.MISSING_HOST,
            message="URL has no hostname.",
        )

    # Normalize hostname to lowercase
    hostname = hostname.lower()

    # Embedded credentials check
    if parsed.username or parsed.password:
        return TargetValidationError(
            code=TargetErrorCode.EMBEDDED_CREDENTIALS,
            message="URLs with embedded credentials are not allowed.",
        )

    # Port validation (urlparse raises ValueError for out-of-range ports)
    try:
        port = parsed.port  # None if not specified
    except ValueError:
        return TargetValidationError(
            code=TargetErrorCode.INVALID_PORT,
            message="Port is out of valid range (1-65535).",
        )
    if port is not None:
        if port < 1 or port > 65535:
            return TargetValidationError(
                code=TargetErrorCode.INVALID_PORT,
                message=f"Port {port} is out of valid range (1-65535).",
            )
    else:
        port = DEFAULT_PORTS[scheme]

    # Path normalization: ensure at least "/"
    path = parsed.path or "/"

    # Fragment removal (not sent in HTTP requests)
    # Query string preserved
    query = parsed.query

    # Build normalized URL (no fragment)
    netloc = hostname if port == DEFAULT_PORTS[scheme] else f"{hostname}:{port}"
    normalized = urlunparse((scheme, netloc, path, "", query, ""))

    return ParsedTarget(
        original_url=raw_url,
        normalized_url=normalized,
        scheme=scheme,
        hostname=hostname,
        port=port,
        path=path,
        query=query,
    )


# ── Full target validation (parse + resolve + classify) ───────────────────

def validate_target(raw_url: str, block_private: bool = True) -> ValidatedTarget | TargetValidationError:
    """Fully validate a target URL: parse, resolve, classify IPs.

    This is the single entry point that recon tools should use.
    Returns ValidatedTarget on success, TargetValidationError on failure.
    """
    # Step 1: Pure parsing
    parsed = parse_url(raw_url)
    if isinstance(parsed, TargetValidationError):
        return parsed

    # Step 2: DNS resolution and IP classification
    resolution = resolve_hostname(parsed.hostname)

    if resolution.blocked and block_private:
        log.warning(
            "Target blocked: %s -> %s", parsed.hostname, resolution.reason
        )
        return TargetValidationError(
            code=TargetErrorCode.BLOCKED_IP,
            message=f"Target '{parsed.hostname}' resolves to a blocked address.",
            detail=resolution.reason,
        )

    return ValidatedTarget(
        parsed=parsed,
        resolution=resolution,
        allowed_origin=parsed.origin,
    )


# ── Redirect validation ───────────────────────────────────────────────────

def validate_redirect(
    redirect_url: str,
    target: ValidatedTarget,
    redirect_count: int = 0,
    max_redirects: int = MAX_REDIRECTS_DEFAULT,
) -> tuple[bool, str]:
    """Validate a redirect destination against the target's scope.

    Returns (is_valid, reason). If invalid, reason explains why.
    """
    if redirect_count >= max_redirects:
        return False, f"Redirect limit ({max_redirects}) exceeded."

    # Parse the redirect URL
    parsed_redirect = parse_url(redirect_url)
    if isinstance(parsed_redirect, TargetValidationError):
        return False, f"Redirect URL is invalid: {parsed_redirect.message}"

    # Handle relative redirects: resolve against the target's origin
    # urlparse already handles this if the redirect_url is absolute.
    # For relative URLs, we need to check scheme presence.
    if not parsed_redirect.scheme:
        return False, "Redirect URL has no scheme."

    # Scope check: must be same origin
    if parsed_redirect.origin != target.allowed_origin:
        return False, (
            f"Redirect to different origin: "
            f"{parsed_redirect.scheme}://{parsed_redirect.hostname}:{parsed_redirect.port} "
            f"(allowed: {target.allowed_origin[0]}://{target.allowed_origin[1]}:{target.allowed_origin[2]})"
        )

    # IP re-validation for the redirect target
    redirect_resolution = resolve_hostname(parsed_redirect.hostname)
    if redirect_resolution.blocked:
        return False, f"Redirect target resolves to blocked address: {redirect_resolution.reason}"

    return True, "OK"
