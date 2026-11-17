"""The seeded subject of the magic-link mail names the platform by the branding (spec 001231).

The seed (0002) put a ``magic_link`` template into the database with a fixed name in the
subject. A template in the database wins over the builtin text, so every installation
sent "Antragsplattform" and not the app name of the branding. The upgrade replaces the
subject of each language with the builtin subject, which holds ``{{ platformName }}``,
only where the subject is still the exact seed text. A subject that an admin changed stays
as it is.

Idempotent: a second run finds no seed text. The downgrade puts back the seed text only
where the subject is still the builtin text.

Revision ID: 81852f245ccb
Revises: b7e2c4a91f03
Create Date: 2026-11-16 22:45:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "81852f245ccb"
down_revision: str | None = "b7e2c4a91f03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (language, seed subject, builtin subject). The builtin subjects match
#: ``_BUILTIN_MAGIC_LINK_SUBJECT`` in app/modules/notifications/service.py.
_SUBJECTS = (
    ("de", "Ihr Zugangslink zur Antragsplattform", "Ihr Zugangslink für {{ platformName }}"),
    (
        "en",
        "Your access link for the application platform",
        "Your access link for {{ platformName }}",
    ),
)

_REWRITE = """
UPDATE mail_template
SET subject_i18n = jsonb_set(subject_i18n, ARRAY[:lang], to_jsonb(CAST(:new AS text)))
WHERE key = 'magic_link' AND subject_i18n ->> :lang = :old
"""


def _rewrite(*, forward: bool) -> None:
    for lang, seed, builtin in _SUBJECTS:
        old, new = (seed, builtin) if forward else (builtin, seed)
        op.get_bind().execute(sa.text(_REWRITE), {"lang": lang, "old": old, "new": new})


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    _rewrite(forward=True)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    _rewrite(forward=False)
