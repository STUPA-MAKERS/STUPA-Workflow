"""Unit-Tests für :func:`bank_maintenance.dedup_staged_lines` (#fints-dedup) — mit einer
synchronen Fake-Connection, ohne DB."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.modules.budget.bank_maintenance import dedup_staged_lines


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeConn:
    """Sync-``Connection``-Stub: erste ``execute`` = SELECT (liefert rows), danach DELETE/UPDATE."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.deleted: list[Any] = []
        self.updated: list[tuple[Any, str]] = []

    def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        sql = str(stmt).strip().upper()
        if sql.startswith("SELECT"):
            return _Result(self._rows)
        if sql.startswith("DELETE"):
            self.deleted.append(params["id"])  # type: ignore[index]
            return None
        if sql.startswith("UPDATE"):
            self.updated.append((params["id"], params["k"]))  # type: ignore[index]
            return None
        raise AssertionError(f"unexpected SQL: {sql[:20]}")


def _row(rid: str, state: str, raw: dict[str, Any], *, acc: uuid.UUID,
         vd: date = date(2026, 6, 9), amt: str = "-250.00", created: int = 1) -> Any:
    return SimpleNamespace(
        id=rid, account_id=acc, value_date=vd, amount=Decimal(amt), end_to_end_id=None,
        match_state=state, created_at=datetime(2026, 1, created), raw_payload=raw,
        acc_iban="DE79640500000100083958",
    )


def test_dedup_collapses_matched_unmatched_twin_keeps_booked() -> None:
    acc = uuid.uuid4()
    clara = {"purpose": "ASTA 05/26", "applicant_name": "DE16604914300400950006Clara Schweiker"}
    rows = [
        _row("m1", "matched", dict(clara), acc=acc, created=1),            # gebucht
        _row("u1", "unmatched", {**clara, "booking_time": "15:51"}, acc=acc, created=2),  # Dublette
        # echte Einzelzahlungen: gleicher Tag/Betrag, ANDERER Roh-Auftraggeber → kein Kollaps
        _row("a1", "unmatched", {"purpose": "Aufwand", "applicant_name": "Alice"}, acc=acc),
        _row("b1", "unmatched", {"purpose": "Aufwand", "applicant_name": "Bob"}, acc=acc),
    ]
    conn = _FakeConn(rows)
    deleted = dedup_staged_lines(conn)
    assert deleted == 1
    assert conn.deleted == ["u1"]            # ungebuchte Dublette gelöscht
    assert [u[0] for u in conn.updated] == ["m1"]  # gebuchte behalten + neu verschlüsselt
    # Alice/Bob unangetastet
    assert "a1" not in conn.deleted and "b1" not in conn.deleted


def test_dedup_keeps_oldest_when_no_matched() -> None:
    acc = uuid.uuid4()
    raw = {"purpose": "X", "applicant_name": "DE16604914300400950006Clara Schweiker"}
    rows = [
        _row("old", "unmatched", dict(raw), acc=acc, created=1),
        _row("new", "suggested", {**raw, "booking_time": "11:15"}, acc=acc, created=2),
    ]
    conn = _FakeConn(rows)
    assert dedup_staged_lines(conn) == 1
    assert conn.deleted == ["new"]           # jüngere Dublette weg, älteste bleibt
    assert [u[0] for u in conn.updated] == ["old"]


def test_dedup_noop_without_duplicates() -> None:
    acc = uuid.uuid4()
    rows = [_row("x", "matched", {"purpose": "X", "applicant_name": "Solo"}, acc=acc)]
    conn = _FakeConn(rows)
    assert dedup_staged_lines(conn) == 0
    assert conn.deleted == []
