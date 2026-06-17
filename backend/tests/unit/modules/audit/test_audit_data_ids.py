"""Unit: ``data_uuid_strings`` — UUID-Extraktion aus ``data``-Payloads (#no-uuids-in-ui).

Reine Funktion ohne DB: deckt die Sammel-Logik ab (rekursiv, Werte-only, nur
UUID-förmige Strings). Die DB-Auflösung selbst liegt im Integrationstest.
"""

from __future__ import annotations

import uuid

from app.modules.audit.service import data_uuid_strings

_U1 = str(uuid.uuid4())
_U2 = str(uuid.uuid4())


def test_collects_top_level_uuid_values() -> None:
    assert data_uuid_strings({"gremiumId": _U1, "budgetId": _U2}) == {_U1, _U2}


def test_ignores_non_uuid_and_keys() -> None:
    # Schlüssel zählen nicht; Nicht-UUID-Werte werden verworfen.
    assert data_uuid_strings({_U1: "not-a-uuid", "count": 7, "flag": True}) == set()


def test_walks_nested_dicts_and_lists() -> None:
    payload = {"members": [{"delegateId": _U1}, _U2], "meta": {"x": {"id": _U1}}}
    assert data_uuid_strings(payload) == {_U1, _U2}


def test_empty_and_none() -> None:
    assert data_uuid_strings(None) == set()
    assert data_uuid_strings({}) == set()
