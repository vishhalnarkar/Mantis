"""Tool 4.4 — Bounded same-origin link/page discovery.

Parses HTML from a single supplied response body and extracts links.
Filtering:
- Only same-origin URLs kept.
- Fragments removed, URLs deduplicated.
- Non-HTTP(S) schemes ignored.
- Page count capped by config.max_pages.

Full multi-page crawling belongs to Stage 05 orchestration.
"""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from config import config
from logger import get_logger
from target import ValidatedTarget
from recon.contract import ToolResult, ToolStatus

log = get_logger("recon.link_discovery")

TOOL_NAME = "link_discovery"

IGNORED_SCHEMES = frozenset({"javascript", "mailto", "data", "tel", "ftp"})


class _LinkExtractor(HTMLParser):
    """Extract href/src attributes from <a>, <link>, <script>, <img>."""

    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attr_dict = dict(attrs)
        if tag in ("a", "link"):
            href = attr_dict.get("href")
            if href:
                self.links.append(href)
        elif tag in ("script", "img"):
            src = attr_dict.get("src")
            if src:
                self.links.append(src)


def run_link_discovery(target: ValidatedTarget, html_body: str) -> ToolResult:
    """Parse HTML and return same-origin, deduplicated, normalized links.

    Args:
        target: The validated target for scope checking.
        html_body: The HTML content to parse.
    """
    base_url = target.parsed.normalized_url
    result = ToolResult(tool_name=TOOL_NAME, status=ToolStatus.ERROR, source_url=base_url)

    if not html_body or not html_body.strip():
        result.status = ToolStatus.UNAVAILABLE
        result.errors.append("No HTML body supplied.")
        result.mark_completed()
        return result

    try:
        parser = _LinkExtractor()
        parser.feed(html_body)
    except Exception as e:
        result.status = ToolStatus.ERROR
        result.errors.append(f"HTML parse error: {e}")
        result.mark_completed()
        return result

    raw_links = parser.links
    allowed_origin = target.allowed_origin  # (scheme, hostname, port)
    max_pages = config.recon.max_pages

    seen: set[str] = set()
    same_origin: list[str] = []
    skipped_non_http = 0
    skipped_other_origin = 0
    truncated = False

    for raw in raw_links:
        raw = raw.strip()
        if not raw:
            continue

        # Resolve relative URLs
        absolute = urljoin(base_url, raw)
        # Remove fragment
        absolute = absolute.split("#")[0]
        if not absolute:
            continue

        parsed = urlparse(absolute)
        scheme = parsed.scheme.lower()

        if scheme in IGNORED_SCHEMES or scheme not in ("http", "https"):
            skipped_non_http += 1
            continue

        hostname = (parsed.hostname or "").lower()
        try:
            port = parsed.port or (443 if scheme == "https" else 80)
        except ValueError:
            continue

        if (scheme, hostname, port) != allowed_origin:
            skipped_other_origin += 1
            continue

        if absolute in seen:
            continue
        seen.add(absolute)
        same_origin.append(absolute)

        if len(same_origin) >= max_pages:
            truncated = True
            result.limits_applied.append(f"max_pages_{max_pages}_reached")
            break

    result.observations = {
        "total_raw_links": len(raw_links),
        "same_origin_links": same_origin,
        "same_origin_count": len(same_origin),
        "skipped_non_http": skipped_non_http,
        "skipped_other_origin": skipped_other_origin,
        "deduplicated": True,
        "truncated": truncated,
    }
    result.status = ToolStatus.SUCCESS
    result.mark_completed()
    return result
