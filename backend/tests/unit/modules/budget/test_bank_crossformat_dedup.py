"""Format-übergreifende Staging-Deduplizierung + Sammel-Ersetzung (#fints-batch).

Der Umstieg MT940 → CAMT ändert Idempotenz-Schlüssel; das Staging gleicht deshalb
zusätzlich inhaltlich ab (Fingerprint) und ersetzt aufgeteilte Sammelbuchungen durch
ihre Einzelumsätze. Fakes wie in ``test_bank_service`` (FIFO-Queues, kein DB-I/O).
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.modules.budget.bank import service_base, staging
from app.modules.budget.bank.service import BankService
from app.modules.budget.bank.staging import (
    StagingOps,
    _Fingerprint,
    _fingerprint_keys,
    _line_fingerprint,
)
from app.modules.budget.bank.statement import StatementLine
from app.modules.budget.tree_models import Account
from app.settings import load_settings

_KEY = "0123456789abcdef-fints-enc-key"


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    def __init__(self) -> None:
        self.execute_q: deque[_Result] = deque()
        self.scalar_q: deque[Any] = deque()
        self.executed: list[Any] = []
        self.commits = 0

    async def execute(self, stmt: Any) -> _Result:
        self.executed.append(stmt)
        return self.execute_q.popleft() if self.execute_q else _Result([])

    async def scalar(self, _stmt: Any) -> Any:
        return self.scalar_q.popleft() if self.scalar_q else None

    async def commit(self) -> None:
        self.commits += 1


def _svc(session: _Session, monkeypatch: pytest.MonkeyPatch) -> BankService:
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(service_base, "audit_record", _noop)
    return BankService(
        session,  # type: ignore[arg-type]
        settings=load_settings(fints_enc_key=_KEY),
        actor="tester",
        principal_id=uuid.uuid4(),
    )


def _account() -> Account:
    return Account(id=uuid.uuid4(), name="Giro", iban="DE111", active=True)


def _line(**over: Any) -> StatementLine:
    base: dict[str, Any] = dict(amount=Decimal("-10.00"), value_date=date(2026, 6, 30))
    base.update(over)
    return StatementLine(**base)


# ------------------------------------------------------------- pure fingerprints
def test_fingerprint_keys_variants() -> None:
    # Mit E2E-Ref zählt NUR die E2E-Ref (präzisester Schlüssel).
    fp = _line_fingerprint(_line(end_to_end_id="E2E-1", purpose="Miete"))
    assert _fingerprint_keys(fp) == [("2026-06-30|-10.00", "e2e:E2E-1")]
    # Ohne E2E: kanonischer Zweck + Gegen-IBAN.
    fp = _line_fingerprint(_line(purpose="Miete Mai!", counterparty_iban="DE99"))
    assert _fingerprint_keys(fp) == [("2026-06-30|-10.00", "pp:MIETEMAI|DE99")]
    # Ohne Wertstellung oder ohne Zweck+E2E: kein Inhalts-Vergleich.
    assert _fingerprint_keys(_line_fingerprint(_line(value_date=None, purpose="x"))) == []
    assert _fingerprint_keys(_line_fingerprint(_line())) == []


def test_consume_fingerprint_is_a_multiset() -> None:
    known = {("2026-06-30|-10.00", "e2e:E2E-1"): 1}
    fp = _line_fingerprint(_line(end_to_end_id="E2E-1"))
    assert StagingOps._consume_fingerprint(known, fp) is True
    # Der eine Bestands-Eintrag ist verbraucht → die zweite identische Zeile ist NEU.
    assert StagingOps._consume_fingerprint(known, fp) is False
    assert StagingOps._consume_fingerprint(known, _line_fingerprint(_line())) is False


# ----------------------------------------------------------- _stage_lines flows
@pytest.mark.asyncio
async def test_stage_skips_cross_format_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eine per MT940 gestagete Zahlung kommt per CAMT (anderer Schlüssel) erneut →
    inhaltlicher Fingerprint (E2E) erkennt sie; kein Insert."""
    session = _Session()
    svc = _svc(session, monkeypatch)
    # _existing_fingerprints: eine Bestandszeile mit gleicher Valuta/Betrag/E2E.
    session.execute_q.append(
        _Result([(date(2026, 6, 30), Decimal("-10.00"), "E2E-1", "Miete Mai", None)])
    )
    line = _line(end_to_end_id="E2E-1", bank_ref="CAMTREF", purpose="Miete Mai")
    imported, duplicates, superseded = await svc._stage_lines(_account(), [line])
    assert (imported, duplicates, superseded) == (0, 1, 0)
    # Nur die Fingerprint-Query lief — kein Vorschlag, kein Insert.
    assert len(session.executed) == 1


@pytest.mark.asyncio
async def test_stage_purpose_iban_fingerprint_without_e2e(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    session.execute_q.append(
        _Result([(date(2026, 6, 30), Decimal("-10.00"), None, "Miete  Mai!", "DE99")])
    )
    line = _line(purpose="MIETE MAI", counterparty_iban="DE99", bank_ref="X")
    imported, duplicates, _ = await svc._stage_lines(_account(), [line])
    assert (imported, duplicates) == (0, 1)


@pytest.mark.asyncio
async def test_stage_multiset_keeps_second_identical_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zwei identische Zahlungen am selben Tag, nur EINE davon im Bestand → genau eine
    der eingehenden gilt als Dublette, die andere wird importiert."""
    session = _Session()
    svc = _svc(session, monkeypatch)
    session.execute_q.append(
        _Result([(date(2026, 6, 30), Decimal("-10.00"), "E2E-1", None, None)])
    )
    lines = [
        _line(end_to_end_id="E2E-1", bank_ref="R1"),
        _line(end_to_end_id="E2E-1", bank_ref="R2"),
    ]
    # Zweite Zeile: Vorschlag (leer) + Insert (liefert Zeile).
    session.execute_q.append(_Result([]))  # _suggest: Kandidaten
    session.execute_q.append(_Result([uuid.uuid4()]))  # Insert RETURNING
    imported, duplicates, _ = await svc._stage_lines(_account(), lines)
    assert (imported, duplicates) == (1, 1)


@pytest.mark.asyncio
async def test_stage_supersedes_stale_batch_total_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CAMT-Split staged Einzelumsätze → die alte, ungebuchte MT940-Gesamt-Zeile
    („DATEI-NR. …", Gesamtbetrag) wird entfernt; Zeilen ohne Sammel-Muster bleiben."""
    session = _Session()
    svc = _svc(session, monkeypatch)
    batch_raw = {"batch": "true", "batch_total": "-500.00", "batch_count": "2"}
    lines = [
        _line(amount=Decimal("-180.00"), bank_ref="S1", raw=dict(batch_raw)),
        _line(amount=Decimal("-320.00"), bank_ref="S2", raw=dict(batch_raw)),
    ]
    session.execute_q.append(_Result([]))  # Fingerprints: leer
    for _ in lines:  # je Zeile: Vorschlag leer + Insert ok
        session.execute_q.append(_Result([]))
        session.execute_q.append(_Result([uuid.uuid4()]))
    stale_id = uuid.uuid4()
    session.execute_q.append(
        _Result(
            [
                (stale_id, "DATEI-NR. 0000794247 ANZAHL 00000002"),
                (uuid.uuid4(), "Echte Einzelzahlung 500"),
            ]
        )
    )  # Supersede-Kandidaten
    imported, duplicates, superseded = await svc._stage_lines(_account(), lines)
    assert (imported, duplicates, superseded) == (2, 0, 1)


@pytest.mark.asyncio
async def test_stage_ignores_unparseable_batch_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line(bank_ref="S1", raw={"batch": "true", "batch_total": "kaputt"})
    session.execute_q.append(_Result([]))  # Fingerprints
    session.execute_q.append(_Result([]))  # Vorschlag
    session.execute_q.append(_Result([uuid.uuid4()]))  # Insert
    imported, _, superseded = await svc._stage_lines(_account(), [line])
    assert (imported, superseded) == (1, 0)


@pytest.mark.asyncio
async def test_stage_supersede_no_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line(bank_ref="S1", raw={"batch": "true", "batch_total": "-10.00"})
    session.execute_q.append(_Result([]))  # Fingerprints
    session.execute_q.append(_Result([]))  # Vorschlag
    session.execute_q.append(_Result([uuid.uuid4()]))  # Insert
    session.execute_q.append(_Result([]))  # Supersede: keine Kandidaten
    imported, _, superseded = await svc._stage_lines(_account(), [line])
    assert (imported, superseded) == (1, 0)


@pytest.mark.asyncio
async def test_existing_fingerprints_skips_lines_without_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    known = await svc._existing_fingerprints(uuid.uuid4(), [_line(value_date=None)])
    assert known == {}
    assert session.executed == []


def test_fingerprint_dataclass_shape() -> None:
    fp = staging._Fingerprint(
        value_date=date(2026, 6, 30),
        amount=Decimal("-1.00"),
        end_to_end=None,
        purpose_key="",
        counterparty_iban=None,
    )
    assert isinstance(fp, _Fingerprint)
