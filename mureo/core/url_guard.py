"""Shared SSRF guard for outbound fetches of caller-supplied URLs.

mureo fetches a few URLs that originate from LLM/MCP tool arguments or from
untrusted content the agent already processed (landing-page text, ad data):
the LP analyzer (``analysis.lp_analyzer``) and the Meta ad-image uploader
(``meta_ads._creatives``). Both must refuse to fetch internal/loopback/
link-local/cloud-metadata targets so a prompt-injection payload cannot turn a
fetch into an internal read (e.g. ``http://169.254.169.254/...`` for cloud IAM
credentials).

This module is the single source of truth for that check. It validates the
scheme, a denylist of obvious internal hostnames, and — for both literal IPs
and DNS names — the resolved address ranges.

Note: a DNS-rebinding TOCTOU remains possible because the actual HTTP client
re-resolves the hostname when it connects. Callers that follow redirects must
re-validate every hop with :func:`validate_public_url` before following it.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = frozenset({"http", "https"})

_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",  # nosec B104
        "::1",
        "169.254.169.254",  # Cloud metadata service (AWS/GCP/Azure)
        "metadata.google.internal",
    }
)


class UnsafeUrlError(ValueError):
    """Raised when a URL targets an internal/blocked network location."""


def _is_internal_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_public_url(url: str) -> None:
    """Raise :class:`UnsafeUrlError` if ``url`` is not a safe public target.

    Blocks non-http(s) schemes, a denylist of internal hostnames, literal
    private/loopback/link-local/reserved IPs, and DNS names that resolve to any
    such address.
    """
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"URL scheme not allowed: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeUrlError("URL does not contain a hostname")

    if hostname.lower() in _BLOCKED_HOSTS:
        raise UnsafeUrlError("Internal network URLs are not allowed")

    # Literal IP in the host position.
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None
    if ip is not None:
        if _is_internal_ip(ip):
            raise UnsafeUrlError("Internal network URLs are not allowed")
        return

    # DNS name: reject if ANY resolved address is internal.
    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
    except socket.gaierror:
        # Let the actual HTTP request surface the resolution failure.
        return
    for *_, addr in resolved:
        try:
            resolved_ip = ipaddress.ip_address(addr[0])
        except ValueError:
            continue
        if _is_internal_ip(resolved_ip):
            raise UnsafeUrlError(
                "URLs that resolve to internal networks are not allowed"
            )
