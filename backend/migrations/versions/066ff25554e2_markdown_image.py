"""markdown_image: the uploaded images of the Markdown texts.

One row per image that a protocol, a to-do card or a chat message refers to as
``/api/media/images/<id>``. The bytes live in the attachment bucket under
``media/images/<id>``. The table has no uploader column, so the image is no part of
the account merge or the erasure.

Idempotent. A fresh database already gets the table from the ``create_all`` baseline
(0001), because ``MarkdownImage`` sits in ``app.models``. A migrated database gets it
through ``CREATE TABLE IF NOT EXISTS``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "066ff25554e2"
down_revision: str | None = "e7eeac24423f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS markdown_image (
        id uuid NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        storage_key text NOT NULL,
        mime text NOT NULL,
        size bigint NOT NULL,
        width integer NOT NULL,
        height integer NOT NULL,
        CONSTRAINT pk_markdown_image PRIMARY KEY (id),
        CONSTRAINT ck_markdown_image_mime
            CHECK (mime IN ('image/png', 'image/jpeg', 'image/gif', 'image/webp')),
        CONSTRAINT ck_markdown_image_size CHECK (size >= 0),
        CONSTRAINT ck_markdown_image_dimensions CHECK (width > 0 AND height > 0)
    )
    """,
)

_DOWNGRADE: tuple[str, ...] = ("DROP TABLE IF EXISTS markdown_image",)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
