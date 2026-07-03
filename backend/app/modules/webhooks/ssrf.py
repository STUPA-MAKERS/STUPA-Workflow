"""SSRF guard for webhook targets.

Before every send the target is checked: ``http(s)`` scheme, an optional host allowlist,
and - the core - the resolved target IP. All non-global addresses are blocked
(private/loopback/link-local/multicast/reserved/unspecified), which also covers the
metadata IP ``169.254.169.254`` (link-local). IPv4-in-IPv6 mappings (``::ffff:a.b.c.d``)
are unwrapped before the check.

DNS rebinding: resolution happens at send time (worker, right before the POST) and
checks every returned A/AAAA record - a single internal record blocks the send. A
residual TOCTOU between resolution and connect remains (httpx re-resolves); the worker's
egress policy is the second line of defense.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

# Host -> list of resolved IP strings. Injectable (tests / DNS-rebinding protection).
Resolver = Callable[[str], list[str]]


class SsrfError(Exception):
    """Target URL is not allowed (scheme/allowlist/internal IP)."""


def default_resolver(host: str) -> list[str]:  # pragma: no cover — real DNS
    """Resolve all A/AAAA records (deduped). Errors -> empty list (= blocked)."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return []
    return sorted({str(info[4][0]) for info in infos})


# NAT64 well-known prefix (RFC 6052): the target IPv4 lives in the low 32 bits of a
# ``64:ff9b::/96`` address. Such an address reports ``is_global=True`` and would slip
# through without unwrapping - a NAT64 gateway in the worker egress would then translate
# it to the embedded IPv4 (e.g. the metadata IP ``169.254.169.254`` or RFC1918).
_NAT64_WKP = ipaddress.IPv6Network("64:ff9b::/96")


def _unmap(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Reduce IPv4-in-IPv6 embeddings to the embedded IPv4 so the global check sees the
    actual target address.

    Covers all three embeddings through which an internal IPv4 could otherwise slip
    through as a global IPv6: ``::ffff:a.b.c.d`` (IPv4-mapped), ``2002:a.b.c.d::/16``
    (6to4) and ``64:ff9b::a.b.c.d`` (NAT64, RFC 6052).
    """
    if not isinstance(ip, ipaddress.IPv6Address):
        return ip
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip in _NAT64_WKP:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """``True`` for any non-global (internal/special) address."""
    return not _unmap(ip).is_global


def assert_allowed_url(
    url: str,
    *,
    allowlist: Iterable[str] = (),
    resolver: Resolver = default_resolver,
) -> list[str]:
    """Check the target URL against the SSRF guard. Returns the checked target IPs.

    Raises ``SsrfError`` if the scheme is unsupported, the host is missing, the allowlist
    (if set) does not contain the host, or any target IP is non-global. A host given as an
    IP literal is checked directly (no DNS).
    """
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise SsrfError(f"unsupported scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise SsrfError("missing host")

    allow = {h.lower() for h in allowlist}
    if allow and host.lower() not in allow:
        raise SsrfError(f"host not in allowlist: {host!r}")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        addrs = resolver(host)
        if not addrs:
            raise SsrfError(f"dns resolution failed: {host!r}") from None
        ips = [ipaddress.ip_address(a) for a in addrs]
    else:
        ips = [literal]

    for ip in ips:
        if _is_blocked(ip):
            raise SsrfError(f"blocked non-global target: {ip}")
    return [str(ip) for ip in ips]


def pin_url(url: str, ip: str) -> tuple[str, str]:
    """Rewrite the URL to the validated target IP (DNS-rebinding pinning).

    Returns ``(ip_url, host_header)``: ``ip_url`` replaces the host with the IP (so the
    client connects to exactly the checked address instead of re-resolving),
    ``host_header`` carries the original ``Host`` for routing/TLS SNI. This removes the
    TOCTOU between resolution and connect.
    """
    parsed = urlsplit(url)
    port = parsed.port
    host_header = parsed.hostname or ""
    if port is not None:
        host_header = f"{host_header}:{port}"
    ip_host = f"[{ip}]" if ":" in ip else ip
    netloc = f"{ip_host}:{port}" if port is not None else ip_host
    ip_url = urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))
    return ip_url, host_header
