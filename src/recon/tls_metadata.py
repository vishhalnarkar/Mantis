"""Tool 4.5 — TLS certificate metadata.

For HTTPS targets, connects with standard ssl and records:
- Subject and issuer.
- Validity start/end dates.
- TLS version and handshake outcome.

Does NOT disable certificate validation. Returns unavailable/error
honestly when metadata cannot be safely collected.
"""

from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone

from logger import get_logger
from target import ValidatedTarget
from recon.contract import ToolResult, ToolStatus

log = get_logger("recon.tls_metadata")

TOOL_NAME = "tls_metadata"

CONNECT_TIMEOUT = 10.0


def run_tls_metadata(target: ValidatedTarget) -> ToolResult:
    """Collect TLS certificate metadata for an HTTPS target."""
    result = ToolResult(tool_name=TOOL_NAME, status=ToolStatus.ERROR,
                        source_url=target.parsed.normalized_url)

    if target.parsed.scheme != "https":
        result.status = ToolStatus.UNAVAILABLE
        result.errors.append("TLS metadata only available for HTTPS targets.")
        result.mark_completed()
        return result

    hostname = target.parsed.hostname
    port = target.parsed.port

    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=CONNECT_TIMEOUT) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as tls_sock:
                cert = tls_sock.getpeercert()
                tls_version = tls_sock.version()

        # Parse subject/issuer
        subject = dict(x[0] for x in cert.get("subject", ()))
        issuer = dict(x[0] for x in cert.get("issuer", ()))

        not_before = cert.get("notBefore", "")
        not_after = cert.get("notAfter", "")

        # Check expiry
        expired = False
        try:
            expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            expired = expiry < datetime.now(timezone.utc)
        except ValueError:
            pass

        result.observations = {
            "subject": subject,
            "issuer": issuer,
            "not_before": not_before,
            "not_after": not_after,
            "expired": expired,
            "tls_version": tls_version,
            "serial_number": cert.get("serialNumber", ""),
            "san": [entry[1] for entry in cert.get("subjectAltName", ())],
        }
        result.status = ToolStatus.SUCCESS

    except ssl.SSLCertVerificationError as e:
        result.status = ToolStatus.ERROR
        result.errors.append(f"Certificate verification failed: {e}")
        log.warning("TLS verification failed for %s: %s", hostname, e)
    except ssl.SSLError as e:
        result.status = ToolStatus.ERROR
        result.errors.append(f"TLS error: {e}")
        log.warning("TLS error for %s: %s", hostname, e)
    except socket.timeout:
        result.status = ToolStatus.ERROR
        result.errors.append("TLS connection timed out.")
        log.warning("TLS timeout for %s", hostname)
    except OSError as e:
        result.status = ToolStatus.ERROR
        result.errors.append(f"Connection error during TLS handshake: {e}")
        log.warning("TLS connection error for %s: %s", hostname, e)

    result.mark_completed()
    return result
