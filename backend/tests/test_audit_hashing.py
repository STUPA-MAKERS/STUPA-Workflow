"""TDD: kanonische Serialisierung + Hash-Kette (T-23, security.md §4)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.audit.hashing import canonical_payload, compute_hash

_AT = datetime(2026, 6, 6, 12, 0, 0, tzinfo=UTC)


def _payload(data: dict[str, object]) -> bytes:
    return canonical_payload(
        actor="admin-1",
        action="status_change",
        target_type="application",
        target_id="abc",
        at=_AT,
        data=data,
    )


def test_canonical_is_key_order_independent() -> None:
    a = _payload({"x": 1, "y": 2})
    b = _payload({"y": 2, "x": 1})
    assert a == b


def test_canonical_nested_key_order_independent() -> None:
    a = _payload({"o": {"a": 1, "b": 2}})
    b = _payload({"o": {"b": 2, "a": 1}})
    assert a == b


def test_canonical_compact_and_sorted() -> None:
    raw = _payload({"b": 1, "a": 2}).decode("utf-8")
    # Felder alphabetisch, kompakte Separatoren, action vor actor.
    assert raw.startswith('{"action":"status_change","actor":"admin-1"')
    assert ", " not in raw
    assert raw.index('"a":2') < raw.index('"b":1')  # data-Keys sortiert


def test_canonical_at_is_iso() -> None:
    assert _AT.isoformat() in _payload({}).decode("utf-8")


def test_canonical_rejects_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(TypeError):
        _payload({"bad": object()})


def test_compute_hash_genesis_uses_empty_prev() -> None:
    canonical = _payload({})
    assert compute_hash(None, canonical) == compute_hash(b"", canonical)


def test_compute_hash_depends_on_prev() -> None:
    canonical = _payload({})
    assert compute_hash(None, canonical) != compute_hash(b"\x01" * 32, canonical)


def test_compute_hash_is_32_bytes_and_deterministic() -> None:
    canonical = _payload({"k": "v"})
    first = compute_hash(b"\x02" * 32, canonical)
    assert len(first) == 32
    assert first == compute_hash(b"\x02" * 32, canonical)


def test_chain_links_change_when_field_changes() -> None:
    base = compute_hash(None, _payload({"k": 1}))
    tampered = compute_hash(None, _payload({"k": 2}))
    assert base != tampered
