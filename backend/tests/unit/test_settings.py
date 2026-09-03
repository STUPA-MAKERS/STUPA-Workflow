"""Load the settings from the environment.

A missing required secret must give a clear startup error.
"""

from typing import Any

import pytest

from app import settings as settings_mod
from app.settings import Settings, SettingsError, load_settings

REQUIRED = ["DATABASE_URL", "SESSION_SECRET", "MAGIC_LINK_SECRET"]
# A secret needs 16 characters or more (security.md §10). The test values are that long.
_OK_SECRET = "x" * 16


class _SpyLog:
    """Stand-in for the `app.settings` module logger.

    The spy is deterministic and immune to the global logging state of the full suite.
    Other tests configure logging with `disable_existing_loggers`. That step empties
    `caplog` and drops directly attached handlers. See `test_flow_dispatch._SpyLogger`.
    """

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str, *args: object) -> None:
        self.warnings.append(msg % args if args else msg)


def _settings_warnings(
    monkeypatch: pytest.MonkeyPatch, **overrides: Any
) -> tuple[Settings, list[str]]:
    """Run `load_settings` and collect the warning messages of `app.settings`.

    The helper replaces the module logger with a spy. See `_SpyLog`.
    """
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
    assert missing.lower() in str(exc.value).lower()


def test_optional_have_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "x")
    monkeypatch.setenv("SESSION_SECRET", _OK_SECRET)
    monkeypatch.setenv("MAGIC_LINK_SECRET", _OK_SECRET)
    s = load_settings(_env_file=None)
    assert s.app_name
    assert s.forwarded_allow_ips  # narrow default, not "*"
    assert s.cors_allow_origins == []  # CORS is off by default


def test_short_secret_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "x")
    monkeypatch.setenv("SESSION_SECRET", _OK_SECRET)
    monkeypatch.setenv("MAGIC_LINK_SECRET", "too-short")  # under 16 characters, so boot fails
    with pytest.raises(SettingsError):
        load_settings(_env_file=None)


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "x")
    monkeypatch.setenv("SESSION_SECRET", _OK_SECRET)
    monkeypatch.setenv("MAGIC_LINK_SECRET", _OK_SECRET)


def test_strict_security_default_on_and_dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep `strict_security` on by default, as a fail-safe for a dev environment."""
    _base_env(monkeypatch)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("STRICT_SECURITY", raising=False)
    s = load_settings(_env_file=None)
    assert s.strict_security is True
    assert s.is_production is False
    assert s.strict_security_enabled is True


def test_production_env_enables_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.18.0.2")  # "*" is forbidden in production
    s = load_settings(_env_file=None)
    assert s.is_production is True
    assert s.strict_security_enabled is True


def test_strict_security_off_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the hardening off on purpose with `STRICT_SECURITY=false` in a dev environment."""
    _base_env(monkeypatch)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("STRICT_SECURITY", "false")
    s = load_settings(_env_file=None)
    assert s.strict_security is False
    assert s.strict_security_enabled is False


def test_dev_env_logs_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Log a loud warning outside production, because some guards can stay off."""
    _base_env(monkeypatch)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    _settings, warnings = _settings_warnings(monkeypatch, _env_file=None)
    assert any("ENVIRONMENT" in m for m in warnings)


def test_empty_webhook_allowlist_warns_under_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warn loudly when the webhook allowlist is empty and the hardening is on."""
    _base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.18.0.2")
    s, warnings = _settings_warnings(monkeypatch, _env_file=None)
    assert s.webhook_host_allowlist == []
    assert any("WEBHOOK_HOST_ALLOWLIST" in m for m in warnings)


def test_webhook_allowlist_set_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Send no webhook warning when the allowlist has an entry."""
    _base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.18.0.2")
    monkeypatch.setenv("STRICT_SECURITY", "true")
    s, warnings = _settings_warnings(
        monkeypatch, _env_file=None, webhook_host_allowlist=["hooks.example"]
    )
    assert s.webhook_host_allowlist == ["hooks.example"]
    assert not any("WEBHOOK_HOST_ALLOWLIST" in m for m in warnings)


def _clear_allowlist_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every spelling of the webhook allowlist from the environment."""
    for key in ("WEBHOOK_HOST_ALLOWLIST", "WEBHOOK_ALLOWLIST"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)


def test_webhook_allowlist_reads_canonical_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read the allowlist from the canonical `WEBHOOK_HOST_ALLOWLIST`."""
    _base_env(monkeypatch)
    _clear_allowlist_env(monkeypatch)
    monkeypatch.setenv("WEBHOOK_HOST_ALLOWLIST", "hooks.example")
    s = load_settings(_env_file=None)
    assert s.webhook_host_allowlist == ["hooks.example"]


def test_webhook_allowlist_reads_documented_legacy_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read the allowlist from the older `WEBHOOK_ALLOWLIST` too.

    `deploy/.env.example` documented that name for a long time. A deployment that
    copied it must keep an allowlist that works, not an empty one.
    """
    _base_env(monkeypatch)
    _clear_allowlist_env(monkeypatch)
    monkeypatch.setenv("WEBHOOK_ALLOWLIST", "hooks.example")
    s = load_settings(_env_file=None)
    assert s.webhook_host_allowlist == ["hooks.example"]


def test_webhook_allowlist_splits_comma_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Split a comma-separated value, which is the documented format."""
    _base_env(monkeypatch)
    _clear_allowlist_env(monkeypatch)
    monkeypatch.setenv("WEBHOOK_HOST_ALLOWLIST", "host1, host2 ,")
    s = load_settings(_env_file=None)
    assert s.webhook_host_allowlist == ["host1", "host2"]


def test_webhook_allowlist_accepts_json_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Accept a JSON list, the format that pydantic-settings took before."""
    _base_env(monkeypatch)
    _clear_allowlist_env(monkeypatch)
    monkeypatch.setenv("WEBHOOK_HOST_ALLOWLIST", '["host1", "host2"]')
    s = load_settings(_env_file=None)
    assert s.webhook_host_allowlist == ["host1", "host2"]


def test_webhook_allowlist_broken_json_does_not_abort_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fall back to the comma split when a bracketed value is not valid JSON.

    A typo in the value must not stop the boot with a raw parser error.
    """
    _base_env(monkeypatch)
    _clear_allowlist_env(monkeypatch)
    monkeypatch.setenv("WEBHOOK_HOST_ALLOWLIST", "[host1, host2")
    s = load_settings(_env_file=None)
    assert s.webhook_host_allowlist == ["[host1", "host2"]


def test_webhook_allowlist_canonical_name_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prefer the canonical name when both names are set."""
    _base_env(monkeypatch)
    _clear_allowlist_env(monkeypatch)
    monkeypatch.setenv("WEBHOOK_HOST_ALLOWLIST", "canonical.example")
    monkeypatch.setenv("WEBHOOK_ALLOWLIST", "legacy.example")
    s = load_settings(_env_file=None)
    assert s.webhook_host_allowlist == ["canonical.example"]


def test_webhook_allowlist_empty_value_stays_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treat an empty or blank value as no allowlist."""
    _base_env(monkeypatch)
    _clear_allowlist_env(monkeypatch)
    monkeypatch.setenv("WEBHOOK_HOST_ALLOWLIST", "  ")
    s = load_settings(_env_file=None)
    assert s.webhook_host_allowlist == []


def test_cors_allow_origins_splits_comma_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Split `CORS_ALLOW_ORIGINS` the same way, so a plain value cannot crash boot."""
    _base_env(monkeypatch)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://a.example,https://b.example")
    s = load_settings(_env_file=None)
    assert s.cors_allow_origins == ["https://a.example", "https://b.example"]
