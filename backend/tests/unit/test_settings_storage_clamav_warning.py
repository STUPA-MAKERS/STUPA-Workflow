"""AUD-071: MINIO an / CLAMAV aus → laute Startup-Warnung.

Mit Object-Storage aktiv aber ohne Scanner werden Anhänge gespeichert und ein Scan-Job
enqueued; der Worker hat aber keinen Scanner und lässt ``scanned=False`` — Downloads
bleiben dauerhaft in Quarantäne (409). Diese Fehlkonfiguration darf nicht still bleiben:
``Settings._strict_security_warnings`` muss laut warnen.
"""

from typing import Any

import pytest

from app import settings as settings_mod
from app.settings import Settings, load_settings

_OK_SECRET = "x" * 16


class _SpyLog:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str, *args: object) -> None:
        self.warnings.append(msg % args if args else msg)


def _settings_warnings(
    monkeypatch: pytest.MonkeyPatch, **overrides: Any
) -> tuple[Settings, list[str]]:
    spy = _SpyLog()
    monkeypatch.setattr(settings_mod, "_log", spy)
    settings = load_settings(**overrides)
    return settings, spy.warnings


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app:pw@db/antrag")
    monkeypatch.setenv("SESSION_SECRET", _OK_SECRET)
    monkeypatch.setenv("MAGIC_LINK_SECRET", _OK_SECRET)


def test_storage_on_clamav_off_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """MINIO gesetzt, CLAMAV_HOST leer → CLAMAV-Quarantäne-Warnung."""
    _base_env(monkeypatch)
    s, warnings = _settings_warnings(
        monkeypatch,
        _env_file=None,
        minio_endpoint="minio:9000",
        clamav_host=None,
    )
    assert s.storage_enabled is True
    assert s.clamav_enabled is False
    assert any("CLAMAV" in m and "quarantine" in m.lower() for m in warnings)


def test_storage_on_clamav_on_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """MINIO + CLAMAV beide gesetzt → keine Quarantäne-Warnung."""
    _base_env(monkeypatch)
    s, warnings = _settings_warnings(
        monkeypatch,
        _env_file=None,
        minio_endpoint="minio:9000",
        clamav_host="clamav",
    )
    assert s.storage_enabled is True
    assert s.clamav_enabled is True
    assert not any("quarantine" in m.lower() for m in warnings)


def test_storage_off_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ohne Object-Storage → keine Quarantäne-Warnung (auch ohne CLAMAV)."""
    _base_env(monkeypatch)
    s, warnings = _settings_warnings(
        monkeypatch,
        _env_file=None,
        minio_endpoint=None,
        clamav_host=None,
    )
    assert s.storage_enabled is False
    assert not any("quarantine" in m.lower() for m in warnings)
