"""drop_deadline_policies: remove the "Fristen" deadline-policy feature from the data.

The named deadline policies of flow waiting states are gone from the code. This
revision removes what the database still holds of them.

1. Stored flow definitions (``transition`` rows and the ``flow`` snapshots in
   ``config_revision``) lose the ``deadlinePassed`` guard operator:

   * Every leaf is treated as satisfied, counting the ``not`` above it: a leaf
     that requires the deadline to have passed and a leaf that requires it not
     to have passed both fold to true.
   * Every transition whose guard held the operator, in any polarity, becomes
     manual (``automatic = false``). A transition such as "Frist abgelaufen" then
     no longer fires by itself, and a member moves the application by hand. A
     folded "not passed" guard on an automatic transition would otherwise
     advance every waiting application at the first cron run after the deploy.
   * ``and``, ``or`` and ``not`` fold around the constants. A guard that folds to
     always-true becomes NULL. A transition without ``deadlinePassed`` stays as
     it is.

2. ``state.config`` and the snapshot states lose ``deadlinePolicyKey``.
3. ``webhook.events`` loses ``deadline_approaching`` and ``deadline_passed``.
4. The ``notification_preference`` rows of kind ``deadline`` are deleted. The
   ``mail_template`` row ``deadline_approaching`` is deleted only when no
   ``transition.actions`` names it as ``templateKey``, because a flow can send a
   template that exists only in the database.
5. The tables ``deadline`` and ``deadline_policy`` are dropped.

``config_revision`` is append-only through a trigger. The upgrade disables the
UPDATE trigger only around the snapshot rewrite, inside the migration
transaction, because a revert re-validates a snapshot and would reject a
``deadlinePassed`` guard.

**The data changes are one-way.** The downgrade recreates both tables empty with
their schema so that the chain round-trips. It does not restore the guards, the
``automatic`` flags, the state configs, the webhook events, the deleted rows or
the deadlines.

Revision ID: e5b16898d639
Revises: b7c41e9a2f53
Create Date: 2026-10-25 10:00:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "e5b16898d639"
down_revision: str | None = "b7c41e9a2f53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OP = "deadlinePassed"
_POLICY_KEY = "deadlinePolicyKey"
_COMBINATORS = frozenset({"and", "or", "not"})


def _has_op(node: Any) -> bool:
    if isinstance(node, dict):
        return _OP in node or any(_has_op(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_op(v) for v in node)
    return False


def _fold(node: Any, negated: bool) -> Any:
    """Return the folded node: a guard dict, or the constant True or False."""
    if not isinstance(node, dict) or len(node) != 1 or not _has_op(node):
        return node
    op_name, value = next(iter(node.items()))
    if op_name == _OP:
        # The constant that makes the leaf's effective condition hold.
        return not negated
    if op_name not in _COMBINATORS:
        return node
    children = value if isinstance(value, list) else [value]
    if op_name == "not":
        if len(children) != 1:
            return node
        child = _fold(children[0], not negated)
        if isinstance(child, bool):
            return not child
        return {"not": child}
    absorbing = op_name == "or"
    kept: list[Any] = []
    for c in children:
        folded = _fold(c, negated)
        if folded is absorbing:
            return absorbing
        if folded is not (not absorbing):
            kept.append(folded)
    if not kept:
        return not absorbing
    if len(kept) == 1:
        return kept[0]
    return {op_name: kept}


def rewrite_guard(guard: Any) -> tuple[Any, bool]:
    """Remove ``deadlinePassed`` from a guard.

    Returns the new guard (None for always-true) and whether the guard held the
    operator, which makes the transition manual. A guard without the operator comes
    back unchanged.
    """
    if not _has_op(guard):
        return guard, False
    folded = _fold(guard, False)
    if folded is True:
        return None, True
    if folded is False:  # pragma: no cover - every leaf folds to its satisfied value
        msg = f"guard folds to never-true: {guard!r}"
        raise ValueError(msg)
    return folded, True


def rewrite_transition(tr: dict[str, Any]) -> dict[str, Any]:
    """Return a snapshot transition without ``deadlinePassed`` in its guard.

    A transition without the operator comes back unchanged.
    """
    guard, touched = rewrite_guard(tr.get("guard"))
    if not touched:
        return tr
    return {**tr, "guard": guard, "automatic": False}


def rewrite_flow_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a ``flow`` snapshot without ``deadlinePassed`` and ``deadlinePolicyKey``."""
    out = dict(snapshot)
    states = snapshot.get("states")
    if isinstance(states, list):
        out["states"] = [
            {**s, "config": {k: v for k, v in s["config"].items() if k != _POLICY_KEY}}
            if isinstance(s, dict) and isinstance(s.get("config"), dict)
            else s
            for s in states
        ]
    transitions = snapshot.get("transitions")
    if isinstance(transitions, list):
        out["transitions"] = [
            rewrite_transition(t) if isinstance(t, dict) else t for t in transitions
        ]
    return out


def _rewrite_transitions(conn: sa.Connection) -> None:
    rows = conn.execute(
        sa.text(
            "SELECT id, guard FROM transition "
            "WHERE strpos(guard::text, :op) > 0"
        ),
        {"op": _OP},
    ).fetchall()
    for tid, guard in rows:
        new_guard, touched = rewrite_guard(guard)
        if not touched:
            continue
        conn.execute(
            sa.text(
                "UPDATE transition SET guard = CAST(:g AS jsonb), automatic = false "
                "WHERE id = :id"
            ),
            {"g": None if new_guard is None else json.dumps(new_guard), "id": tid},
        )


def _rewrite_snapshots(conn: sa.Connection) -> None:
    rows = conn.execute(
        sa.text(
            "SELECT id, snapshot FROM config_revision WHERE entity_type = 'flow' "
            "AND (strpos(snapshot::text, :op) > 0 OR strpos(snapshot::text, :key) > 0)"
        ),
        {"op": _OP, "key": _POLICY_KEY},
    ).fetchall()
    if not rows:
        return
    conn.execute(
        sa.text(
            "ALTER TABLE config_revision DISABLE TRIGGER trg_config_revision_no_update"
        )
    )
    for rid, snapshot in rows:
        conn.execute(
            sa.text(
                "UPDATE config_revision SET snapshot = CAST(:s AS jsonb) WHERE id = :id"
            ),
            {"s": json.dumps(rewrite_flow_snapshot(snapshot)), "id": rid},
        )
    conn.execute(
        sa.text(
            "ALTER TABLE config_revision ENABLE TRIGGER trg_config_revision_no_update"
        )
    )


_UPGRADE: tuple[str, ...] = (
    f"UPDATE state SET config = config - '{_POLICY_KEY}' "
    f"WHERE strpos(config::text, '{_POLICY_KEY}') > 0",
    "UPDATE webhook SET events = array_remove(array_remove(events, "
    "'deadline_approaching'), 'deadline_passed') "
    "WHERE events && ARRAY['deadline_approaching', 'deadline_passed']::text[]",
    "DELETE FROM mail_template WHERE key = 'deadline_approaching' AND NOT EXISTS "
    "(SELECT 1 FROM transition WHERE actions @> "
    "'[{\"templateKey\": \"deadline_approaching\"}]'::jsonb OR actions @> "
    "'[{\"template_key\": \"deadline_approaching\"}]'::jsonb)",
    "DELETE FROM notification_preference WHERE kind = 'deadline'",
    "DROP TABLE IF EXISTS deadline",
    "DROP TABLE IF EXISTS deadline_policy",
)

# Structure only: the rows and the rewritten flow data do not come back.
_DOWNGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS deadline_policy (
        key text NOT NULL,
        label jsonb NOT NULL,
        kind text NOT NULL,
        absolute_at timestamptz,
        offset_days integer,
        at_time text,
        timezone text,
        dates jsonb,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        id uuid NOT NULL DEFAULT gen_random_uuid(),
        CONSTRAINT pk_deadline_policy PRIMARY KEY (id),
        CONSTRAINT uq_deadline_policy_key UNIQUE (key),
        CONSTRAINT ck_deadline_policy_deadline_policy_kind CHECK (kind IN
            ('absolute','relative_submitted','relative_changed','recurring')),
        CONSTRAINT deadline_policy_kind CHECK (kind IN
            ('absolute','relative_submitted','relative_changed','recurring'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deadline (
        application_id uuid,
        type_id uuid,
        kind text NOT NULL,
        due_at timestamptz NOT NULL,
        action_on_pass jsonb,
        reminded_at timestamptz,
        id uuid NOT NULL DEFAULT gen_random_uuid(),
        CONSTRAINT pk_deadline PRIMARY KEY (id),
        CONSTRAINT fk_deadline_application_id_application FOREIGN KEY
            (application_id) REFERENCES application (id) ON DELETE CASCADE,
        CONSTRAINT fk_deadline_type_id_application_type FOREIGN KEY
            (type_id) REFERENCES application_type (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_deadline_due_at_action ON deadline (due_at) "
    "WHERE action_on_pass IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_deadline_reminder ON deadline (due_at) "
    "WHERE reminded_at IS NULL",
)


def upgrade() -> None:
    conn = op.get_bind()
    _rewrite_transitions(conn)
    _rewrite_snapshots(conn)
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
