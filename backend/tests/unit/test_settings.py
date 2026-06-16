"""TDD: Settings aus env; fehlende Pflicht-Secrets → klarer Startfehler."""

from typing import Any

import pytest

from app import settings as settings_mod
from app.settings import Settings, SettingsError, load_settings

REQUIRED = ["DATABASE_URL", "SESSION_SECRET", "MAGIC_LINK_SECRET"]
# Secrets müssen ≥16 Zeichen sein (security.md §10) — Test-Werte entsprechend lang.
_OK_SECRET = "x" * 16


class _SpyLog:
    """Stand-in für den ``app.settings``-Modul-Logger — deterministisch und immun
    gegen den globalen Logging-State der Gesamt-Suite. Andere Tests konfigurieren
    Logging mit ``disable_existing_loggers`` und leeren damit ``caplog`` bzw. direkt
    angehängte Handler (vgl. ``test_flow_dispatch._SpyLogger``)."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str, *args: object) -> None:
        self.warnings.append(msg % args if args else msg)


def _settings_warnings(
    monkeypatch: pytest.MonkeyPatch, **overrides: Any
) -> tuple[Settings, list[str]]:
    """``load_settings`` ausführen und die ``app.settings``-WARN-Meldungen einfangen,
    indem der Modul-Logger durch einen Spy ersetzt wird (s. :class:`_SpyLog`)."""
    spy = _SpyLog()
    monkeypatch.setattr(settings_mod, "_log", spy)
    settings = load_settings(**overrides)
    return settings, spy.warnings


def test_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app:pw@db/antrag")
    monkeypatch.setenv("SESSION_SECRET", _OK_SECRET)
    monkeypatch.setenv("MAGIC_LINK_SECRET", _OK_SECRET)
    s = load_settings(_env_file=None)
    assert s.database_url == "postgresql+asyncpg://app:pw@db/antrag"
    assert s.session_secret == _OK_SECRET


@pytest.mark.parametrize("missing", REQUIRED)
def test_missing_required_secret_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    for key in REQUIRED:
        monkeypatch.setenv(key, "x")
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(SettingsError) as exc:
        load_settings(_env_file=None)
    # Fehlertext nennt das fehlende Feld klar.
    assert missing.lower() in str(exc.value).lower()


def test_optional_have_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "x")
    monkeypatch.setenv("SESSION_SECRET", _OK_SECRET)
    monkeypatch.setenv("MAGIC_LINK_SECRET", _OK_SECRET)
    s = load_settings(_env_file=None)
    assert s.app_name
    assert s.forwarded_allow_ips  # eng (nicht "*")
    assert s.cors_allow_origins == []  # CORS aus per Default


def test_short_secret_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "x")
    monkeypatch.setenv("SESSION_SECRET", _OK_SECRET)
    monkeypatch.setenv("MAGIC_LINK_SECRET", "too-short")  # < 16 → Boot-Fehler
    with pytest.raises(SettingsError):
        load_settings(_env_file=None)


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "x")
    monkeypatch.setenv("SESSION_SECRET", _OK_SECRET)
    monkeypatch.setenv("MAGIC_LINK_SECRET", _OK_SECRET)


def test_strict_security_default_on_and_dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: ``strict_security`` an, ``environment`` dev → Härtung dennoch aktiv (fail-safe)."""
    _base_env(monkeypatch)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("STRICT_SECURITY", raising=False)
    s = load_settings(_env_file=None)
    assert s.strict_security is True
    assert s.is_production is False
    # Fail-safe: Härtung greift trotz dev-Environment.
    assert s.strict_security_enabled is True


def test_production_env_enables_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.18.0.2")  # "*" wäre in prod verboten
    s = load_settings(_env_file=None)
    assert s.is_production is True
    assert s.strict_security_enabled is True


def test_strict_security_off_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bewusstes Abschalten: ``STRICT_SECURITY=false`` + dev → keine Härtung."""
    _base_env(monkeypatch)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("STRICT_SECURITY", "false")
    s = load_settings(_env_file=None)
    assert s.strict_security is False
    assert s.strict_security_enabled is False


def test_dev_env_logs_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nicht-production → laute Warnung im Log (Guards können aussetzen)."""
    _base_env(monkeypatch)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    _settings, warnings = _settings_warnings(monkeypatch, _env_file=None)
    assert any("ENVIRONMENT" in m for m in warnings)


def test_empty_webhook_allowlist_warns_under_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leere Webhook-Allowlist unter Härtung → laute Warnung."""
    _base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.18.0.2")
    s, warnings = _settings_warnings(monkeypatch, _env_file=None)
    assert s.webhook_host_allowlist == []
    assert any("WEBHOOK_ALLOWLIST" in m for m in warnings)


def test_webhook_allowlist_set_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gesetzte Allowlist → keine Webhook-Warnung."""
    _base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.18.0.2")
    monkeypatch.setenv("STRICT_SECURITY", "true")
    s, warnings = _settings_warnings(
        monkeypatch, _env_file=None, webhook_host_allowlist=["hooks.example"]
    )
    assert s.webhook_host_allowlist == ["hooks.example"]
    assert not any("WEBHOOK_ALLOWLIST" in m for m in warnings)
