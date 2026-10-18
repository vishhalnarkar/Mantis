"""Tool 4.7 — Conservative technology fingerprinting.

Uses only observable signals from collected HTTP headers and HTML
metadata to suggest possible technologies. Each suggestion includes:
- The exact signal observed.
- A confidence label ("possible" / "likely").
- A short rationale.

No extra requests are made. No certainty claims without strong signals.
"""

from __future__ import annotations

import re

from logger import get_logger
from target import ValidatedTarget
from recon.contract import ToolResult, ToolStatus

log = get_logger("recon.tech_fingerprint")

TOOL_NAME = "tech_fingerprint"

# Signature patterns: (header_name, regex, technology, confidence, rationale)
HEADER_SIGNATURES = [
    ("server", r"nginx", "Nginx", "likely", "Server header contains 'nginx'."),
    ("server", r"apache", "Apache", "likely", "Server header contains 'apache'."),
    ("server", r"iis|microsoft", "Microsoft IIS", "likely", "Server header indicates IIS."),
    ("server", r"cloudflare", "Cloudflare", "likely", "Server header indicates Cloudflare."),
    ("x-powered-by", r"express", "Express.js", "possible", "X-Powered-By suggests Express."),
    ("x-powered-by", r"php[/: ]?([\d.]+)?", "PHP", "possible", "X-Powered-By suggests PHP."),
    ("x-powered-by", r"asp\.net", "ASP.NET", "possible", "X-Powered-By suggests ASP.NET."),
    ("x-aspnet-version", r".+", "ASP.NET", "likely", "X-AspNet-Version header present."),
    ("x-generator", r"wordpress", "WordPress", "possible", "X-Generator mentions WordPress."),
    ("cf-ray", r".+", "Cloudflare", "likely", "CF-Ray header present."),
    ("via", r"varnish", "Varnish", "possible", "Via header suggests Varnish cache."),
]

# HTML-based signals: (regex, technology, confidence)
HTML_SIGNATURES = [
    (r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', "generator_meta", "possible"),
    (r'wp-content/', "WordPress", "possible"),
    (r'wp-includes/', "WordPress", "possible"),
    (r'__next', "Next.js", "possible"),
    (r'ng-version=', "Angular", "possible"),
    (r'data-reactroot', "React", "possible"),
    (r'cdn\.shopify\.com', "Shopify", "possible"),
    (r'laravel', "Laravel", "possible"),
]


def run_tech_fingerprint(
    target: ValidatedTarget,
    headers: dict[str, str] | None = None,
    html_body: str | None = None,
) -> ToolResult:
    """Fingerprint technologies from already-collected headers and HTML.

    Args:
        target: Validated target for provenance.
        headers: Response headers dict (from http_metadata).
        html_body: HTML content (from http_metadata response body).
    """
    result = ToolResult(tool_name=TOOL_NAME, status=ToolStatus.ERROR,
                        source_url=target.parsed.normalized_url)

    if headers is None and html_body is None:
        result.status = ToolStatus.UNAVAILABLE
        result.errors.append("No headers or HTML supplied. Run http_metadata first.")
        result.mark_completed()
        return result

    findings: list[dict] = []
    headers_lower = {k.lower(): v for k, v in (headers or {}).items()}

    # Header-based signals
    for header_name, pattern, tech, confidence, rationale in HEADER_SIGNATURES:
        value = headers_lower.get(header_name, "")
        if value and re.search(pattern, value, re.IGNORECASE):
            findings.append({
                "technology": tech,
                "confidence": confidence,
                "signal_source": f"header:{header_name}",
                "signal_value": value[:200],
                "rationale": rationale,
            })

    # HTML-based signals
    if html_body:
        for pattern, tech, confidence in HTML_SIGNATURES:
            match = re.search(pattern, html_body, re.IGNORECASE)
            if match:
                findings.append({
                    "technology": tech,
                    "confidence": confidence,
                    "signal_source": "html_content",
                    "signal_value": match.group(0)[:200],
                    "rationale": f"HTML pattern matched: {pattern}",
                })

    result.observations = {
        "findings": findings,
        "findings_count": len(findings),
        "note": "All findings are observational signals, not confirmed facts.",
    }
    result.status = ToolStatus.SUCCESS
    result.mark_completed()
    return result
