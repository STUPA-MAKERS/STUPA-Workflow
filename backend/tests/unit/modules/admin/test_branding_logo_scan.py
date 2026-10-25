"""The ClamAV scan of the inline branding logos before the store."""

from __future__ import annotations

import pytest

from app.modules.admin.branding import Branding, BrandingAsset
from app.modules.admin.site_config_service import SiteConfigService
from app.modules.files import scanner as scanner_mod
from app.modules.files.scanner import ScanVerdict
from app.settings import Settings, load_settings
from app.shared.errors import ServiceUnavailableError, UnsupportedMediaTypeError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _asset(url: str) -> BrandingAsset:
    return BrandingAsset(url=url, filename="logo.png", mime="image/png", size=8)


def _branding() -> Branding:
    return Branding(
        logos={
            "wordmark": _asset("data:image/png;base64,iVBORw0KGgo="),
            "imagemark": _asset("https://example.org/logo.png"),
        }
    )


class _Scanner:
    def __init__(self, verdict: ScanVerdict) -> None:
        self.verdict = verdict
        self.scanned: list[bytes] = []

    async def scan(self, data: bytes) -> ScanVerdict:
        self.scanned.append(data)
        return self.verdict


def _use(monkeypatch: pytest.MonkeyPatch, scanner: _Scanner) -> None:
    def _build(_settings: Settings) -> _Scanner:
        return scanner

    monkeypatch.setattr(scanner_mod, "build_scanner", _build)


def test_inline_bytes_decodes_a_data_url_only() -> None:
    assert _asset("data:image/png;base64,iVBORw0KGgo=").inline_bytes() == PNG_SIGNATURE
    assert _asset("https://example.org/logo.png").inline_bytes() is None


async def test_scan_covers_the_inline_logos_only(monkeypatch: pytest.MonkeyPatch) -> None:
    scanner = _Scanner(ScanVerdict(clean=True))
    _use(monkeypatch, scanner)
    service = SiteConfigService(object(), settings=load_settings())  # type: ignore[arg-type]
    await service._scan_logos(_branding())
    assert scanner.scanned == [PNG_SIGNATURE]


async def test_infected_logo_is_refused_before_the_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The session is a bare object, so any store attempt would fail differently."""
    _use(monkeypatch, _Scanner(ScanVerdict(clean=False, signature="Eicar-Test-Signature")))
    service = SiteConfigService(object(), settings=load_settings())  # type: ignore[arg-type]
    with pytest.raises(UnsupportedMediaTypeError, match="Eicar-Test-Signature"):
        await service.save(_branding(), "admin")


async def test_missing_scanner_in_production_is_unavailable() -> None:
    service = SiteConfigService(
        object(),  # type: ignore[arg-type]
        settings=load_settings(environment="production"),
    )
    with pytest.raises(ServiceUnavailableError, match="Virus scan"):
        await service.restore_branding(_branding(), "admin")


async def test_scan_falls_back_to_the_app_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    scanner = _Scanner(ScanVerdict(clean=True))
    _use(monkeypatch, scanner)
    await SiteConfigService(object())._scan_logos(_branding())  # type: ignore[arg-type]
    assert scanner.scanned == [PNG_SIGNATURE]
