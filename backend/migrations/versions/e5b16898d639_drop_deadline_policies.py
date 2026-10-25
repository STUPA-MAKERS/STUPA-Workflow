"""drop_deadline_policies: remove the "Fristen" deadline-policy feature from the data.

The named deadline policies of flow waiting states are gone from the code. This
revision removes what the database still holds of them.

1. Stored flow definitions (``transition`` rows and the ``flow`` snapshots in
   ``config_revision``) lose the ``deadlinePassed`` guard operator:

   * A leaf that, counting the ``not`` above it, requires the deadline to have
     passed is treated as satisfied, and its transition becomes manual
     (``automatic = false``). Such a transition ("Frist abgelaufen") no longer
     fires by itself, so a member moves the application by hand.
   * A leaf that requires the deadline not to have passed is treated as satisfied.
   * ``and``, ``or`` and ``not`` fold around the constants. A guard that folds to
     always-true becomes NULL. A guard without ``deadlinePassed`` stays as it is.

2. ``state.config`` and the snapshot states lose ``deadlinePolicyKey``.
3. ``webhook.events`` loses ``deadline_approaching`` and ``deadline_passed``.
4. The ``mail_template`` rows with key ``deadline_approaching`` and the
   ``notification_preference`` rows of kind ``deadline`` are deleted.
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
Revises: e029878bed05
Create Date: 2026-10-25 10:00:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "e5b16898d639"
down_revision: str | None = "e029878bed05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OP = "deadlinePassed"
_POLICY_KEY = "deadlinePolicyKey"
_COMBINATORS = frozenset({"and", "or", "not"})


class _Rewrite:
    """The state of one guard rewrite: whether a leaf required a passed deadline."""

    def __init__(self) -> None:
        self.requires_passed = False


def _has_op(node: Any) -> bool:
    if isinstance(node, dict):
        return _OP in node or any(_has_op(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_op(v) for v in node)
    return False


def _fold(node: Any, negated: bool, rw: _Rewrite) -> Any:
    """Return the folded node: a guard dict, or the constant True or False."""
    if not isinstance(node, dict) or len(node) != 1 or not _has_op(node):
        return node
    op_name, value = next(iter(node.items()))
    if op_name == _OP:
        if bool(value) != negated:
            rw.requires_passed = True
        # The constant that makes the leaf's effective condition hold.
        return not negated
    if op_name not in _COMBINATORS:
        return node
    children = value if isinstance(value, list) else [value]
    if op_name == "not":
        if len(children) != 1:
            return node
        child = _fold(children[0], not negated, rw)
        if isinstance(child, bool):
            return not child
        return {"not": child}
    absorbing = op_name == "or"
    kept: list[Any] = []
    for c in children:
        folded = _fold(c, negated, rw)
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

    Returns the new guard (None for always-true) and whether a leaf required the
    deadline to have passed, which makes the transition manual. A guard without the
    operator comes back unchanged.
    """
    if not _has_op(guard):
        return guard, False
    rw = _Rewrite()
    folded = _fold(guard, False, rw)
    if folded is True:
        return None, rw.requires_passed
    if folded is False:  # pragma: no cover - every leaf folds to its satisfied value
        msg = f"guard folds to never-true: {guard!r}"
        raise ValueError(msg)
    return folded, rw.requires_passed


def rewrite_transition(tr: dict[str, Any]) -> dict[str, Any]:
    """Return a snapshot transition without ``deadlinePassed`` in its guard."""
    guard, manual = rewrite_guard(tr.get("guard"))
    out = {**tr, "guard": guard}
    if manual:
        out["automatic"] = False
    return out


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
            "SELECT id, guard, automatic FROM transition "
            "WHERE strpos(guard::text, :op) > 0"
        ),
        {"op": _OP},
    ).fetchall()
    for tid, guard, automatic in rows:
        new_guard, manual = rewrite_guard(guard)
        conn.execute(
            sa.text(
                "UPDATE transition SET guard = CAST(:g AS jsonb), automatic = :a "
                "WHERE id = :id"
            ),
            {
                "g": None if new_guard is None else json.dumps(new_guard),
                "a": False if manual else automatic,
                "id": tid,
            },
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
    "DELETE FROM mail_template WHERE key = 'deadline_approaching'",
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
