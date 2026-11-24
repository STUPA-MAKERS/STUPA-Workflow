"""Paperless: the address for links.

The upgrade adds ``paperless_settings.public_url``, the optional field `Adresse für Links`
(§F/integrations/paperless/002844). Each browser link to Paperless names it, or the address
when it is NULL. The server never calls it.

The step is idempotent. A fresh database already gets the column from the ``create_all``
baseline (0001), because the models sit in ``app.models``.

Revision ID: f4a9c2d7e815
Revises: 80d82c7f078d
Create Date: 2026-11-24 14:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f4a9c2d7e815"
down_revision: str | None = "80d82c7f078d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the address for links."""
    op.execute("ALTER TABLE paperless_settings ADD COLUMN IF NOT EXISTS public_url TEXT")


def downgrade() -> None:
    """Drop the address for links."""
    op.execute("ALTER TABLE paperless_settings DROP COLUMN IF EXISTS public_url")
