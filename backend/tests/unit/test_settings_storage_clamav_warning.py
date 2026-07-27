"""AUD-071: object storage on and ClamAV off must give a startup warning.

With object storage active but no scanner, the backend stores attachments and enqueues a
scan job. The worker finds no scanner and leaves `scanned=False`. Downloads then stay in
quarantine forever (409). This misconfiguration must not stay silent.
`Settings._strict_security_warnings` must warn about it.
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
    """Warn about quarantine when MINIO is set and CLAMAV_HOST is empty."""
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
    """Give no quarantine warning when MINIO and CLAMAV are both set."""
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
    """Give no quarantine warning when object storage is off, even with CLAMAV off."""
    _base_env(monkeypatch)
    s, warnings = _settings_warnings(
        monkeypatch,
        _env_file=None,
        minio_endpoint=None,
        clamav_host=None,
    )
    assert s.storage_enabled is False
    assert not any("quarantine" in m.lower() for m in warnings)
