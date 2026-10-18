"""Tool 4.3 — robots.txt and sitemap retrieval.

Bounded retrieval of /robots.txt and sitemap references.
Listed paths are discovery hints only — never accessed automatically.
"""

from __future__ import annotations

import requests

from config import config
from logger import get_logger
from target import ValidatedTarget, validate_redirect
from recon.contract import ToolResult, ToolStatus

log = get_logger("recon.robots_sitemap")

TOOL_NAME = "robots_sitemap"

MAX_BODY = config.recon.max_response_size
TIMEOUT = config.recon.request_timeout
MAX_SITEMAP_URLS = 5


def _bounded_get(url: str, target: ValidatedTarget) -> requests.Response | None:
    """GET with scope-aware redirect validation and size cap."""
    session = requests.Session()
    current = url
    for i in range(config.recon.max_redirects + 1):
        try:
            resp = session.get(
                current, timeout=TIMEOUT, allow_redirects=False, stream=True,
                headers={"User-Agent": "Mantis-Recon/1.0 (bounded, read-only)"},
            )
        except requests.exceptions.RequestException:
            return None

        if resp.status_code < 300 or resp.status_code >= 400:
            return resp

        location = resp.headers.get("Location", "")
        if not location:
            resp.close()
            return None

        if not location.startswith(("http://", "https://")):
            base = f"{target.parsed.scheme}://{target.parsed.hostname}:{target.parsed.port}"
            location = base + ("" if location.startswith("/") else "/") + location

        ok, _ = validate_redirect(location, target, redirect_count=i + 1)
        resp.close()
        if not ok:
            return None
        current = location
    return None


def _read_body(resp: requests.Response) -> tuple[str, bool]:
    """Read up to MAX_BODY bytes. Returns (text, truncated)."""
    chunks = []
    size = 0
    truncated = False
    for chunk in resp.iter_content(chunk_size=8192):
        size += len(chunk)
        chunks.append(chunk)
        if size > MAX_BODY:
            truncated = True
            break
    resp.close()
    return b"".join(chunks).decode("utf-8", errors="replace"), truncated


def run_robots_sitemap(target: ValidatedTarget) -> ToolResult:
    """Fetch /robots.txt and extract sitemap references."""
    base = f"{target.parsed.scheme}://{target.parsed.hostname}:{target.parsed.port}"
    robots_url = f"{base}/robots.txt"

    result = ToolResult(tool_name=TOOL_NAME, status=ToolStatus.ERROR, source_url=robots_url)

    # ── robots.txt ──
    resp = _bounded_get(robots_url, target)
    if resp is None:
        result.status = ToolStatus.UNAVAILABLE
        result.errors.append("Could not retrieve /robots.txt (connection or scope error).")
        result.mark_completed()
        return result

    robots_status = resp.status_code
    robots_body, robots_truncated = _read_body(resp) if robots_status == 200 else ("", False)
    if resp.status_code == 200:
        pass  # body already read by _read_body
    else:
        resp.close()

    observations: dict = {
        "robots_url": robots_url,
        "robots_status": robots_status,
        "robots_truncated": robots_truncated,
        "disallow_paths": [],
        "allow_paths": [],
        "sitemap_urls": [],
    }

    if robots_truncated:
        result.limits_applied.append(f"robots_body_capped_at_{MAX_BODY}")

    if robots_status == 200 and robots_body:
        for line in robots_body.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            if lower.startswith("disallow:"):
                observations["disallow_paths"].append(stripped.split(":", 1)[1].strip())
            elif lower.startswith("allow:"):
                observations["allow_paths"].append(stripped.split(":", 1)[1].strip())
            elif lower.startswith("sitemap:"):
                if len(observations["sitemap_urls"]) < MAX_SITEMAP_URLS:
                    observations["sitemap_urls"].append(stripped.split(":", 1)[1].strip())

    # ── Sitemap fallback ──
    sitemap_url = None
    if observations["sitemap_urls"]:
        sitemap_url = observations["sitemap_urls"][0]
    else:
        sitemap_url = f"{base}/sitemap.xml"

    sitemap_status = None
    if sitemap_url:
        s_resp = _bounded_get(sitemap_url, target)
        if s_resp is not None:
            sitemap_status = s_resp.status_code
            s_resp.close()

    observations["sitemap_url_checked"] = sitemap_url
    observations["sitemap_status"] = sitemap_status

    result.observations = observations
    result.status = ToolStatus.SUCCESS if robots_status in (200, 404) else ToolStatus.PARTIAL
    result.mark_completed()
    return result
