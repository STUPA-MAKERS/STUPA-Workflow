"""SSRF guard for webhook targets.

The guard checks the target before every send. It accepts only the `http` scheme and the
`https` scheme. It applies the optional host allowlist. As the core check it then looks
at the resolved target IP. The guard blocks every non-global address: private, loopback,
link-local, multicast, reserved and unspecified. This also covers the metadata IP
`169.254.169.254`, which is link-local. The guard unwraps an IPv4-in-IPv6 mapping such
as `::ffff:a.b.c.d` before the check.

DNS rebinding: the worker resolves the host at send time, right before the POST. The
guard checks every A record and AAAA record that comes back. One internal record blocks
the send. A residual TOCTOU between resolution and connect stays, because httpx resolves
again. The egress policy of the worker is the second line of defense.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

# Maps a host to the list of resolved IP strings. Callers inject it in tests and for the
# DNS-rebinding check.
Resolver = Callable[[str], list[str]]


class SsrfError(Exception):
    """The target URL failed the scheme check, the allowlist check or the IP check."""


def default_resolver(host: str) -> list[str]:  # pragma: no cover — real DNS
    """Resolve all A records and AAAA records of a host, deduped and sorted.

    Returns:
        The resolved IP strings. An empty list on a resolution error, which blocks the
        target.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return []
    return sorted({str(info[4][0]) for info in infos})


# NAT64 well-known prefix (RFC 6052). A `64:ff9b::/96` address holds the target IPv4 in
# its low 32 bits and reports `is_global=True`. Without the unwrap it passes the guard.
# A NAT64 gateway in the worker egress then translates it to the embedded IPv4, for
# example the metadata IP `169.254.169.254` or an RFC1918 address.
_NAT64_WKP = ipaddress.IPv6Network("64:ff9b::/96")


def _unmap(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Reduce an IPv4-in-IPv6 embedding to the embedded IPv4 address.

    The global check then sees the actual target address. Three embeddings could
    otherwise let an internal IPv4 pass as a global IPv6. The unwrap covers all of them:
    `::ffff:a.b.c.d` (IPv4-mapped), `2002:a.b.c.d::/16` (6to4) and `64:ff9b::a.b.c.d`
    (NAT64, RFC 6052).
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
    """Report whether the address is non-global, that is internal or special."""
    return not _unmap(ip).is_global


def assert_allowed_url(
    url: str,
    *,
    allowlist: Iterable[str] = (),
    resolver: Resolver = default_resolver,
) -> list[str]:
    """Check the target URL against the SSRF guard.

    A host that is already an IP literal goes through the check directly, without DNS.

    Returns:
        The checked target IPs.

    Raises:
        SsrfError: The scheme is not supported, the host is missing, the allowlist is set
            and does not contain the host, or one target IP is non-global.
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
    """Rewrite the URL to the validated target IP and pin it against DNS rebinding.

    The pin removes the TOCTOU between resolution and connect.

    Returns:
        A tuple `(ip_url, host_header)`. In `ip_url` the IP replaces the host, so the
        client connects to the checked address and does not resolve again.
        `host_header` keeps the original `Host` value for routing and TLS SNI.
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
