"""Pure guard/action evaluator for the flow engine.

Guards decide whether a transition may fire. Declarative, whitelist, NO `eval`.
The catalogue splits into:

* Conditions (auto + manual): ``deadlinePassed``, ``applicantRoleIs``,
  ``applicantCommitteeIs``, ``applicationTypeIs`` (application type key),
  ``attachmentPresent`` (>= 1 attachment), ``budgetIs``, ``budgetFitsApplication``,
  ``hasField``, ``compare`` (typed comparison over a promoted/form field) — combined
  via ``and``/``or``/``not``.
* Actor gates (manual transitions only): ``roleIs`` (global role), ``isInCommittee``
  (gremium membership). Forbidden on automatic transitions
  (``validate_guard(..., allow_actor_ops=False)``).

Actions are one whitelisted type (``webhook``/``notify``/``addToNextSession``/
``assignBudget``/``assignBudgetFromField``); dispatch happens in the engine — here only
validation. An unknown operator/action type raises ``GuardError`` when the flow version
is SAVED (not at runtime), see ``validate_guard`` / ``validate_action``.
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

# --------------------------------------------------------------------------- #
# Operator/action whitelists
# --------------------------------------------------------------------------- #
# Condition operators (auto + manual).
GUARD_CONDITION_OPERATORS: frozenset[str] = frozenset(
    {
        "deadlinePassed",
        "applicantRoleIs",
        "applicantCommitteeIs",
        "applicationTypeIs",
        "attachmentPresent",
        "budgetIs",
        "budgetFitsApplication",
        "hasField",
        "compare",
    }
)
# Actor gates — allowed on manual transitions only.
# ``actorIsApplicant``: the triggering actor is the applicant.
GUARD_ACTOR_OPERATORS: frozenset[str] = frozenset({"roleIs", "isInCommittee", "actorIsApplicant"})
GUARD_LEAF_OPERATORS: frozenset[str] = GUARD_CONDITION_OPERATORS | GUARD_ACTOR_OPERATORS
GUARD_COMBINATORS: frozenset[str] = frozenset({"and", "or", "not"})
GUARD_OPERATORS: frozenset[str] = GUARD_LEAF_OPERATORS | GUARD_COMBINATORS

# Comparison operators of the ``compare`` guard per value type.
_NUMERIC_OPS: frozenset[str] = frozenset({"==", "!=", "<", "<=", ">", ">="})
_DATE_OPS: frozenset[str] = _NUMERIC_OPS
_TEXT_OPS: frozenset[str] = frozenset({"==", "!=", "in"})
_BOOL_OPS: frozenset[str] = frozenset({"=="})

# Value types of a comparable field (derived from the form-field type).
COMPARE_TYPES: frozenset[str] = frozenset({"number", "currency", "date", "text", "bool"})

# Leaf operators with a string value (role/gremium/budget/field key) or bool value —
# for the save gate (``validate_guard``): a wrong value type (e.g. a list) would crash
# at runtime (unhashable in ``in frozenset``) instead of failing cleanly.
_STRING_VALUE_OPERATORS: frozenset[str] = frozenset(
    {
        "roleIs",
        "isInCommittee",
        "applicantRoleIs",
        "applicantCommitteeIs",
        "applicationTypeIs",
        "budgetIs",
        "hasField",
    }
)
_BOOL_VALUE_OPERATORS: frozenset[str] = frozenset(
    {"deadlinePassed", "budgetFitsApplication", "actorIsApplicant", "attachmentPresent"}
)

# Whitelisted action types (dispatch in the engine).
ACTION_TYPES: frozenset[str] = frozenset(
    {"webhook", "notify", "addToNextSession", "assignBudget", "assignBudgetFromField"}
)

# Required string field per action type (``notify`` is checked separately).
# ``assignBudgetFromField`` reads the cost-centre id from the named form field.
_ACTION_REQUIRED_FIELD: dict[str, str] = {
    "webhook": "webhookId",
    "addToNextSession": "gremiumId",
    "assignBudget": "budgetId",
    "assignBudgetFromField": "field",
}

# Valid ``notify`` recipient kinds.
NOTIFY_RECIPIENT_KINDS: frozenset[str] = frozenset({"gremium", "role", "applicant", "email"})


class GuardError(Exception):
    """Invalid guard (unknown operator, wrong structure, …)."""


@dataclass(frozen=True)
class GuardContext:
    """Runtime context for `eval_guard`. Pure input, no I/O.

    * ``manual`` — whether the transition is triggered manually (actor gates apply
      only here; in the automatic case ``roles``/``actor_committees`` are empty).
    * ``roles``/``actor_committees`` — the actor (triggering principal).
    * ``applicant_roles``/``applicant_committees`` — the applicant.
    * ``budget_id`` — assigned cost centre (budget tree) as a string.
    * ``budget_fits`` — amount <= remaining of the cost centre.
    * ``application_type_key`` — application type key (e.g. ``qsm``/``vsm``) for
      ``applicationTypeIs``; ``None`` when unresolvable (fail-closed).
    * ``has_attachment`` — at least one non-quarantined attachment on the application
      (for ``attachmentPresent``).
    * ``field_values``/``field_types`` — promoted/form field values + type (incl.
      built-in ``amount`` = ``currency``) for ``compare``/``hasField``.
    """

    manual: bool = True
    deadline_passed: bool = False
    # Actor is the applicant (logged-in creator or magic-link holder).
    actor_is_applicant: bool = False
    roles: frozenset[str] = frozenset()
    actor_committees: frozenset[str] = frozenset()
    applicant_roles: frozenset[str] = frozenset()
    applicant_committees: frozenset[str] = frozenset()
    budget_id: str | None = None
    budget_fits: bool = False
    application_type_key: str | None = None
    # At least one non-quarantined attachment is present on the application.
    has_attachment: bool = False
    field_values: Mapping[str, Any] = field(default_factory=dict)
    field_types: Mapping[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Type coercion + comparison (compare guard)
# --------------------------------------------------------------------------- #
def _to_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on", "ja"}
    return bool(value)


def ops_for_type(value_type: str) -> frozenset[str]:
    """Allowed ``compare`` operators for a value type (the FE mirrors this)."""
    if value_type in {"number", "currency"}:
        return _NUMERIC_OPS
    if value_type == "date":
        return _DATE_OPS
    if value_type == "bool":
        return _BOOL_OPS
    return _TEXT_OPS


def _eval_compare(spec: Any, ctx: GuardContext) -> bool:
    """Evaluate ``compare``: compare ``{field, op, value}`` per type.

    The value type comes from ``ctx.field_types[field]`` (default ``text``). A field
    missing from ``field_values`` -> ``False`` (fail-closed; implies ``hasField``)."""
    if not isinstance(spec, dict):
        raise GuardError("compare requires an object {field, op, value}")
    fld = spec.get("field")
    op = spec.get("op")
    operand = spec.get("value")
    if not isinstance(fld, str) or not fld:
        raise GuardError("compare.field must be a non-empty string")
    if not isinstance(op, str):
        raise GuardError("compare.op must be a string")
    value_type = ctx.field_types.get(fld, "text")
    if op not in ops_for_type(value_type):
        # The runtime type comes from the application's PINNED form version and can
        # differ from the globally stored flow (form drift, missing field -> ``text``).
        # Fail-closed instead of raising — otherwise a 500 for every transition.
        return False
    if fld not in ctx.field_values:
        return False
    left = ctx.field_values.get(fld)
    if left is None or (isinstance(left, str) and left == ""):
        return False

    if value_type in {"number", "currency"}:
        l_num, r_num = _to_decimal(left), _to_decimal(operand)
        if l_num is None or r_num is None:
            return False
        return _apply_ordered(op, l_num, r_num)
    if value_type == "date":
        l_d, r_d = _to_date(left), _to_date(operand)
        if l_d is None or r_d is None:
            return False
        return _apply_ordered(op, l_d, r_d)
    if value_type == "bool":
        return _to_bool(left) == _to_bool(operand)
    # text / select
    left_s = str(left)
    if op == "==":
        return left_s == str(operand)
    if op == "!=":
        return left_s != str(operand)
    if op == "in":
        return isinstance(operand, list) and left_s in [str(v) for v in operand]
    return False


# Ordered comparison operators -> ``operator`` function. Unknown operator -> ``False``
# (fail-closed; ``validate_guard`` rejects unknown operators at save time anyway).
_ORDERED_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


def _apply_ordered(op: str, left: Any, right: Any) -> bool:
    fn = _ORDERED_OPS.get(op)
    return fn(left, right) if fn is not None else False


# --------------------------------------------------------------------------- #
# Leaf evaluator
# --------------------------------------------------------------------------- #
def _has_field(value: Any, ctx: GuardContext) -> bool:
    """``hasField``: field present AND non-empty (None/""/[] count as missing)."""
    v = ctx.field_values.get(str(value))
    return v is not None and v != "" and v != []


# Leaf operator -> pure predicate ``(value, ctx) -> bool``. Actor gates apply only on
# manual transitions (automatic ones have empty ``roles``/``actor_committees``);
# ``compare`` values are compared per type in :func:`_eval_compare`.
_LEAF_EVALUATORS: dict[str, Callable[[Any, GuardContext], bool]] = {
    # Actor gates
    "roleIs": lambda value, ctx: value in ctx.roles,
    "isInCommittee": lambda value, ctx: str(value) in ctx.actor_committees,
    # ``true`` -> actor must be the applicant, ``false`` -> must not.
    "actorIsApplicant": lambda value, ctx: ctx.actor_is_applicant == bool(value),
    # Applicant
    "applicantRoleIs": lambda value, ctx: value in ctx.applicant_roles,
    "applicantCommitteeIs": lambda value, ctx: str(value) in ctx.applicant_committees,
    # Application type (key, e.g. ``qsm``/``vsm``) — fail-closed when unresolvable.
    "applicationTypeIs": lambda value, ctx: ctx.application_type_key is not None
    and str(value) == ctx.application_type_key,
    # Budget
    "budgetIs": lambda value, ctx: ctx.budget_id is not None and str(value) == ctx.budget_id,
    "budgetFitsApplication": lambda value, ctx: ctx.budget_fits == bool(value),
    # Attachments — ``true`` -> at least one attachment present, ``false`` -> none.
    "attachmentPresent": lambda value, ctx: ctx.has_attachment == bool(value),
    # Deadlines
    "deadlinePassed": lambda value, ctx: ctx.deadline_passed == bool(value),
    # Fields
    "hasField": _has_field,
    "compare": _eval_compare,
}


def _eval_leaf(op: str, value: Any, ctx: GuardContext) -> bool:
    evaluator = _LEAF_EVALUATORS.get(op)
    if evaluator is None:
        raise GuardError(f"unknown guard operator: {op!r}")  # pragma: no cover
    return evaluator(value, ctx)


def eval_guard(guard: dict[str, Any] | None, ctx: GuardContext) -> bool:
    """Evaluate a guard against `ctx` -> bool. Empty/None guard -> True (no gate)."""
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


def guard_requires_applicant(guard: dict[str, Any] | None) -> bool:
    """``True`` when the guard tree contains an ``actorIsApplicant`` gate anywhere.

    This lets us allow exactly the transitions an admin deliberately opened up to the
    applicant — a magic-link applicant may only fire such transitions."""
    if not isinstance(guard, dict) or len(guard) != 1:
        return False
    op, value = next(iter(guard.items()))
    if op == "actorIsApplicant":
        return True
    if op in GUARD_COMBINATORS:
        children = value if isinstance(value, list) else [value]
        return any(guard_requires_applicant(c) for c in children if isinstance(c, dict))
    return False


# --------------------------------------------------------------------------- #
# Static validation (save gate)
# --------------------------------------------------------------------------- #
def validate_guard(guard: dict[str, Any] | None, *, allow_actor_ops: bool = True) -> None:
    """Statically check: only whitelisted operators, correct structure (save gate).

    ``allow_actor_ops=False`` (automatic transitions) forbids ``roleIs``/
    ``isInCommittee`` — an actor gate without an actor makes no sense."""
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
            validate_guard(c, allow_actor_ops=allow_actor_ops)
        return
    if op not in GUARD_LEAF_OPERATORS:
        raise GuardError(f"unknown guard operator: {op!r}")
    if op in GUARD_ACTOR_OPERATORS and not allow_actor_ops:
        raise GuardError(f"actor gate {op!r} is only allowed on manual transitions")
    if op in _STRING_VALUE_OPERATORS and (not isinstance(value, str) or not value):
        raise GuardError(f"{op!r} requires a non-empty string value")
    if op in _BOOL_VALUE_OPERATORS and not isinstance(value, bool):
        raise GuardError(f"{op!r} requires a boolean value")
    if op == "compare":
        _validate_compare(value)


def _validate_compare(spec: Any) -> None:
    """Check the ``compare`` structure (the type is resolved from the field only at
    runtime; here just the shape + that ``op`` is a known comparison operator)."""
    if not isinstance(spec, dict):
        raise GuardError("compare requires an object {field, op, value}")
    fld = spec.get("field")
    op = spec.get("op")
    if not isinstance(fld, str) or not fld:
        raise GuardError("compare.field must be a non-empty string")
    if op not in (_NUMERIC_OPS | _TEXT_OPS):
        raise GuardError(f"unknown compare operator: {op!r}")
    if op == "in" and not isinstance(spec.get("value"), list):
        raise GuardError("compare operator 'in' requires a list value")


def validate_action(action: dict[str, Any]) -> None:
    """Statically check that `action.type` is whitelisted + required fields present.

    ``webhook`` needs ``webhookId``; ``notify`` a recipient list with valid kinds;
    ``addToNextSession`` a ``gremiumId`` (the target-state constraint is checked by the
    flow-graph validator, which knows the transition)."""
    if not isinstance(action, dict):
        raise GuardError(f"action must be an object, got {type(action).__name__}")
    action_type = action.get("type")
    if action_type is None:
        raise GuardError("action is missing 'type'")
    if action_type not in ACTION_TYPES:
        raise GuardError(f"unknown action type: {action_type!r}")
    if action_type == "notify":
        _validate_notify_recipients(action.get("recipients"))
        return
    # The remaining actions each require exactly one non-empty string field.
    field = _ACTION_REQUIRED_FIELD[action_type]
    if not isinstance(action.get(field), str) or not action[field]:
        raise GuardError(f"{action_type} action requires '{field}'")


def _validate_notify_recipients(recipients: Any) -> None:
    if not isinstance(recipients, list) or not recipients:
        raise GuardError("notify action requires a non-empty 'recipients' list")
    for r in recipients:
        if not isinstance(r, dict):
            raise GuardError("each notify recipient must be an object")
        kind = r.get("kind")
        if kind not in NOTIFY_RECIPIENT_KINDS:
            raise GuardError(f"unknown notify recipient kind: {kind!r}")
        if kind in {"gremium", "role", "email"} and not r.get("ref"):
            raise GuardError(f"notify recipient kind {kind!r} requires 'ref'")
        if kind == "applicant" and r.get("ref") is not None:
            raise GuardError("notify recipient kind 'applicant' must not have 'ref'")
