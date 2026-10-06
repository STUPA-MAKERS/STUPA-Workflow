"""Stored audit-chain checks (Z6/O8) and the role-key pre-check (A10).

The upgrade:

1. adds the table `audit_verification`: `started_at`, `finished_at`, `valid`,
   `checked`, `broken_at` (the id of the first broken `audit_entry` row, without a
   foreign key), `reason`, `trigger` and `triggered_by`. A CHECK limits `trigger` to
   `cron`, `manual` and `restore`, and `reason` to `prev_hash_mismatch` and
   `hash_mismatch`. A third CHECK binds `valid` to an empty `reason`. An index on
   `started_at DESC` serves the read of the newest check.
2. logs every `role.key` and every `gremium_role.key` that does not match
   `^[a-z][a-z0-9_]*$` (A10). It changes nothing. From now on the admin API rejects
   such a key on create with 422. An existing role keeps its key, because other rows
   and the OIDC group mappings point at it.

All steps are idempotent. A fresh database gets the table from the `create_all`
baseline (0001), because the model already declares it.

The downgrade drops the table. The pre-check has nothing to undo.

Revision ID: 373c9fe9cafb
Revises: 92f23ad77fc5
Create Date: 2026-10-02 17:59:05.597072
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "373c9fe9cafb"
down_revision: str | None = "92f23ad77fc5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_TABLE = "audit_verification"
_KEY_PATTERN = "^[a-z][a-z0-9_]*$"

_CREATE: tuple[str, ...] = (
    f"""
    CREATE TABLE IF NOT EXISTS {_TABLE} (
        id uuid DEFAULT gen_random_uuid() NOT NULL,
        started_at timestamptz NOT NULL,
        finished_at timestamptz,
        valid boolean NOT NULL,
        checked bigint NOT NULL,
        broken_at bigint,
        reason text,
        trigger text NOT NULL,
        triggered_by text,
        CONSTRAINT pk_{_TABLE} PRIMARY KEY (id),
        CONSTRAINT ck_{_TABLE}_trigger
            CHECK (trigger IN ('cron','manual','restore')),
        CONSTRAINT ck_{_TABLE}_reason
            CHECK (reason IS NULL OR reason IN ('prev_hash_mismatch','hash_mismatch')),
        CONSTRAINT ck_{_TABLE}_valid_reason CHECK (valid = (reason IS NULL))
    )
    """,
    f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_started_at ON {_TABLE} (started_at DESC)",
)


def _report_bad_role_keys() -> None:
    """Log the role keys that do not match the A10 pattern. Change nothing."""
    bind = op.get_bind()
    roles = bind.execute(
        sa.text("SELECT key FROM role WHERE key !~ :p ORDER BY key"), {"p": _KEY_PATTERN}
    ).scalars().all()
    gremium_roles = bind.execute(
        sa.text(
            "SELECT g.name, r.key FROM gremium_role r JOIN gremium g ON g.id = r.gremium_id "
            "WHERE r.key !~ :p ORDER BY g.name, r.key"
        ),
        {"p": _KEY_PATTERN},
    ).all()
    for key in roles:
        logger.warning("role key does not match %s: role %r", _KEY_PATTERN, key)
    for gremium, key in gremium_roles:
        logger.warning(
            "role key does not match %s: gremium role %r in gremium %r",
            _KEY_PATTERN,
            key,
            gremium,
        )
    logger.info(
        "role key check: %d role(s), %d gremium role(s) do not match %s",
        len(roles),
        len(gremium_roles),
        _KEY_PATTERN,
    )


def upgrade() -> None:
    for statement in _CREATE:
        op.execute(statement)
    _report_bad_role_keys()


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_TABLE}")
