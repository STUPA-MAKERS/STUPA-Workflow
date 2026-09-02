"""Drop ``render_job``: applications no longer render a PDF.

The table had one producer and one consumer, both in the application-PDF path, and both
are gone. Protocols render through pytex directly and never used it.

The stored objects live under the ``pdf/`` prefix of the attachment bucket and are NOT
removed here — a migration has no MinIO credentials. ``scripts/drop_application_pdfs.py``
clears them, and the deployment notes say to run it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3f1e59d84"
down_revision: str | None = "e5d02c8a41f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS render_job")


def downgrade() -> None:
    """Recreate the shell of the table. The rows are gone for good."""
    op.create_table(
        "render_job",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False, server_default="application_pdf"),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True, unique=True),
    )
