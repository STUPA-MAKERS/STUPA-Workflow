"""SSRF-Guard für Webhook-Ziele (security.md §5).

Vor **jedem** Versand wird das Ziel geprüft: Schema ``http(s)``, optionale Host-
Allowlist und — der Kern — die **aufgelöste Ziel-IP**. Blockiert werden alle nicht-
globalen Adressen (private/loopback/link-local/multicast/reserved/unspezifiziert),
womit auch die Metadaten-IP ``169.254.169.254`` (link-local) erfasst ist. IPv4-in-
IPv6-Mappings (``::ffff:a.b.c.d``) werden vor der Prüfung entpackt.

DNS-Rebinding: die Auflösung passiert **zur Sende-Zeit** (Worker, unmittelbar vor dem
POST) und prüft **alle** zurückgegebenen A/AAAA-Records — ein einzelner interner
Record blockt den Versand. Ein Rest-TOCTOU zwischen Auflösung und Connect bleibt
(httpx löst selbst erneut auf); die Egress-Policy des Workers (security.md §5) ist die
zweite Verteidigungslinie.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

# Host → Liste aufgelöster IP-Strings. Injizierbar (Tests/DNS-Rebinding-Schutz).
Resolver = Callable[[str], list[str]]


class SsrfError(Exception):
    """Ziel-URL ist nicht erlaubt (Schema/Allowlist/interne IP)."""


def default_resolver(host: str) -> list[str]:  # pragma: no cover — echtes DNS
    """Alle A/AAAA-Records auflösen (deduped). Fehler → leere Liste (= blockiert)."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return []
    return sorted({str(info[4][0]) for info in infos})


def _unmap(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> (
    ipaddress.IPv4Address | ipaddress.IPv6Address
):
    """IPv4-in-IPv6 (``::ffff:a.b.c.d``) auf die IPv4-Adresse zurückführen."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """``True`` für jede nicht-globale (= interne/Sonder-)Adresse."""
    return not _unmap(ip).is_global


def assert_allowed_url(
    url: str,
    *,
    allowlist: Iterable[str] = (),
    resolver: Resolver = default_resolver,
) -> list[str]:
    """Ziel-URL gegen den SSRF-Guard prüfen. Gibt die geprüften Ziel-IPs zurück.

    Wirft :class:`SsrfError`, wenn Schema unzulässig, Host fehlt, die Allowlist
    (falls gesetzt) den Host nicht enthält oder **irgendeine** Ziel-IP nicht global
    ist. Eine als Host angegebene IP-Literal wird direkt geprüft (kein DNS).
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
    """URL auf die **validierte** Ziel-IP umschreiben (DNS-Rebinding-Pinning).

    Gibt ``(ip_url, host_header)`` zurück: ``ip_url`` ersetzt den Host durch die IP
    (so verbindet der Client genau zur geprüften Adresse statt erneut aufzulösen),
    ``host_header`` trägt den ursprünglichen ``Host`` für Routing/TLS-SNI. Der TOCTOU
    zwischen Auflösung und Connect entfällt damit.
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
