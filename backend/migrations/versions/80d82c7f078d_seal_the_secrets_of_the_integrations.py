"""Seal the secrets of the integrations.

The upgrade seals each stored secret with the key of the settings
(§NF/security/integrity/002810, 002811): the IMAP and the SMTP password of a Postfach, the
Paperless token, the secret of a webhook, the private VAPID key and the calendar token of a
person. ``webhook.secret`` changes from ``bytea`` to sealed ``text``. The feed finds a person
by the new ``principal.calendar_token_hash`` (sha256 of the token), because a sealed token
differs at each write; its unique index replaces the one on ``calendar_token``.

The step is idempotent: a value that is already sealed stays, and a fresh database has the
new column and the text type from the baseline. The downgrade opens each value again.

Revision ID: 80d82c7f078d
Revises: e0dd72d776c9
Create Date: 2026-11-24 08:51:11.083922
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.shared.sealed import current_keyring, is_sealed, open_sealed, seal

revision: str = "80d82c7f078d"
down_revision: str | None = "e0dd72d776c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The text columns with a secret: (table, key column, secret column).
TEXT_SECRETS = (
    ("ticket_mailbox", "id", "imap_password"),
    ("ticket_mailbox", "id", "smtp_password"),
    ("paperless_settings", "id", "token"),
    ("push_vapid_key", "id", "private_pem"),
    ("principal", "id", "calendar_token"),
)


def _column_type(table: str, column: str) -> str:
    bind = op.get_bind()
    return bind.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar_one()


def _seal_text(table: str, key: str, column: str) -> None:
    bind = op.get_bind()
    ring = current_keyring()
    rows = bind.execute(
        sa.text(f"SELECT {key}, {column} FROM {table} WHERE {column} IS NOT NULL")
    ).all()
    for row_key, value in rows:
        if is_sealed(value):
            continue
        bind.execute(
            sa.text(f"UPDATE {table} SET {column} = :v WHERE {key} = :k"),
            {"v": seal(value.encode(), f"{table}.{column}", ring), "k": row_key},
        )


def _seal_webhook_secret() -> None:
    bind = op.get_bind()
    if _column_type("webhook", "secret") != "bytea":
        return
    rows = bind.execute(sa.text("SELECT id, secret FROM webhook WHERE secret IS NOT NULL")).all()
    op.execute("ALTER TABLE webhook ALTER COLUMN secret TYPE text USING NULL")
    ring = current_keyring()
    for row_id, secret in rows:
        bind.execute(
            sa.text("UPDATE webhook SET secret = :v WHERE id = :k"),
            {"v": seal(bytes(secret), "webhook.secret", ring), "k": row_id},
        )


def _hash_calendar_tokens() -> None:
    bind = op.get_bind()
    op.execute("ALTER TABLE principal ADD COLUMN IF NOT EXISTS calendar_token_hash TEXT")
    rows = bind.execute(
        sa.text("SELECT id, calendar_token FROM principal WHERE calendar_token IS NOT NULL")
    ).all()
    for row_id, token in rows:
        if is_sealed(token):
            continue
        bind.execute(
            sa.text("UPDATE principal SET calendar_token_hash = :h WHERE id = :k"),
            {"h": hashlib.sha256(token.encode()).hexdigest(), "k": row_id},
        )
    op.execute("DROP INDEX IF EXISTS uq_principal_calendar_token")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_principal_calendar_token_hash "
        "ON principal (calendar_token_hash)"
    )


def upgrade() -> None:
    """Hash the calendar tokens, then seal every stored secret."""
    _hash_calendar_tokens()
    for table, key, column in TEXT_SECRETS:
        _seal_text(table, key, column)
    _seal_webhook_secret()


def _open_text(table: str, key: str, column: str) -> None:
    bind = op.get_bind()
    ring = current_keyring()
    rows = bind.execute(
        sa.text(f"SELECT {key}, {column} FROM {table} WHERE {column} IS NOT NULL")
    ).all()
    for row_key, value in rows:
        if not is_sealed(value):
            continue
        plain = open_sealed(value, f"{table}.{column}", ring).decode()
        bind.execute(
            sa.text(f"UPDATE {table} SET {column} = :v WHERE {key} = :k"),
            {"v": plain, "k": row_key},
        )


def downgrade() -> None:
    """Open every sealed secret, and go back to the plain token index and ``bytea``."""
    bind = op.get_bind()
    ring = current_keyring()
    for table, key, column in TEXT_SECRETS:
        _open_text(table, key, column)
    rows = bind.execute(sa.text("SELECT id, secret FROM webhook WHERE secret IS NOT NULL")).all()
    op.execute("ALTER TABLE webhook ALTER COLUMN secret TYPE bytea USING NULL")
    for row_id, secret in rows:
        bind.execute(
            sa.text("UPDATE webhook SET secret = :v WHERE id = :k"),
            {"v": open_sealed(secret, "webhook.secret", ring), "k": row_id},
        )
    op.execute("DROP INDEX IF EXISTS uq_principal_calendar_token_hash")
    op.execute("ALTER TABLE principal DROP COLUMN IF EXISTS calendar_token_hash")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_principal_calendar_token "
        "ON principal (calendar_token)"
    )
