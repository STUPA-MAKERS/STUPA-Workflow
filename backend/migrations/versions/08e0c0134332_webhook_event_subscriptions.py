"""webhook_event_subscriptions: events, payload fields and filters per webhook.

``webhook`` gets ``subscriptions``, ``gremium_ids``, ``type_ids`` and ``state_keys``
(§F/integrations/webhooks/002410, 002412, 002414), all empty lists. ``webhook_delivery``
gets ``created_at``, which the worker cron that enqueues new deliveries reads.

The flow has no ``webhook`` action any more (§F/integrations/webhooks/002410). The upgrade
turns each ``webhook`` action of the active flow into a subscription: the named webhook
gets the event ``application.transition`` without fields and the status keys of the target
states of every transition that named it as ``state_keys``. It then removes the
``webhook`` actions from the transitions of every flow version.

Idempotent for the columns. A fresh database already has them from the ``create_all``
baseline (0001).

**The data change is one-way.** The downgrade drops the columns. It does not restore the
``webhook`` actions of the flow.

Revision ID: 08e0c0134332
Revises: 2e204b8ee6dd
Create Date: 2026-11-23 09:00:00
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "08e0c0134332"
down_revision: str | None = "2e204b8ee6dd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("subscriptions", "gremium_ids", "type_ids", "state_keys")


def upgrade() -> None:
    """Add the columns, move the flow actions into subscriptions and drop the actions."""
    for column in _COLUMNS:
        op.execute(
            f"ALTER TABLE webhook ADD COLUMN IF NOT EXISTS {column} jsonb NOT NULL DEFAULT '[]'"
        )
    op.execute(
        "ALTER TABLE webhook_delivery ADD COLUMN IF NOT EXISTS created_at "
        "timestamptz NOT NULL DEFAULT now()"
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT t.actions, s.key FROM transition t "
            "JOIN flow_version f ON f.id = t.flow_version_id "
            "JOIN state s ON s.id = t.to_state_id "
            "WHERE f.active"
        )
    ).all()
    keys: dict[str, set[str]] = defaultdict(set)
    for actions, state_key in rows:
        for action in actions or []:
            if isinstance(action, dict) and action.get("type") == "webhook":
                hook = action.get("webhookId")
                if isinstance(hook, str) and hook:
                    keys[hook].add(state_key)
    for hook, states in keys.items():
        bind.execute(
            sa.text(
                "UPDATE webhook SET subscriptions = CAST(:subs AS jsonb), "
                "state_keys = CAST(:states AS jsonb) WHERE CAST(id AS text) = :id"
            ),
            {
                "subs": json.dumps([{"event": "application.transition", "fields": []}]),
                "states": json.dumps(sorted(states)),
                "id": hook,
            },
        )
    op.execute(
        "UPDATE transition SET actions = COALESCE(("
        "SELECT jsonb_agg(e.a ORDER BY e.n) FROM jsonb_array_elements(actions) "
        "WITH ORDINALITY AS e(a, n) "
        "WHERE e.a->>'type' IS DISTINCT FROM 'webhook'), '[]'::jsonb) "
        'WHERE actions @> \'[{"type": "webhook"}]\'::jsonb'
    )


def downgrade() -> None:
    """Drop the new columns."""
    for column in _COLUMNS:
        op.execute(f"ALTER TABLE webhook DROP COLUMN IF EXISTS {column}")
    op.execute("ALTER TABLE webhook_delivery DROP COLUMN IF EXISTS created_at")
