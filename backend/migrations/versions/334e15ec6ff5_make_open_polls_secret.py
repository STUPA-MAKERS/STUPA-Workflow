"""make_open_polls_secret: turn every open poll into a secret one.

Every vote is secret, a poll too (user decision 2026-11-05). A new poll is always
secret (``voting.service.secret_only``). This migration converts the old open polls,
so that no stored row links a person to an answer. Revision ``d8a799699d0f`` did the
same for the motions and elections.

For each open poll the upgrade:

1. writes a ``voted_marker`` for each ``ballot`` row (who answered, no answer),
2. writes a ``secret_ballot`` for each ``ballot`` row with a choice (the answer, no
   person), in random order, so that the row order does not follow the ballot order,
3. deletes the ``ballot`` rows,
4. sets ``secret`` to true in ``vote.config``.

The counts, the stored ``poll_result`` and the "has answered" state stay the same. A
delegated ballot keeps the ``voter_sub`` of the delegator in its marker, as the secret
cast path does. A poll without the key ``secret`` is open (``PollConfig`` default
false).

The upgrade is idempotent: a second run finds no open poll. The downgrade does nothing,
because the link between a person and an answer is deleted and cannot come back. Only
a backup made before this revision still holds it.

Revision ID: 334e15ec6ff5
Revises: d8a799699d0f
Create Date: 2026-11-05 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "334e15ec6ff5"
down_revision: str | None = "d8a799699d0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The open polls: the polls whose ballots carry a person.
_OPEN = (
    "SELECT id FROM vote WHERE "
    "kind = 'poll' AND COALESCE((config->>'secret')::boolean, false) = false"
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
    """Keep the data: the deleted link between a person and an answer cannot come back."""
