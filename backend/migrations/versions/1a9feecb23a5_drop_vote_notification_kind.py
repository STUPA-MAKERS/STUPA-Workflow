"""Drop the dead notification kinds `vote` and `role_change` and the role mail templates.

No code path sends a mail of the kind `vote`. The role mails (`role_assigned`,
`role_revoked`, kind `role_change`) had no caller either: since the OIDC-only
memberships, no API route assigns or revokes a role. The settings page offered
switches for both kinds that changed nothing.

The upgrade:

1. deletes the `notification_preference` rows of the kinds `vote` and
   `role_change`. The table stores only deviations from the default, one row per
   principal and kind. A later save of the settings page therefore does not send
   the keys back, and the API refuses them (422).
2. logs and deletes the stored overrides of the mail templates `role_assigned` and
   `role_revoked`. The template catalogue no longer lists them.

The downgrade does nothing. The deleted rows were switches and texts for mails that
no code sends. The downgraded code treats a missing preference row as "on" and a
missing template override as the builtin text, so it runs without them.

Revision ID: 1a9feecb23a5
Revises: b0c8fd389e10
Create Date: 2026-09-30 19:58:31.851882
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1a9feecb23a5"
down_revision: str | None = "b0c8fd389e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_DROPPED_KINDS_SQL = "'vote', 'role_change'"
_DROPPED_TEMPLATES_SQL = "'role_assigned', 'role_revoked'"


def upgrade() -> None:
    bind = op.get_bind()
    prefs = bind.execute(
        sa.text(
            "DELETE FROM notification_preference "
            f"WHERE kind IN ({_DROPPED_KINDS_SQL}) RETURNING kind"
        )
    ).all()
    if prefs:
        logger.info(
            "deleted %d notification preference(s) of the kinds vote and role_change",
            len(prefs),
        )
    templates = bind.execute(
        sa.text(
            "DELETE FROM mail_template "
            f"WHERE key IN ({_DROPPED_TEMPLATES_SQL}) RETURNING key"
        )
    ).all()
    for (key,) in templates:
        logger.warning(
            "deleted the stored override of the mail template %r; no code sends it", key
        )


def downgrade() -> None:
    # Nothing to restore: see the module docstring.
    pass
