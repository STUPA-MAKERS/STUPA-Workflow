"""Routing-Logik der Global-Flow-Engine (#28) — **reine** Funktionen.

Drei State-Arten brauchen eine Auswahl, welcher Ausgang gefeuert wird:

* ``decision`` — Auto-Routing nach Fakten des Antrags (Betrag/Typ/Antragsteller-Rolle).
  ``config = {rules: [{when, to}], else}``; die erste passende Regel gewinnt, sonst
  ``else``. ``to``/``else`` sind State-**Keys**.
* ``vote``     — ein Gremium stimmt ab; Ergebnis ``pass``/``fail`` wählt den Branch.
* ``approval`` — Rolle X in Gremium Y nimmt an/ab; ``accept``/``reject`` wählt den Branch.

Alles hier ist I/O-frei und damit isoliert testbar; die :class:`FlowService` lädt die
Fakten/Transitions und feuert den ausgewählten Übergang.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class DecisionFacts:
    """Antrags-Fakten, gegen die ``decision``-Regeln ausgewertet werden."""

    amount: Decimal | None = None
    type_key: str | None = None
    applicant_roles: frozenset[str] = field(default_factory=frozenset)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _eval_predicate(when: Any, facts: DecisionFacts) -> bool:
    """Eine einzelne ``when``-Bedingung auswerten.

    Form: ``{"field": <amount|typeKey|applicantRole>, "op": <op>, "value": <v>}``.
    Unbekannte Felder/Operatoren ⇒ ``False`` (fail-closed). Eine leere/None-Bedingung
    matcht immer (``True``) — so lässt sich eine bedingungslose Default-Regel schreiben.
    """
    if not when:
        return True
    if not isinstance(when, dict):
        return False
    fld = when.get("field")
    op = when.get("op")
    value = when.get("value")

    if fld == "amount":
        left = facts.amount
        right = _to_decimal(value)
        if left is None or right is None:
            return False
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        return False

    if fld == "typeKey":
        left_s = facts.type_key
        if op == "==":
            return left_s == value
        if op == "!=":
            return left_s != value
        if op == "in":
            return isinstance(value, list) and left_s in value
        return False

    if fld == "applicantRole":
        roles = facts.applicant_roles
        if op == "in":
            return isinstance(value, list) and any(r in roles for r in value)
        if op == "has":
            return value in roles
        if op == "notIn":
            return isinstance(value, list) and not any(r in roles for r in value)
        return False

    return False


def evaluate_decision(
    rules: list[dict[str, Any]], fallback: str, facts: DecisionFacts
) -> str:
    """Ziel-State-**Key** eines ``decision``-States bestimmen.

    Erste Regel, deren ``when`` matcht, gewinnt; sonst ``fallback`` (``config.else``).
    Regeln ohne gültiges ``to`` werden übersprungen (Validierung garantiert ``to`` aber).
    """
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        target = rule.get("to")
        if not isinstance(target, str):
            continue
        if _eval_predicate(rule.get("when"), facts):
            return target
    return fallback
