"""ui_translations: the tables of the UI text overrides and the extra UI languages.

``ui_translation`` holds one override per locale and key; a missing row and a NULL
``value`` both mean the built-in text of the frontend. ``ui_language`` holds the
languages that an admin adds beside the built-in ``de`` and ``en``.

Idempotent. A fresh database already gets both tables from the ``create_all`` baseline
(0001), because both models sit in ``app.models``. A migrated database gets them through
``CREATE TABLE IF NOT EXISTS``.

The new permission ``admin.translations`` goes to no role. The ``admin`` role holds it
through the admin bypass.

Revision ID: b80a146809d4
Revises: e5b16898d639
Create Date: 2026-10-26 00:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b80a146809d4"
down_revision: str | None = "e5b16898d639"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS ui_language (
        code text PRIMARY KEY,
        name text NOT NULL,
        active boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        updated_by text,
        CONSTRAINT ck_ui_language_not_builtin CHECK (code NOT IN ('de', 'en')),
        CONSTRAINT ck_ui_language_code_length CHECK (length(code) BETWEEN 2 AND 16),
        CONSTRAINT ck_ui_language_name_length CHECK (length(name) BETWEEN 1 AND 64)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ui_translation (
        locale text NOT NULL,
        key text NOT NULL,
        value text,
        updated_at timestamptz NOT NULL DEFAULT now(),
        updated_by text,
        CONSTRAINT pk_ui_translation PRIMARY KEY (locale, key)
    )
    """,
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'admin.translations'",
    "DROP TABLE IF EXISTS ui_translation",
    "DROP TABLE IF EXISTS ui_language",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
