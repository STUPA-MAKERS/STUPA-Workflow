"""Pure Guard-/Action-Evaluator für die Flow-Engine (flows §9.2, data-model §5.2).

Guards entscheiden, ob ein Übergang feuern darf. **Deklarativ, Whitelist, kein
`eval`.** Der Katalog (#28-Redesign) trennt:

* **Bedingungen** (auto + manuell): ``deadlinePassed``, ``applicantRoleIs``,
  ``applicantCommitteeIs``, ``budgetIs``, ``budgetFitsApplication``, ``hasField``,
  ``compare`` (typisierter Vergleich über ein Promoted-/Formularfeld) — kombiniert
  via ``and``/``or``/``not``.
* **Akteur-Gates** (nur **manuelle** Übergänge): ``roleIs`` (globale Rolle),
  ``isInCommittee`` (Mitgliedschaft im Gremium). Auf automatischen Übergängen
  verboten (``validate_guard(..., allow_actor_ops=False)``).

Actions sind ein Typ aus der Whitelist (``webhook``/``notify``/``addToNextSession``);
Dispatch passiert in der Engine (T-14) — hier nur Validierung.

Unbekannter Operator/Action-Typ → ``GuardError`` **beim Speichern** der Flow-Version
(nicht erst zur Laufzeit), siehe ``validate_guard`` / ``validate_action``.
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

# --------------------------------------------------------------------------- #
# Operator-/Action-Whitelists
# --------------------------------------------------------------------------- #
# Bedingungs-Operatoren (auto + manuell).
GUARD_CONDITION_OPERATORS: frozenset[str] = frozenset(
    {
        "deadlinePassed",
        "applicantRoleIs",
        "applicantCommitteeIs",
        "budgetIs",
        "budgetFitsApplication",
        "hasField",
        "compare",
    }
)
# Akteur-Gates — nur auf **manuellen** Übergängen zulässig.
# ``actorIsApplicant``: der auslösende Akteur ist der/die Antragsteller:in (#guard).
GUARD_ACTOR_OPERATORS: frozenset[str] = frozenset({"roleIs", "isInCommittee", "actorIsApplicant"})
GUARD_LEAF_OPERATORS: frozenset[str] = GUARD_CONDITION_OPERATORS | GUARD_ACTOR_OPERATORS
GUARD_COMBINATORS: frozenset[str] = frozenset({"and", "or", "not"})
GUARD_OPERATORS: frozenset[str] = GUARD_LEAF_OPERATORS | GUARD_COMBINATORS

# Vergleichs-Operatoren des ``compare``-Guards je Wert-Typ.
_NUMERIC_OPS: frozenset[str] = frozenset({"==", "!=", "<", "<=", ">", ">="})
_DATE_OPS: frozenset[str] = _NUMERIC_OPS
_TEXT_OPS: frozenset[str] = frozenset({"==", "!=", "in"})
_BOOL_OPS: frozenset[str] = frozenset({"=="})

# Wert-Typen eines vergleichbaren Feldes (abgeleitet aus dem Formularfeld-Typ).
COMPARE_TYPES: frozenset[str] = frozenset({"number", "currency", "date", "text", "bool"})

# Leaf-Operatoren mit String-Wert (Rolle/Gremium/Budget/Feld-Key) bzw. Bool-Wert —
# fürs Speicher-Gate (``validate_guard``): falscher Wert-Typ (z. B. Liste) würde zur
# Laufzeit crashen (unhashable in ``in frozenset``) statt sauber zu failen.
_STRING_VALUE_OPERATORS: frozenset[str] = frozenset(
    {
        "roleIs",
        "isInCommittee",
        "applicantRoleIs",
        "applicantCommitteeIs",
        "budgetIs",
        "hasField",
    }
)
_BOOL_VALUE_OPERATORS: frozenset[str] = frozenset(
    {"deadlinePassed", "budgetFitsApplication", "actorIsApplicant"}
)

# Whitelist Action-Typen (Dispatch in der Engine, T-14).
ACTION_TYPES: frozenset[str] = frozenset({"webhook", "notify", "addToNextSession", "assignBudget"})

# Pflicht-String-Feld je Aktionstyp (``notify`` wird separat geprüft).
_ACTION_REQUIRED_FIELD: dict[str, str] = {
    "webhook": "webhookId",
    "addToNextSession": "gremiumId",
    "assignBudget": "budgetId",
}

# Gültige ``notify``-Empfänger-Arten.
NOTIFY_RECIPIENT_KINDS: frozenset[str] = frozenset({"gremium", "role", "applicant", "email"})


class GuardError(Exception):
    """Ungültiger Guard (unbekannter Operator, falsche Struktur, …)."""


@dataclass(frozen=True)
class GuardContext:
    """Laufzeit-Kontext für `eval_guard` (flows §9.2). Pure Eingabe, kein I/O.

    * ``manual`` — ob der Übergang manuell ausgelöst wird (Akteur-Gates greifen nur
      hier; im Automatik-Fall sind ``roles``/``actor_committees`` leer).
    * ``roles``/``actor_committees`` — **Akteur** (auslösender Principal).
    * ``applicant_roles``/``applicant_committees`` — **Antragsteller**.
    * ``budget_id`` — zugeordnete Kostenstelle (Budget-Baum) als String.
    * ``budget_fits`` — Betrag ≤ verfügbarer Rest der Kostenstelle.
    * ``field_values``/``field_types`` — Promoted-/Formularfeldwerte + ihr Typ
      (inkl. Built-in ``amount`` = ``currency``) für ``compare``/``hasField``.
    """

    manual: bool = True
    deadline_passed: bool = False
    # Akteur ist der/die Antragsteller:in (eingeloggte:r Ersteller:in oder Magic-Link).
    actor_is_applicant: bool = False
    roles: frozenset[str] = frozenset()
    actor_committees: frozenset[str] = frozenset()
    applicant_roles: frozenset[str] = frozenset()
    applicant_committees: frozenset[str] = frozenset()
    budget_id: str | None = None
    budget_fits: bool = False
    field_values: Mapping[str, Any] = field(default_factory=dict)
    field_types: Mapping[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Typ-Koerzierung + Vergleich (compare-Guard)
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
    """Erlaubte ``compare``-Operatoren für einen Wert-Typ (FE spiegelt das)."""
    if value_type in {"number", "currency"}:
        return _NUMERIC_OPS
    if value_type == "date":
        return _DATE_OPS
    if value_type == "bool":
        return _BOOL_OPS
    return _TEXT_OPS


def _eval_compare(spec: Any, ctx: GuardContext) -> bool:
    """``compare`` auswerten: ``{field, op, value}`` typgerecht vergleichen.

    Der Wert-Typ kommt aus ``ctx.field_types[field]`` (Default ``text``). Fehlt das
    Feld in ``field_values`` → ``False`` (fail-closed; impliziert ``hasField``)."""
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
        # Laufzeit-Typ kommt aus der **gepinnten** Form-Version des Antrags und kann
        # vom global gespeicherten Flow abweichen (Form-Drift, fehlendes Feld ⇒
        # ``text``). Fail-closed statt Exception — sonst 500 für alle Übergänge.
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


# Geordnete Vergleichsoperatoren → ``operator``-Funktion (statt einer if/elif-Kette,
# die Pythons eigene Operatoren von Hand nachbaut). Unbekannter Operator ⇒ ``False``
# (fail-closed; ``validate_guard`` lehnt unbekannte Operatoren ohnehin beim Speichern ab).
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
# Leaf-Evaluator
# --------------------------------------------------------------------------- #
def _has_field(value: Any, ctx: GuardContext) -> bool:
    """``hasField``: Feld vorhanden **und** nicht leer (None/""/[] zählen als fehlend)."""
    v = ctx.field_values.get(str(value))
    return v is not None and v != "" and v != []


# Leaf-Operator → reine Prädikatfunktion ``(value, ctx) -> bool``. Akteur-Gates greifen
# nur manuell (automatisch sind ``roles``/``actor_committees`` leer); ``compare``-Werte
# werden in :func:`_eval_compare` typgerecht verglichen.
_LEAF_EVALUATORS: dict[str, Callable[[Any, GuardContext], bool]] = {
    # Akteur-Gates
    "roleIs": lambda value, ctx: value in ctx.roles,
    "isInCommittee": lambda value, ctx: str(value) in ctx.actor_committees,
    # ``true`` ⇒ Akteur muss Antragsteller:in sein, ``false`` ⇒ nicht.
    "actorIsApplicant": lambda value, ctx: ctx.actor_is_applicant == bool(value),
    # Antragsteller
    "applicantRoleIs": lambda value, ctx: value in ctx.applicant_roles,
    "applicantCommitteeIs": lambda value, ctx: str(value) in ctx.applicant_committees,
    # Budget
    "budgetIs": lambda value, ctx: ctx.budget_id is not None and str(value) == ctx.budget_id,
    "budgetFitsApplication": lambda value, ctx: ctx.budget_fits == bool(value),
    # Fristen
    "deadlinePassed": lambda value, ctx: ctx.deadline_passed == bool(value),
    # Felder
    "hasField": _has_field,
    "compare": _eval_compare,
}


def _eval_leaf(op: str, value: Any, ctx: GuardContext) -> bool:
    evaluator = _LEAF_EVALUATORS.get(op)
    if evaluator is None:
        raise GuardError(f"unknown guard operator: {op!r}")  # pragma: no cover
    return evaluator(value, ctx)


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


def guard_requires_applicant(guard: dict[str, Any] | None) -> bool:
    """``True``, wenn der Guard-Baum (irgendwo) ein ``actorIsApplicant``-Gate enthält.

    Damit erlauben wir genau die Übergänge, die ein Admin **bewusst** für die
    Antragsteller:in freigegeben hat — ein Magic-Link-Applicant darf nur solche
    feuern (#guard/#applicant-actions)."""
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
# Statische Validierung (Speicher-Gate)
# --------------------------------------------------------------------------- #
def validate_guard(guard: dict[str, Any] | None, *, allow_actor_ops: bool = True) -> None:
    """Statisch prüfen: nur Whitelist-Operatoren, korrekte Struktur (Speicher-Gate).

    ``allow_actor_ops=False`` (automatische Übergänge) verbietet ``roleIs``/
    ``isInCommittee`` — ein Akteur-Gate ohne Akteur ergibt keinen Sinn."""
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
    """``compare``-Struktur prüfen (Typ wird erst zur Laufzeit aus dem Feld bestimmt;
    hier nur Form + dass ``op`` überhaupt ein bekannter Vergleichsoperator ist)."""
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
    """Statisch prüfen, dass `action.type` in der Whitelist liegt + Pflichtfelder.

    ``webhook`` braucht ``webhookId``; ``notify`` eine Empfänger-Liste mit gültigen
    Arten; ``addToNextSession`` ein ``gremiumId`` (Ziel-State-Constraint prüft der
    Flow-Graph-Validator, der die Transition kennt)."""
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
    # Übrige Aktionen verlangen je genau ein nicht-leeres String-Feld.
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
