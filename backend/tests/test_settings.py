"""TDD: Settings aus env; fehlende Pflicht-Secrets → klarer Startfehler."""

import pytest

from app.settings import SettingsError, load_settings

REQUIRED = ["DATABASE_URL", "SESSION_SECRET", "MAGIC_LINK_SECRET"]


def test_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app:pw@db/antrag")
    monkeypatch.setenv("SESSION_SECRET", "s")
    monkeypatch.setenv("MAGIC_LINK_SECRET", "m")
    s = load_settings(_env_file=None)
    assert s.database_url == "postgresql+asyncpg://app:pw@db/antrag"
    assert s.session_secret == "s"


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
    for key in REQUIRED:
        monkeypatch.setenv(key, "x")
    s = load_settings(_env_file=None)
    assert s.app_name
    assert s.forwarded_allow_ips  # eng (nicht "*")
    assert s.cors_allow_origins == []  # CORS aus per Default
