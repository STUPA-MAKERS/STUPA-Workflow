"""make_open_votes_secret: turn every open motion and election into a secret one.

The platform has no open vote any more (user decision 2026-11-05). A new motion or
election is always secret (``voting.service.secret_only``). This migration converts the
old open motions and elections, so that no stored row links a person to a choice.

For each such vote the upgrade:

1. writes a ``voted_marker`` for each ``ballot`` row (who voted, no choice),
2. writes a ``secret_ballot`` for each ``ballot`` row with a choice (the choice, no
   person), in random order, so that the row order does not follow the ballot order,
3. deletes the ``ballot`` rows,
4. sets ``secret`` to true in ``vote.config``.

The counts, the results and the "has voted" state stay the same. A delegated ballot
keeps the ``voter_sub`` of the delegator in its marker, as the secret cast path does.
A poll (``kind = 'poll'``) keeps its own secrecy and stays as it is. The audit entries
``vote_cast`` carry no choice, so they need no change.

A motion without the key ``secret`` is open (``VoteConfig`` default false). An election
without the key is secret (``ElectionConfig`` default true), so its ballots already
live in the secret tables.

The upgrade is idempotent: a second run finds no open vote. The downgrade does nothing,
because the link between a person and a choice is deleted and cannot come back. Only a
backup made before this revision still holds it.

Revision ID: d8a799699d0f
Revises: 4fd514277924
Create Date: 2026-11-05 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d8a799699d0f"
down_revision: str | None = "4fd514277924"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The open motions and elections: the votes whose ballots carry a person.
_OPEN = (
    "SELECT id FROM vote WHERE "
    "(kind = 'motion' AND COALESCE((config->>'secret')::boolean, false) = false) "
    "OR (kind = 'election' AND COALESCE((config->>'secret')::boolean, true) = false)"
)

_UPGRADE: tuple[str, ...] = (
    "INSERT INTO voted_marker (vote_id, voter_sub) "
    f"SELECT b.vote_id, b.voter_sub FROM ballot b WHERE b.vote_id IN ({_OPEN}) "
    "ON CONFLICT (vote_id, voter_sub) DO NOTHING",
    "INSERT INTO secret_ballot (vote_id, choice) "
    f"SELECT b.vote_id, b.choice FROM ballot b WHERE b.vote_id IN ({_OPEN}) "
    "AND b.choice IS NOT NULL ORDER BY random()",
    f"DELETE FROM ballot WHERE vote_id IN ({_OPEN})",
    "UPDATE vote SET config = jsonb_set(config, '{secret}', 'true'::jsonb, true) "
    f"WHERE id IN ({_OPEN})",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Keep the data: the deleted link between a person and a choice cannot come back."""
