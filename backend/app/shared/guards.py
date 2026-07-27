"""Pure guard and action evaluator for the flow engine.

A guard decides if a transition can fire. The evaluator is declarative and works from a
whitelist. It never calls `eval`.

The catalog splits into conditions and actor gates. Conditions apply to automatic and
manual transitions: `deadlinePassed`, `applicantRoleIs`, `applicantCommitteeIs`,
`applicationTypeIs` (the application type key), `attachmentPresent` (one attachment or
more), `budgetIs`, `budgetFitsApplication`, `hasField`. `compare` adds a typed
comparison over a promoted or form field. The combinators `and`, `or` and `not` join
conditions.

Actor gates apply to manual transitions only: `roleIs` (a global role) and
`isInCommittee` (Gremium membership). `validate_guard(..., allow_actor_ops=False)`
forbids them on automatic transitions.

An action has one whitelisted type: `webhook`, `notify`, `addToNextSession`,
`assignBudget` or `assignBudgetFromField`. The engine dispatches the action. This module
only validates it. An unknown operator or action type raises `GuardError` when the flow
version is SAVED, not at runtime. See `validate_guard` and `validate_action`.
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

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
# Actor gates apply to manual transitions only. `actorIsApplicant` is true when the
# actor that triggers the transition is the applicant.
GUARD_ACTOR_OPERATORS: frozenset[str] = frozenset({"roleIs", "isInCommittee", "actorIsApplicant"})
GUARD_LEAF_OPERATORS: frozenset[str] = GUARD_CONDITION_OPERATORS | GUARD_ACTOR_OPERATORS
GUARD_COMBINATORS: frozenset[str] = frozenset({"and", "or", "not"})
GUARD_OPERATORS: frozenset[str] = GUARD_LEAF_OPERATORS | GUARD_COMBINATORS

# Comparison operators of the `compare` guard, per value type.
_NUMERIC_OPS: frozenset[str] = frozenset({"==", "!=", "<", "<=", ">", ">="})
_DATE_OPS: frozenset[str] = _NUMERIC_OPS
_TEXT_OPS: frozenset[str] = frozenset({"==", "!=", "in"})
_BOOL_OPS: frozenset[str] = frozenset({"=="})

# Value types of a comparable field. They come from the form-field type.
COMPARE_TYPES: frozenset[str] = frozenset({"number", "currency", "date", "text", "bool"})

# Leaf operators with a string value, such as a role, Gremium, budget or field key, or
# with a bool value. The save gate `validate_guard` checks them. A wrong value type such
# as a list crashes at runtime as unhashable in `in frozenset` instead of failing
# cleanly.
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

ACTION_TYPES: frozenset[str] = frozenset(
    {"webhook", "notify", "addToNextSession", "assignBudget", "assignBudgetFromField"}
)

# Required string field per action type. `notify` has a separate check.
# `assignBudgetFromField` reads the cost center id from the named form field.
_ACTION_REQUIRED_FIELD: dict[str, str] = {
    "webhook": "webhookId",
    "addToNextSession": "gremiumId",
    "assignBudget": "budgetId",
    "assignBudgetFromField": "field",
}

NOTIFY_RECIPIENT_KINDS: frozenset[str] = frozenset({"gremium", "role", "applicant", "email"})


class GuardError(Exception):
    """Invalid guard, for example an unknown operator or a wrong structure."""


@dataclass(frozen=True)
class GuardContext:
    """Runtime context for `eval_guard`.

    The context is pure input. The evaluator does no I/O.

    Attributes:
        manual: True when an actor triggers the transition by hand. Actor gates apply
            only here. An automatic transition has empty `roles` and
            `actor_committees`.
        actor_is_applicant: True when the actor is the applicant. The applicant is the
            logged-in creator or the holder of the magic link.
        roles: The roles of the actor, which is the triggering principal.
        actor_committees: The Gremien of the actor.
        applicant_roles: The roles of the applicant.
        applicant_committees: The Gremien of the applicant.
        budget_id: The assigned cost center of the budget tree, as a string.
        budget_fits: True when the amount is at most the remaining sum of the cost
            center.
        application_type_key: The application type key, for example `qsm` or `vsm`. It
            serves `applicationTypeIs`. `None` when the key does not resolve, which
            fails closed.
        has_attachment: True when the application carries at least one attachment that
            is not in quarantine. It serves `attachmentPresent`.
        field_values: The promoted and form field values for `compare` and `hasField`.
        field_types: The type of each field, including the built-in `amount` of type
            `currency`.
    """

    manual: bool = True
    deadline_passed: bool = False
    actor_is_applicant: bool = False
    roles: frozenset[str] = frozenset()
    actor_committees: frozenset[str] = frozenset()
    applicant_roles: frozenset[str] = frozenset()
    applicant_committees: frozenset[str] = frozenset()
    budget_id: str | None = None
    budget_fits: bool = False
    application_type_key: str | None = None
    has_attachment: bool = False
    field_values: Mapping[str, Any] = field(default_factory=dict)
    field_types: Mapping[str, str] = field(default_factory=dict)


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
    """Return the allowed `compare` operators for a value type.

    The frontend mirrors this mapping.
    """
    if value_type in {"number", "currency"}:
        return _NUMERIC_OPS
    if value_type == "date":
        return _DATE_OPS
    if value_type == "bool":
        return _BOOL_OPS
    return _TEXT_OPS


def _eval_compare(spec: Any, ctx: GuardContext) -> bool:
    """Evaluate the `compare` guard over `{field, op, value}` per type.

    The value type comes from `ctx.field_types[field]` and defaults to `text`. A field
    that is missing from `field_values` gives `False`. That fails closed and implies
    `hasField`.
    """
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
        # The runtime type comes from the PINNED form version of the application. It can
        # differ from the globally stored flow through form drift. A missing field gives
        # `text`. Fail closed instead of raising, or every transition returns a 500.
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
    # Fall-through for the text and select types.
    left_s = str(left)
    if op == "==":
        return left_s == str(operand)
    if op == "!=":
        return left_s != str(operand)
    if op == "in":
        return isinstance(operand, list) and left_s in [str(v) for v in operand]
    return False


# Map an ordered comparison operator to its `operator` function. An unknown operator
# gives `False` and fails closed. `validate_guard` rejects an unknown operator at save
# time anyway.
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


def _has_field(value: Any, ctx: GuardContext) -> bool:
    """Evaluate `hasField`: the field is present and not empty.

    A value of `None`, an empty string or an empty list counts as missing.
    """
    v = ctx.field_values.get(str(value))
    return v is not None and v != "" and v != []


# Map a leaf operator to a pure predicate `(value, ctx) -> bool`. Actor gates apply only
# on manual transitions. An automatic transition has empty `roles` and
# `actor_committees`. `_eval_compare` compares a `compare` value per type.
_LEAF_EVALUATORS: dict[str, Callable[[Any, GuardContext], bool]] = {
    "roleIs": lambda value, ctx: value in ctx.roles,
    "isInCommittee": lambda value, ctx: str(value) in ctx.actor_committees,
    "actorIsApplicant": lambda value, ctx: ctx.actor_is_applicant == bool(value),
    "applicantRoleIs": lambda value, ctx: value in ctx.applicant_roles,
    "applicantCommitteeIs": lambda value, ctx: str(value) in ctx.applicant_committees,
    "applicationTypeIs": lambda value, ctx: ctx.application_type_key is not None
    and str(value) == ctx.application_type_key,
    "budgetIs": lambda value, ctx: ctx.budget_id is not None and str(value) == ctx.budget_id,
    "budgetFitsApplication": lambda value, ctx: ctx.budget_fits == bool(value),
    "attachmentPresent": lambda value, ctx: ctx.has_attachment == bool(value),
    "deadlinePassed": lambda value, ctx: ctx.deadline_passed == bool(value),
    "hasField": _has_field,
    "compare": _eval_compare,
}


def _eval_leaf(op: str, value: Any, ctx: GuardContext) -> bool:
    evaluator = _LEAF_EVALUATORS.get(op)
    if evaluator is None:
        raise GuardError(f"unknown guard operator: {op!r}")  # pragma: no cover
    return evaluator(value, ctx)


def eval_guard(guard: dict[str, Any] | None, ctx: GuardContext) -> bool:
    """Evaluate a guard against `ctx`.

    An empty guard or `None` returns `True` and adds no gate.

    Raises:
        GuardError: The guard uses an unknown operator or a wrong structure.
    """
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
    """Report whether the guard tree holds an `actorIsApplicant` gate anywhere.

    The caller allows exactly the transitions that an admin opened to the applicant. A
    magic-link applicant can fire only such a transition.
    """
    if not isinstance(guard, dict) or len(guard) != 1:
        return False
    op, value = next(iter(guard.items()))
    if op == "actorIsApplicant":
        return True
    if op in GUARD_COMBINATORS:
        children = value if isinstance(value, list) else [value]
        return any(guard_requires_applicant(c) for c in children if isinstance(c, dict))
    return False


def validate_guard(guard: dict[str, Any] | None, *, allow_actor_ops: bool = True) -> None:
    """Check the guard structure and reject every operator outside the whitelist.

    This is the save gate for a flow version.

    Pass `allow_actor_ops=False` for an automatic transition. That forbids `roleIs` and
    `isInCommittee`, because an actor gate without an actor makes no sense.

    Raises:
        GuardError: The guard uses an unknown operator, a forbidden actor gate, a wrong
            structure or a wrong value type.
    """
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
    """Check the shape of a `compare` guard.

    This function checks the structure and that `op` is a known comparison operator.
    The value type resolves from the field only at runtime.
    """
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
    """Check that `action.type` is whitelisted and that the required fields are present.

    `webhook` needs `webhookId`. `notify` needs a recipient list with valid kinds.
    `addToNextSession` needs a `gremiumId`. The flow-graph validator checks the
    target-state constraint, because it knows the transition.

    Raises:
        GuardError: The action type is unknown or a required field is missing.
    """
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
