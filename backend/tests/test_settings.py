"""TDD: Settings aus env; fehlende Pflicht-Secrets → klarer Startfehler."""

import pytest

from app.settings import SettingsError, load_settings

REQUIRED = ["DATABASE_URL", "SESSION_SECRET", "MAGIC_LINK_SECRET"]
# Secrets müssen ≥16 Zeichen sein (security.md §10) — Test-Werte entsprechend lang.
_OK_SECRET = "x" * 16


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
