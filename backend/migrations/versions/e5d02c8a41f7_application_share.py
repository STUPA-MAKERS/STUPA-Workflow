"""application_share: revocable public read-only links to one application.

The table holds ``HMAC-SHA256(pepper, token)`` and never the plaintext, like
``magic_link``. A link expires and can be revoked, because a URL that has been pasted
into a chat is outside our control and the only way to take it back is to stop honouring
it.

Not single-use, unlike a magic link: several people are meant to open it, often more than
once.

Idempotent. A fresh database already gets the table from the ``create_all`` baseline
(0001), because ``ApplicationShare`` sits in ``app.models``; a migrated database gets it
through ``CREATE TABLE IF NOT EXISTS``.

The revision also grants ``application.share`` to the ``admin`` role. Creating a public
link is a decision about the committee's record, so it is its own key rather than part of
``application.read``: someone reading through a magic link may view an application and
must not be able to publish it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e5d02c8a41f7"
down_revision: str | None = "c4a91e77b2d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS application_share (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        application_id uuid NOT NULL
            REFERENCES application (id) ON DELETE CASCADE,
        token_hash bytea NOT NULL,
        expires_at timestamptz NOT NULL,
        revoked_at timestamptz,
        created_by text,
        label text
    )
    """,
    # UNIQUE: the lookup is by hash, and two rows with the same digest would make the
    # answer ambiguous at exactly the moment it must not be.
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_application_share_token_hash "
        "ON application_share (token_hash)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_application_share_application_id "
        "ON application_share (application_id)"
    ),
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'application.share' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'application.share'",
    "DROP TABLE IF EXISTS application_share",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
