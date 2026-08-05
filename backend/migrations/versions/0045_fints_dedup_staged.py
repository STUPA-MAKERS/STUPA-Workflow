"""fints_dedup_staged: no-op — the FinTS feature is removed.

This revision was a data backfill for ``bank_statement_line``. That table (and
the whole FinTS/Konten feature) is dropped in
``b7c41d2e9f38_drop_fints_and_accounts``, so the backfill has no target any
more. The revision id stays in the chain: databases that already ran it keep a
valid ``alembic_version``, and a fresh database walks past it.

The body is empty on purpose. The original code imported
``app.modules.budget.bank``, which no longer exists — leaving the import in
place would break ``alembic upgrade head``.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0045_fints_dedup_staged"
down_revision: str | None = "0044_fints_purpose_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op — see the module docstring."""


def downgrade() -> None:
    """No-op — see the module docstring."""
