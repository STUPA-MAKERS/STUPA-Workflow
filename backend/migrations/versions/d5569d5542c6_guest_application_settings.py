"""Guest application settings and magic links without an expiry (Z1, O3).

The upgrade:

1. creates the single-row table `guest_application_settings` and inserts the row
   `(id=1, confirm_ttl_hours=12, link_ttl_days=NULL)`. NULL means that a new magic
   link has no expiry. The worker reads `confirm_ttl_hours` for the discard of
   unconfirmed applications. Both values replace environment settings
   (`MAGIC_LINK_EDIT_TTL_DAYS`, `MAGIC_LINK_ACTION_TTL_MINUTES`) and the fixed 12 h
   window of the worker.
2. makes `magic_link.expires_at` nullable and adds
   `CHECK (expires_at IS NOT NULL OR scope = 'edit')`. Only an edit link can live
   without an expiry. The existing links keep their expiry, so all of them satisfy
   the check.
3. rewrites the lifetime sentence of the `magic_link` mail template. The seed said
   that the link is valid for a limited time. By default a link now has no expiry,
   so the sentence becomes a neutral hint to keep the link private. The step
   replaces only that exact sentence. The rest of the text, and a text without the
   sentence, stays as it is.

All steps are idempotent. A fresh database gets the table and the check from the
`create_all` baseline (0001), because the models already declare them.

The downgrade gives every link without an expiry `now() + 7 days` (the old default
of `MAGIC_LINK_EDIT_TTL_DAYS`), restores NOT NULL, drops the check and the table, and
puts back the seed sentence of the mail template.

Revision ID: d5569d5542c6
Revises: eff772f93d8e
Create Date: 2026-10-01 17:13:50.986284
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5569d5542c6"
down_revision: str | None = "eff772f93d8e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS guest_application_settings (
    id integer NOT NULL DEFAULT 1,
    confirm_ttl_hours integer NOT NULL DEFAULT 12,
    link_ttl_days integer NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NULL,
    CONSTRAINT pk_guest_application_settings PRIMARY KEY (id),
    CONSTRAINT ck_guest_application_settings_singleton CHECK (id = 1),
    CONSTRAINT ck_guest_application_settings_confirm_ttl
        CHECK (confirm_ttl_hours BETWEEN 1 AND 720),
    CONSTRAINT ck_guest_application_settings_link_ttl
        CHECK (link_ttl_days IS NULL OR link_ttl_days > 0)
)
"""

_SEED = """
INSERT INTO guest_application_settings (id, confirm_ttl_hours, link_ttl_days)
VALUES (1, 12, NULL)
ON CONFLICT (id) DO NOTHING
"""

_CHECK = "ck_magic_link_magic_link_unlimited_edit_only"

# (old seed sentence, new sentence). The new sentences match the builtin fallback in
# app/modules/notifications/service.py.
_MAIL_SENTENCES = (
    (
        "Der Link ist zeitlich begrenzt gültig.",
        "Bewahren Sie den Link vertraulich auf. Er öffnet Ihren Antrag.",
    ),
    (
        "The link is valid for a limited time.",
        "Keep this link private. It opens your application.",
    ),
)

_REWRITE_MAIL = """
UPDATE mail_template
SET body_i18n = replace(body_i18n::text, :old, :new)::jsonb
WHERE key = 'magic_link' AND strpos(body_i18n::text, :old) > 0
"""


def _rewrite_mail(*, forward: bool) -> None:
    for old, new in _MAIL_SENTENCES:
        src, dst = (old, new) if forward else (new, old)
        op.get_bind().execute(sa.text(_REWRITE_MAIL), {"old": src, "new": dst})


def upgrade() -> None:
    op.execute(_CREATE_TABLE)
    op.execute(_SEED)
    op.execute("ALTER TABLE magic_link ALTER COLUMN expires_at DROP NOT NULL")
    op.execute(f"ALTER TABLE magic_link DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.execute(
        f"ALTER TABLE magic_link ADD CONSTRAINT {_CHECK} "
        "CHECK (expires_at IS NOT NULL OR scope = 'edit')"
    )
    _rewrite_mail(forward=True)


def downgrade() -> None:
    op.execute(
        "UPDATE magic_link SET expires_at = now() + interval '7 days' WHERE expires_at IS NULL"
    )
    op.execute(f"ALTER TABLE magic_link DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.execute("ALTER TABLE magic_link ALTER COLUMN expires_at SET NOT NULL")
    op.execute("DROP TABLE IF EXISTS guest_application_settings")
    _rewrite_mail(forward=False)
