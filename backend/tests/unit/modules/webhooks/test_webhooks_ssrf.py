"""SSRF-Guard (T-19, security.md §5): jede interne/Sonder-IP wird blockiert."""

from __future__ import annotations

import pytest

from app.modules.webhooks.ssrf import SsrfError, assert_allowed_url, pin_url


def _resolver(*addrs: str):
    return lambda _host: list(addrs)


def test_public_literal_ok() -> None:
    assert assert_allowed_url("https://93.184.216.34/hook") == ["93.184.216.34"]


def test_public_dns_ok() -> None:
    ips = assert_allowed_url("https://example.com/hook", resolver=_resolver("1.1.1.1"))
    assert ips == ["1.1.1.1"]


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # private
        "172.16.0.1",  # private
        "192.168.1.1",  # private
        "169.254.169.254",  # link-local / cloud metadata
        "0.0.0.0",  # unspecified
        "::1",  # ipv6 loopback
        "fc00::1",  # ipv6 unique-local
        "fe80::1",  # ipv6 link-local
        "::ffff:10.0.0.1",  # ipv4-mapped private
        "64:ff9b::a9fe:a9fe",  # NAT64-wrapped 169.254.169.254 (cloud metadata)
        "64:ff9b::a00:1",  # NAT64-wrapped 10.0.0.1 (private)
        "2002:a00:1::",  # 6to4-wrapped 10.0.0.1 (private)
    ],
)
def test_blocks_internal_literals(ip: str) -> None:
    with pytest.raises(SsrfError):
        assert_allowed_url(f"http://[{ip}]/h" if ":" in ip else f"http://{ip}/h")


def test_blocks_internal_via_dns() -> None:
    with pytest.raises(SsrfError):
        assert_allowed_url("http://evil.test/h", resolver=_resolver("10.1.2.3"))


def test_blocks_when_any_record_internal() -> None:
    # Round-Robin-Rebinding: ein interner Record unter mehreren blockt den Versand.
    with pytest.raises(SsrfError):
        assert_allowed_url(
            "http://mix.test/h", resolver=_resolver("8.8.8.8", "127.0.0.1")
        )


def test_dns_empty_blocked() -> None:
    with pytest.raises(SsrfError):
        assert_allowed_url("http://nxdomain.test/h", resolver=_resolver())


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(SsrfError):
        assert_allowed_url("ftp://example.com/h")
    with pytest.raises(SsrfError):
        assert_allowed_url("file:///etc/passwd")


def test_rejects_missing_host() -> None:
    with pytest.raises(SsrfError):
        assert_allowed_url("http:///nohost")


def test_allowlist_blocks_unlisted_host() -> None:
    with pytest.raises(SsrfError):
        assert_allowed_url(
            "https://other.com/h",
            allowlist=["good.com"],
            resolver=_resolver("1.1.1.1"),
        )


def test_allowlist_permits_listed_host() -> None:
    ips = assert_allowed_url(
        "https://Good.com/h",  # Case-insensitiv
        allowlist=["good.com"],
        resolver=_resolver("1.1.1.1"),
    )
    assert ips == ["1.1.1.1"]


def test_ipv6_public_ok() -> None:
    assert assert_allowed_url("https://[2606:4700:4700::1111]/h") == [
        "2606:4700:4700::1111"
    ]


# --------------------------------------------------------------- pin_url #
def test_pin_url_ipv4() -> None:
    ip_url, host = pin_url("https://hook.example/path?q=1", "93.184.216.34")
    assert ip_url == "https://93.184.216.34/path?q=1"
    assert host == "hook.example"


def test_pin_url_with_port() -> None:
    ip_url, host = pin_url("http://hook.example:8443/h", "203.0.113.9")
    assert ip_url == "http://203.0.113.9:8443/h"
    assert host == "hook.example:8443"


def test_pin_url_ipv6_target_is_bracketed() -> None:
    ip_url, host = pin_url("https://hook.example/h", "2606:4700:4700::1111")
    assert ip_url == "https://[2606:4700:4700::1111]/h"
    assert host == "hook.example"


def test_pin_url_empty_path_becomes_root() -> None:
    ip_url, _ = pin_url("https://hook.example", "93.184.216.34")
    assert ip_url == "https://93.184.216.34/"
