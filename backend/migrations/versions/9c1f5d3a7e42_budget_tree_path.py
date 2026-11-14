"""Haushalt: the path key has one hyphen, and the tree path keeps the place in the tree.

``budget`` gets ``tree_path``, the keys from the top level down with ``-`` between
them, which is the form that ``path_key`` had. ``path_key`` takes the form that a
person reads: the key of the top level, one hyphen, then the keys of each level with
nothing between them (``VSM-801-33`` becomes ``VSM-80133``, spec 000878). The lines
of a decided plan keep a copy of the path key and take the new form too.

The upgrade stops before it changes a row when two cost centers would get one path
key, because the unique constraint would stop it later with no name of the rows.

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001), because the model sits in ``app.models``.

Revision ID: 9c1f5d3a7e42
Revises: 4b8e2f6c1a93
Create Date: 2026-11-14 00:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "9c1f5d3a7e42"
down_revision: str | None = "4b8e2f6c1a93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ONE_HYPHEN = (
    "split_part({col}, '-', 1) || CASE WHEN position('-' in {col}) > 0 "
    "THEN '-' || replace(substr({col}, position('-' in {col}) + 1), '-', '') ELSE '' END"
)


def upgrade() -> None:
    """Add the tree path and give each path key the form with one hyphen."""
    op.execute("ALTER TABLE budget ADD COLUMN IF NOT EXISTS tree_path text")
    op.execute("UPDATE budget SET tree_path = path_key WHERE tree_path IS NULL")
    new_key = _ONE_HYPHEN.format(col="tree_path")
    clashes = (
        op.get_bind()
        .execute(
            text(
                f"SELECT {new_key} AS path, string_agg(tree_path, ', ' ORDER BY tree_path) "
                "FROM budget GROUP BY 1 HAVING count(*) > 1 ORDER BY 1"
            )
        )
        .all()
    )
    if clashes:
        named = "; ".join(f"{path} for {paths}" for path, paths in clashes)
        message = f"Cost centers would share a path key. Give one a new key first: {named}"
        raise RuntimeError(message)
    op.execute(f"UPDATE budget SET path_key = {new_key}")
    op.execute(
        f"UPDATE budget_plan_line SET path_key = {_ONE_HYPHEN.format(col='path_key')} "
        "WHERE path_key IS NOT NULL"
    )
    op.execute("ALTER TABLE budget ALTER COLUMN tree_path SET NOT NULL")
    op.execute("ALTER TABLE budget DROP CONSTRAINT IF EXISTS uq_budget_tree_path")
    op.execute("ALTER TABLE budget ADD CONSTRAINT uq_budget_tree_path UNIQUE (tree_path)")


def downgrade() -> None:
    """Give each cost center the path key with a hyphen per level and drop the tree path.

    A line of a decided plan keeps the form with one hyphen, because the copy does
    not say where a level ends.
    """
    op.execute("UPDATE budget SET path_key = tree_path")
    op.execute("ALTER TABLE budget DROP CONSTRAINT IF EXISTS uq_budget_tree_path")
    op.execute("ALTER TABLE budget DROP COLUMN IF EXISTS tree_path")
