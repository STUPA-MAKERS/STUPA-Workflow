"""Unit tests for `data_uuid_strings`: UUID extraction from `data`.

The function is pure and needs no database. These tests cover the collection logic. It
walks the payload, reads values only and keeps UUID-shaped strings only. The
integration test covers the database lookup.
"""

from __future__ import annotations

import uuid

from app.modules.audit_log.service import data_uuid_strings

_U1 = str(uuid.uuid4())
_U2 = str(uuid.uuid4())


def test_collects_top_level_uuid_values() -> None:
    assert data_uuid_strings({"gremiumId": _U1, "budgetId": _U2}) == {_U1, _U2}


def test_ignores_non_uuid_values_and_reads_uuid_keys() -> None:
    """A map of changes names each cost center in its key.

    Rule: §F/finance/budget/000802.
    """
    assert data_uuid_strings({_U1: "not-a-uuid", "count": 7, "flag": True}) == {_U1}


def test_walks_nested_dicts_and_lists() -> None:
    payload = {"members": [{"delegateId": _U1}, _U2], "meta": {"x": {"id": _U1}}}
    assert data_uuid_strings(payload) == {_U1, _U2}


def test_empty_and_none() -> None:
    assert data_uuid_strings(None) == set()
    assert data_uuid_strings({}) == set()
