"""Reine Feld-Diff-Berechnung für Antragsversionen (T-12) — keine DB/HTTP.

:func:`compute_diff` vergleicht zwei ``data``-Snapshots (alte vs. neue Feldwerte)
und liefert einen strukturierten Diff:

``{"added": {key: new}, "removed": {key: old}, "changed": {key: {"old", "new"}}}``

Verschachtelte Felder (Objekte, ``table``-Zeilenlisten) werden **wertweise** als
Ganzes verglichen — kein rekursives Zell-Diff. Das ist robust gegen heterogene
Tabellen-/Objektstrukturen (Risiko T-12) und reicht für Timeline/History.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict


class FieldChange(TypedDict):
    old: Any
    new: Any


class DataDiff(TypedDict):
    added: dict[str, Any]
    removed: dict[str, Any]
    changed: dict[str, FieldChange]


def compute_diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> DataDiff:
    """Strukturierten Diff zweier Feldwert-Maps berechnen.

    * ``added``   — Schlüssel nur in ``new``.
    * ``removed`` — Schlüssel nur in ``old``.
    * ``changed`` — Schlüssel in beiden, aber mit ungleichem Wert.
    """
    added: dict[str, Any] = {k: new[k] for k in new.keys() - old.keys()}
    removed: dict[str, Any] = {k: old[k] for k in old.keys() - new.keys()}
    changed: dict[str, FieldChange] = {
        k: {"old": old[k], "new": new[k]}
        for k in old.keys() & new.keys()
        if old[k] != new[k]
    }
    return {"added": added, "removed": removed, "changed": changed}


def is_empty_diff(diff: DataDiff) -> bool:
    """``True``, wenn der Diff keine Änderung enthält (keine neue Version nötig)."""
    return not (diff["added"] or diff["removed"] or diff["changed"])
