"""Unit tests for the ClamAV scanner. A fake module replaces `clamd`."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from app.modules.files import scanner as scanner_mod
from app.modules.files.scanner import (
    EICAR_TEST_BYTES,
    ClamdScanner,
    ScannerError,
    ScanVerdict,
    build_scanner,
    scan_or_raise,
)
from app.settings import Settings, load_settings
from app.shared.errors import ServiceUnavailableError, UnsupportedMediaTypeError


class _FakeDaemon:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self._result = result

    def instream(self, _stream: Any) -> dict[str, Any]:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


@pytest.fixture
def fake_clamd(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"result": {"stream": ("OK", None)}}
    module = types.ModuleType("clamd")

    def _socket(*_a: Any, **_kw: Any) -> _FakeDaemon:
        return _FakeDaemon(state["result"])

    module.ClamdNetworkSocket = _socket  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "clamd", module)
    return state


async def test_scan_clean(fake_clamd: dict[str, Any]) -> None:
    fake_clamd["result"] = {"stream": ("OK", None)}
    verdict = await ClamdScanner(host="clamav").scan(b"hello")
    assert verdict == ScanVerdict(clean=True)


async def test_scan_found_reports_signature(fake_clamd: dict[str, Any]) -> None:
    fake_clamd["result"] = {"stream": ("FOUND", "Eicar-Test-Signature")}
    verdict = await ClamdScanner(host="clamav").scan(EICAR_TEST_BYTES)
    assert verdict.clean is False
    assert verdict.signature == "Eicar-Test-Signature"


async def test_scan_found_without_signature_defaults_unknown(
    fake_clamd: dict[str, Any],
) -> None:
    fake_clamd["result"] = {"stream": ("FOUND", None)}
    verdict = await ClamdScanner(host="clamav").scan(b"x")
    assert verdict.signature == "unknown"


async def test_scan_error_wrapped(fake_clamd: dict[str, Any]) -> None:
    fake_clamd["result"] = ConnectionError("clamd down")
    with pytest.raises(ScannerError):
        await ClamdScanner(host="clamav").scan(b"x")


async def test_scan_empty_result_raises(fake_clamd: dict[str, Any]) -> None:
    """Raise for a result without a "stream" key, a protocol error."""
    fake_clamd["result"] = {}
    with pytest.raises(ScannerError):
        await ClamdScanner(host="clamav").scan(b"x")


def test_build_scanner_disabled_returns_none() -> None:
    assert build_scanner(load_settings()) is None


def test_build_scanner_enabled() -> None:
    settings = load_settings(clamav_host="clamav", clamav_port=3310)
    scanner = build_scanner(settings)
    assert isinstance(scanner, ClamdScanner)
    assert scanner.host == "clamav"


class _StubScanner:
    def __init__(self, result: ScanVerdict | Exception) -> None:
        self._result = result

    async def scan(self, data: bytes) -> ScanVerdict:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _use_scanner(monkeypatch: pytest.MonkeyPatch, result: ScanVerdict | Exception) -> None:
    def _build(_settings: Settings) -> _StubScanner:
        return _StubScanner(result)

    monkeypatch.setattr(scanner_mod, "build_scanner", _build)


async def test_scan_or_raise_skips_without_scanner_outside_production() -> None:
    await scan_or_raise(b"data", load_settings(environment="development"))


async def test_scan_or_raise_fails_closed_without_scanner_in_production() -> None:
    with pytest.raises(ServiceUnavailableError):
        await scan_or_raise(b"data", load_settings(environment="production"))


async def test_scan_or_raise_clean_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_scanner(monkeypatch, ScanVerdict(clean=True))
    await scan_or_raise(b"data", load_settings())


async def test_scan_or_raise_scanner_error_gives_503(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_scanner(monkeypatch, ScannerError("down"))
    with pytest.raises(ServiceUnavailableError):
        await scan_or_raise(b"data", load_settings())


async def test_scan_or_raise_infected_names_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_scanner(monkeypatch, ScanVerdict(clean=False, signature="Eicar-Test-Signature"))
    with pytest.raises(UnsupportedMediaTypeError, match="Eicar-Test-Signature"):
        await scan_or_raise(EICAR_TEST_BYTES, load_settings())


async def test_scan_or_raise_infected_without_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_scanner(monkeypatch, ScanVerdict(clean=False, signature=None))
    with pytest.raises(UnsupportedMediaTypeError, match="unknown"):
        await scan_or_raise(b"x", load_settings())
