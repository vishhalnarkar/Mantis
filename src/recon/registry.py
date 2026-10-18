"""Allowlisted reconnaissance tool registry (Stage 05).

Maps stable internal tool IDs to known, implemented callables.
Only code-defined entries may run. Unknown or disabled IDs are
rejected safely. No dynamic imports, no user/model-supplied names.

Each entry carries metadata used by the orchestrator:
- id: stable string identifier
- description: human-readable purpose
- enabled: whether the tool participates in assessments
- needs: prerequisite tool IDs whose results may be reused
- network: True if the tool performs network I/O
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from recon.http_metadata import run_http_metadata
from recon.security_headers import run_security_headers
from recon.robots_sitemap import run_robots_sitemap
from recon.link_discovery import run_link_discovery
from recon.tls_metadata import run_tls_metadata
from recon.dns_info import run_dns_info
from recon.tech_fingerprint import run_tech_fingerprint


@dataclass(frozen=True)
class ReconToolEntry:
    """Metadata + callable for one registered recon tool."""
    id: str
    description: str
    fn: Callable
    enabled: bool = True
    needs: tuple[str, ...] = ()
    network: bool = False


# The single source of truth for which tools exist.
RECON_TOOL_REGISTRY: dict[str, ReconToolEntry] = {
    "http_metadata": ReconToolEntry(
        id="http_metadata",
        description="HTTP metadata and redirect inspection",
        fn=run_http_metadata,
        network=True,
    ),
    "security_headers": ReconToolEntry(
        id="security_headers",
        description="Security response-header inspection",
        fn=run_security_headers,
        needs=("http_metadata",),
    ),
    "robots_sitemap": ReconToolEntry(
        id="robots_sitemap",
        description="robots.txt and sitemap retrieval",
        fn=run_robots_sitemap,
        network=True,
    ),
    "link_discovery": ReconToolEntry(
        id="link_discovery",
        description="Bounded same-origin link discovery",
        fn=run_link_discovery,
        needs=("http_metadata",),
    ),
    "tls_metadata": ReconToolEntry(
        id="tls_metadata",
        description="TLS certificate metadata",
        fn=run_tls_metadata,
        network=True,
    ),
    "dns_info": ReconToolEntry(
        id="dns_info",
        description="DNS record collection",
        fn=run_dns_info,
        network=True,
    ),
    "tech_fingerprint": ReconToolEntry(
        id="tech_fingerprint",
        description="Conservative technology fingerprinting",
        fn=run_tech_fingerprint,
        needs=("http_metadata",),
    ),
}


def get_tool(tool_id: str) -> ReconToolEntry | None:
    """Return a registered, enabled tool entry, or None."""
    entry = RECON_TOOL_REGISTRY.get(tool_id)
    if entry is None or not entry.enabled:
        return None
    return entry


def enabled_tool_ids() -> list[str]:
    """IDs of all enabled tools, in registry insertion order."""
    return [tid for tid, entry in RECON_TOOL_REGISTRY.items() if entry.enabled]