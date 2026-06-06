"""Budget-Domänenlogik (pur, ohne DB) — T-17.

Sämtliche Entscheidungen (Stufen-Übergang, Überbuchung, Auslastungs-Aggregation,
Topf-Zuordbarkeit) liegen hier als reine Funktionen → deterministisch + ohne
Backing-Services prüfbar (testing.md §1: ``budget`` = kritisches Modul, 100 % Branch).
Der Service (``service.py``) bleibt dünne I/O-Verdrahtung auf diese Regeln.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.modules.budget.models import STAGES

# Stufen, deren Beträge den Topf binden (gegen ``total`` gezählt). ``requested`` ist
# reine Absicht und zählt nicht (SDS-A1).
COMMITTED_STAGES: frozenset[str] = frozenset({"reserved", "approved", "paid"})

_ZERO = Decimal("0")


def stage_index(stage: str) -> int:
    """Position einer Stufe in :data:`STAGES`. Wirft ``ValueError`` bei Unbekanntem."""
    return STAGES.index(stage)


def is_valid_stage(stage: str) -> bool:
    return stage in STAGES


def is_committed(stage: str) -> bool:
    """Bindet die Stufe Budget (zählt gegen ``budget_pot.total``)?"""
    return stage in COMMITTED_STAGES


def can_advance(current: str, target: str) -> bool:
    """Vorwärts-Übergang ``current → target`` zulässig?

    Nur echte Vorwärtsbewegung entlang :data:`STAGES` (Überspringen erlaubt, SDS-A1
    »per Config kürzbar«); gleichbleiben/zurück → ``False``. Unbekannte Stufen → ``False``.
    """
    if not (is_valid_stage(current) and is_valid_stage(target)):
        return False
    return stage_index(target) > stage_index(current)


def as_amount(value: Decimal | None) -> Decimal:
    """``None`` → 0; sonst der Betrag (budgetlose Bindung zählt als 0)."""
    return value if value is not None else _ZERO


def available(total: Decimal | None, committed: Decimal) -> Decimal | None:
    """Freier Topf-Rest. ``total=None`` (unbegrenzt) → ``None``."""
    if total is None:
        return None
    return total - committed


def would_overbook(
    total: Decimal | None, committed_others: Decimal, amount: Decimal | None
) -> bool:
    """Überbucht das Hinzufügen von ``amount`` den Topf?

    ``total=None`` → unbegrenzt → nie. Sonst: bereits gebundener Rest (ohne den
    betroffenen Antrag) + neuer Betrag > Topf-Total.
    """
    if total is None:
        return False
    return committed_others + as_amount(amount) > total


@dataclass(frozen=True, slots=True)
class PotUsage:
    """Aggregierte Topf-Auslastung (eine Zeile je Topf)."""

    requested: Decimal
    reserved: Decimal
    approved: Decimal
    paid: Decimal
    committed: Decimal
    available: Decimal | None


def usage_from_stage_sums(
    stage_sums: Mapping[str, Decimal], total: Decimal | None
) -> PotUsage:
    """Stufen-Summen (``{stage: sum}``) + Topf-Total → :class:`PotUsage`."""
    requested = stage_sums.get("requested", _ZERO)
    reserved = stage_sums.get("reserved", _ZERO)
    approved = stage_sums.get("approved", _ZERO)
    paid = stage_sums.get("paid", _ZERO)
    committed = reserved + approved + paid
    return PotUsage(
        requested=requested,
        reserved=reserved,
        approved=approved,
        paid=paid,
        committed=committed,
        available=available(total, committed),
    )


def stage_sums_by_pot(
    rows: Iterable[tuple[object, str, Decimal | None]],
) -> dict[object, dict[str, Decimal]]:
    """``(pot_id, stage, amount)``-Zeilen → ``{pot_id: {stage: summe}}``.

    Aggregiert die MV-/Entry-Rohzeilen pro Topf und Stufe (reine Statistik-Logik).
    """
    out: dict[object, dict[str, Decimal]] = {}
    for pot_id, stage, amount in rows:
        per_stage = out.setdefault(pot_id, {})
        per_stage[stage] = per_stage.get(stage, _ZERO) + as_amount(amount)
    return out


def assignment_block_reason(
    *, has_budget: bool, type_gremium_id: object, pot_gremium_id: object
) -> str | None:
    """Grund, warum ein Topf **nicht** zugeordnet werden darf — oder ``None`` (ok).

    Fail-closed: nur ``has_budget``-Typen dürfen Töpfe tragen (data-model §2), und der
    Topf muss zum Gremium des Typs gehören (kein Cross-Gremium-Leak).
    """
    if not has_budget:
        return "application type does not support budget pots"
    if type_gremium_id is None or pot_gremium_id != type_gremium_id:
        return "budget pot is not available for this application type's gremium"
    return None
