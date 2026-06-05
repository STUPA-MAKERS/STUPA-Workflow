"""Pure Guard-/Action-Evaluator für die Flow-Engine (flows §9.2, data-model §5.2).

Guards entscheiden, ob ein Übergang feuern darf. **Deklarativ, Whitelist, kein
`eval`.** Operatoren: ``roleIs permissionIs fieldsComplete voteResult
deadlinePassed manual`` kombiniert via ``and/or/not``. Actions sind ein Typ aus
der Whitelist (Dispatch passiert in der Engine, T-14 — hier nur Validierung).

Unbekannter Operator/Action-Typ → `GuardError` **beim Speichern** der Flow-Version
(nicht erst zur Laufzeit), siehe `validate_guard` / `validate_action`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Whitelist Guard-Operatoren (Blätter) + Kombinatoren.
GUARD_LEAF_OPERATORS: frozenset[str] = frozenset(
    {"roleIs", "permissionIs", "fieldsComplete", "voteResult", "deadlinePassed", "manual"}
)
GUARD_COMBINATORS: frozenset[str] = frozenset({"and", "or", "not"})
GUARD_OPERATORS: frozenset[str] = GUARD_LEAF_OPERATORS | GUARD_COMBINATORS

# Whitelist Action-Typen (Dispatch in der Engine, T-14).
ACTION_TYPES: frozenset[str] = frozenset(
    {
        "notify",
        "webhook",
        "exportPdf",
        "setEditLock",
        "budgetReserve",
        "budgetBook",
        "openVote",
        "requeue",
    }
)

# Gültige `voteResult`-Werte.
VOTE_RESULTS: frozenset[str] = frozenset({"passed", "rejected", "tie"})


class GuardError(Exception):
    """Ungültiger Guard (unbekannter Operator, falsche Struktur, …)."""


@dataclass(frozen=True)
class GuardContext:
    """Laufzeit-Kontext für `eval_guard` (flows §9.2). Pure Eingabe, kein I/O."""

    roles: frozenset[str] = frozenset()
    permissions: frozenset[str] = frozenset()
    fields_complete: bool = False
    vote_result: str | None = None
    deadline_passed: bool = False
    manual: bool = True


def _eval_leaf(op: str, value: Any, ctx: GuardContext) -> bool:
    if op == "roleIs":
        return value in ctx.roles
    if op == "permissionIs":
        return value in ctx.permissions
    if op == "fieldsComplete":
        return ctx.fields_complete == bool(value)
    if op == "voteResult":
        if value not in VOTE_RESULTS:
            raise GuardError(f"invalid voteResult value: {value!r}")
        return ctx.vote_result == value
    if op == "deadlinePassed":
        return ctx.deadline_passed == bool(value)
    if op == "manual":
        # Manueller Übergang: Gate ist die manuelle Auslösung selbst.
        return ctx.manual == bool(value)
    raise GuardError(f"unknown guard operator: {op!r}")  # pragma: no cover


def eval_guard(guard: dict[str, Any] | None, ctx: GuardContext) -> bool:
    """Guard gegen `ctx` auswerten → bool. Leerer/None-Guard ⇒ True (kein Gate)."""
    if not guard:
        return True
    if len(guard) != 1:
        raise GuardError(f"guard must have exactly one operator, got {list(guard)}")
    op, value = next(iter(guard.items()))

    if op == "and":
        return all(eval_guard(g, ctx) for g in _children(op, value))
    if op == "or":
        return any(eval_guard(g, ctx) for g in _children(op, value))
    if op == "not":
        children = _children(op, value)
        if len(children) != 1:
            raise GuardError("'not' requires exactly one child guard")
        return not eval_guard(children[0], ctx)
    if op in GUARD_LEAF_OPERATORS:
        return _eval_leaf(op, value, ctx)
    raise GuardError(f"unknown guard operator: {op!r}")


def _children(op: str, value: Any) -> list[dict[str, Any]]:
    children = value if isinstance(value, list) else [value]
    for c in children:
        if not isinstance(c, dict):
            raise GuardError(f"'{op}' children must be guard objects, got {c!r}")
    return children


def validate_guard(guard: dict[str, Any] | None) -> None:
    """Statisch prüfen: nur Whitelist-Operatoren, korrekte Struktur (Speicher-Gate)."""
    if not guard:
        return
    if len(guard) != 1:
        raise GuardError(f"guard must have exactly one operator, got {list(guard)}")
    op, value = next(iter(guard.items()))
    if op in GUARD_COMBINATORS:
        children = _children(op, value)
        if op == "not" and len(children) != 1:
            raise GuardError("'not' requires exactly one child guard")
        if op in {"and", "or"} and not children:
            raise GuardError(f"'{op}' requires at least one child guard")
        for c in children:
            validate_guard(c)
        return
    if op not in GUARD_LEAF_OPERATORS:
        raise GuardError(f"unknown guard operator: {op!r}")
    if op == "voteResult" and value not in VOTE_RESULTS:
        raise GuardError(f"invalid voteResult value: {value!r}")


def validate_action(action: dict[str, Any]) -> None:
    """Statisch prüfen, dass `action.type` in der Whitelist liegt (Speicher-Gate)."""
    if not isinstance(action, dict):
        raise GuardError(f"action must be an object, got {type(action).__name__}")
    action_type = action.get("type")
    if action_type is None:
        raise GuardError("action is missing 'type'")
    if action_type not in ACTION_TYPES:
        raise GuardError(f"unknown action type: {action_type!r}")
