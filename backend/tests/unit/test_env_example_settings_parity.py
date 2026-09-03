"""Keep `deploy/.env.example` and `app.settings.Settings` in step.

`Settings` uses `extra="ignore"`. A key that the template documents under a name no
field reads is therefore dropped without a word, and the operator gets the default.
For `WEBHOOK_ALLOWLIST` that meant an EMPTY webhook host allowlist on a deployment
that followed the documentation. These tests block a repeat.

A key that another service reads (compose, postgres, the altcha sidecar, pytex) is
listed below with its consumer. A key that nothing reads at all is listed too, so the
list stays an explicit, reviewed inventory instead of a silent hole.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import AliasChoices

from app.settings import Settings

# From tests/unit/, parents[2] is backend and parents[3] is the repo root that holds deploy/.
_EXAMPLE = (
    Path(__file__).resolve().parents[3] / "deploy" / ".env.example"
).read_text(encoding="utf-8")

# Keys in the template that the API deliberately does not read.
_NOT_READ_BY_THE_API = {
    # docker compose interpolation and the postgres/altcha images.
    "POSTGRES_DB": "postgres image",
    "POSTGRES_USER": "postgres image",
    "POSTGRES_PASSWORD": "postgres image",
    "ALTCHA_ROOT_PASSWORD": "altcha sidecar",
    "WEB_PORT": "compose interpolation",
    "WEB_HOST": "compose interpolation",
    # The pytex service reads these itself (pytex/app.py).
    "PYTEX_DEFAULT_OUTPUT": "pytex service",
    "PYTEX_DEFAULT_TRUST": "pytex service",
    "PYTEX_MAX_BODY_BYTES": "pytex service",
    "PYTEX_MAX_ASSETS": "pytex service",
    "PYTEX_MAX_ASSET_BYTES": "pytex service",
    # Documented but dead: nothing in the repo reads these. They stay listed here so a
    # NEW dead key fails the test. Do not add to this group without a decision.
    "AUDIT_DB_ROLE": "dead — the role name is hardcoded in the migrations",
    "WEBHOOK_HMAC_KEY": "dead — the signature uses the per-webhook secret from the DB",
    "SMTP_FROM": "dead — the sender address comes from MAIL_FROM",
    "NEXTCLOUD_WEBDAV_URL": "dead — no Nextcloud export in the code",
    "NEXTCLOUD_USER": "dead — no Nextcloud export in the code",
    "NEXTCLOUD_APP_PASSWORD": "dead — no Nextcloud export in the code",
    "NEXTCLOUD_BASE_PATH": "dead — no Nextcloud export in the code",
    "NEXTCLOUD_TIMEOUT_SECONDS": "dead — no Nextcloud export in the code",
}

_KEY_RE = re.compile(r"^\s*(?:#\s*)?([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _example_keys() -> set[str]:
    """Collect every key of the template, active or commented out."""
    return set(_KEY_RE.findall(_EXAMPLE))


def _settings_env_names() -> set[str]:
    """Collect every environment name that `Settings` reads, aliases included."""
    names: set[str] = set()
    for name, field in Settings.model_fields.items():
        names.add(name.upper())
        alias = field.validation_alias
        if isinstance(alias, AliasChoices):
            names.update(str(c).upper() for c in alias.choices if isinstance(c, str))
        elif isinstance(alias, str):
            names.add(alias.upper())
    return names


def test_example_has_keys() -> None:
    assert len(_example_keys()) > 50


def test_every_documented_key_is_read_somewhere() -> None:
    """Every key of the template reaches a field, or is a listed exception."""
    unread = sorted(_example_keys() - _settings_env_names() - set(_NOT_READ_BY_THE_API))
    assert not unread, (
        "deploy/.env.example documents keys that app.settings.Settings does not read "
        f"(extra='ignore' drops them silently): {unread}"
    )


def test_webhook_allowlist_uses_the_canonical_name() -> None:
    """The template must name the allowlist the way the field is named."""
    assert re.search(r"^WEBHOOK_HOST_ALLOWLIST=", _EXAMPLE, re.MULTILINE)
    assert not re.search(r"^WEBHOOK_ALLOWLIST=", _EXAMPLE, re.MULTILINE)
