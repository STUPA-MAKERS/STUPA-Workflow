"""Budget-Baum-Domänenlogik (pur, ohne DB) — CR #76/#78 (R7.1*).

Sämtliche Entscheidungen des Kostenstellen-Baums liegen hier als reine Funktionen
→ deterministisch + ohne Backing-Services prüfbar (testing.md §1: ``budget`` =
kritisches Modul, 100 % Branch). Der Service (``tree_service.py``) bleibt dünne
I/O-Verdrahtung auf diese Regeln.

Merksatz (R7.1b/c): **Allokation fließt runter (Top-Down, KEIN Roll-up), Verbrauch
fließt rauf (Roll-up der gebundenen Summe aus genehmigten Anträgen).**
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from typing import TypeVar

_T = TypeVar("_T")

# Pfad-Segment: alphanumerisch (z.B. ``VS``/``800``/``04``). Trenner ``-`` ist reserviert
# für die Pfad-Komposition und daher im Segment verboten.
_KEY_RE = re.compile(r"^[A-Za-z0-9]+$")
_SEP = "-"
_ZERO = Decimal("0")


def is_valid_key(key: str) -> bool:
    """Gültiges Pfad-Segment? Alphanumerisch, kein Trenner ``-`` (kollidiert mit Pfad)."""
    return bool(_KEY_RE.match(key))


def compose_path_key(parent_path: str | None, key: str) -> str:
    """Pfad-Key bilden: Top-Level → ``key``; sonst ``<parent_path>-<key>``."""
    if parent_path is None:
        return key
    return f"{parent_path}{_SEP}{key}"


def is_descendant_path(ancestor_path: str, node_path: str) -> bool:
    """Liegt ``node_path`` **echt unterhalb** ``ancestor_path`` im Baum?

    Über die Pfad-Präfix-Konvention (``VS`` ⊃ ``VS-800`` ⊃ ``VS-800-04``). Der Knoten
    selbst zählt **nicht** als Nachfahre.
    """
    return node_path.startswith(ancestor_path + _SEP)


def is_self_or_descendant_path(ancestor_path: str, node_path: str) -> bool:
    """Knoten selbst **oder** Nachfahre (für Roll-up-Aggregation: Leaf zählt zu sich)."""
    return node_path == ancestor_path or is_descendant_path(ancestor_path, node_path)


def intervals_overlap(
    a_start: date, a_end: date, b_start: date, b_end: date
) -> bool:
    """Überschneiden sich zwei abgeschlossene Datums-Intervalle ``[start, end]``?

    Klassischer Overlap-Test: ``a.start <= b.end AND b.start <= a.end`` (R7.1f/g).
    Lücken zwischen HHJ sind erlaubt — nur Überlappung verboten.
    """
    return a_start <= b_end and b_start <= a_end


def overlaps_any(
    new_start: date,
    new_end: date,
    existing: Iterable[tuple[date, date]],
) -> bool:
    """Schneidet ``[new_start, new_end]`` irgendein bestehendes HHJ-Intervall?"""
    return any(
        intervals_overlap(new_start, new_end, s, e) for s, e in existing
    )


def as_amount(value: Decimal | None) -> Decimal:
    """``None`` → 0; sonst der Betrag."""
    return value if value is not None else _ZERO


def children_allocation_exceeds_parent(
    parent_allocated: Decimal | None,
    siblings_sum_excluding: Decimal,
    new_value: Decimal,
) -> bool:
    """Überschreitet das Setzen einer Kind-Zuteilung das Parent-Budget (R7.1b)?

    ``siblings_sum_excluding`` = Σ ``allocated`` der **anderen** direkten Kinder (ohne
    das gerade gesetzte). Verletzung, wenn die neue Summe der Kinder die
    Parent-Zuteilung übersteigt. Fehlende Parent-Zuteilung gilt als 0 → jede positive
    Kind-Zuteilung verletzt (Top-Down: ohne Parent-Budget nichts verteilbar).
    """
    return siblings_sum_excluding + new_value > as_amount(parent_allocated)


def parent_allocation_below_children(
    new_parent_value: Decimal,
    children_sum: Decimal,
) -> bool:
    """Senkt das Setzen der Parent-Zuteilung diese **unter** die bereits an Kinder
    verteilte Summe (R7.1b, Gegenrichtung)? Dann verletzt → 422."""
    return new_parent_value < children_sum


def rollup_committed(
    node_paths: Iterable[tuple[object, str]],
    leaf_amounts: Iterable[tuple[str, Decimal | None]],
) -> dict[object, Decimal]:
    """Gebundene Summe je Knoten = Roll-up der genehmigten Antrags-Beträge (R7.1c).

    ``node_paths`` = ``(node_id, path_key)`` aller Baumknoten; ``leaf_amounts`` =
    ``(leaf_path_key, amount)`` je gebundenem (genehmigtem) Antrag. Jeder Antrag zählt
    zu **seiner** Kostenstelle und allen **Vorfahren** (Pfad-Präfix). Verbrauch fließt
    rauf — verfügbar (allocated) bleibt unberührt.
    """
    leaves = [(path, as_amount(amount)) for path, amount in leaf_amounts]
    out: dict[object, Decimal] = {}
    for node_id, node_path in node_paths:
        total = _ZERO
        for leaf_path, amount in leaves:
            if is_self_or_descendant_path(node_path, leaf_path):
                total += amount
        out[node_id] = total
    return out


def node_available(
    allocated: Decimal | None, committed: Decimal
) -> Decimal:
    """Freie Summe eines Knotens = verfügbar (allocated) − gebunden (committed)."""
    return as_amount(allocated) - committed


def pick_fiscal_year(active_ids: Sequence[_T]) -> _T | None:
    """HHJ bei Budget-Zuordnung ableiten (R7.1e): genau **ein** aktives HHJ → dieses;
    sonst ``None`` (mehrdeutig/keins → Service lässt ``fiscal_year_id`` offen)."""
    return active_ids[0] if len(active_ids) == 1 else None


# Knoten-Tupel: (id, parent_id, gremium_id, key, path_key, name, currency, active).
NodeTuple = tuple[object, object | None, object | None, str, str, str, str, bool]


def _views_for_node(
    node_id: object,
    alloc_by_node: dict[tuple[object, object], Decimal],
    committed_by_node: dict[tuple[object, object], Decimal],
) -> list[dict]:
    """``AllocationView``-Dicts eines Knotens je relevantem HHJ (allocated ODER bound)."""
    fys = {fy for (nid, fy) in alloc_by_node if nid == node_id}
    fys |= {fy for (nid, fy) in committed_by_node if nid == node_id}
    views: list[dict] = []
    for fy in sorted(fys, key=str):
        allocated = alloc_by_node.get((node_id, fy), _ZERO)
        committed = committed_by_node.get((node_id, fy), _ZERO)
        views.append(
            {
                "fiscal_year_id": fy,
                "allocated": allocated,
                "committed": committed,
                "available": node_available(allocated, committed),
            }
        )
    return views


def build_forest(
    nodes: Sequence[NodeTuple],
    allocations: Sequence[tuple[object, object, Decimal | None]],
    committed_rows: Sequence[tuple[object, str, Decimal | None]],
    *,
    gremium_id: object | None = None,
) -> list[dict]:
    """Reiner Baum-Aufbau für ``GET /budgets`` → DTO-fertige (snake_case) Dicts.

    * ``allocations`` = ``(budget_id, fiscal_year_id, allocated)`` — Top-Down (R7.1b).
    * ``committed_rows`` = ``(fiscal_year_id, leaf_path_key, amount)`` je gebundenem
      (genehmigtem) Antrag → Roll-up je HHJ über Pfad-Präfix (R7.1c).
    * ``gremium_id`` filtert die **Wurzeln** (Top-Level-Budgets) optional.

    Verbrauch fließt rauf, Allokation bleibt am Knoten — getrennt je HHJ ausgewiesen.
    """
    node_paths = [(nid, path) for nid, _, _, _, path, _, _, _ in nodes]

    # committed je HHJ rollup'en (Verbrauch fließt rauf).
    fy_leaves: dict[object, list[tuple[str, Decimal | None]]] = {}
    for fy_id, leaf_path, amount in committed_rows:
        fy_leaves.setdefault(fy_id, []).append((leaf_path, amount))
    committed_by_node: dict[tuple[object, object], Decimal] = {}
    for fy_id, leaves in fy_leaves.items():
        for nid, total in rollup_committed(node_paths, leaves).items():
            if total != _ZERO:
                committed_by_node[(nid, fy_id)] = total

    alloc_by_node: dict[tuple[object, object], Decimal] = {
        (bid, fy): as_amount(value) for bid, fy, value in allocations
    }

    children_of: dict[object | None, list[NodeTuple]] = {}
    for n in nodes:
        children_of.setdefault(n[1], []).append(n)

    def to_dict(n: NodeTuple) -> dict:
        nid, parent_id, n_gremium, key, path, name, currency, active = n
        return {
            "id": nid,
            "parent_id": parent_id,
            "gremium_id": n_gremium,
            "key": key,
            "path_key": path,
            "name": name,
            "currency": currency,
            "active": active,
            "by_fiscal_year": _views_for_node(nid, alloc_by_node, committed_by_node),
            "children": [to_dict(c) for c in children_of.get(nid, [])],
        }

    roots = children_of.get(None, [])
    return [
        to_dict(r)
        for r in roots
        if gremium_id is None or r[2] == gremium_id
    ]
