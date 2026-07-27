"""Cross-format staging deduplication and batch replacement (#fints-batch).

A move from MT940 to CAMT changes the idempotency keys. Staging therefore also compares
the content through a fingerprint. It replaces a split batch booking with its single
transactions. The fakes work as in `test_bank_service`: FIFO queues and no database I/O.
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


def test_fingerprint_keys_variants() -> None:
    # With an E2E reference, ONLY the E2E reference counts. It is the most precise key.
    fp = _line_fingerprint(_line(end_to_end_id="E2E-1", purpose="Miete"))
    assert _fingerprint_keys(fp) == [("2026-06-30|-10.00", "e2e:E2E-1")]
    # Without E2E: canonical purpose plus counterparty IBAN.
    fp = _line_fingerprint(_line(purpose="Miete Mai!", counterparty_iban="DE99"))
    assert _fingerprint_keys(fp) == [("2026-06-30|-10.00", "pp:MIETEMAI|DE99")]
    # Without a value date, or without both purpose and E2E: no content comparison.
    assert _fingerprint_keys(_line_fingerprint(_line(value_date=None, purpose="x"))) == []
    assert _fingerprint_keys(_line_fingerprint(_line())) == []


def test_consume_fingerprint_is_a_multiset() -> None:
    known = {("2026-06-30|-10.00", "e2e:E2E-1"): 1}
    fp = _line_fingerprint(_line(end_to_end_id="E2E-1"))
    assert StagingOps._consume_fingerprint(known, fp) is True
    # The single stored entry is used up, so the second identical line counts as NEW.
    assert StagingOps._consume_fingerprint(known, fp) is False
    assert StagingOps._consume_fingerprint(known, _line_fingerprint(_line())) is False


@pytest.mark.asyncio
async def test_stage_skips_cross_format_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip a payment that arrives again in another statement format.

    MT940 staged the payment. CAMT delivers it again under a different key. The content
    fingerprint (E2E) finds it, so the service inserts nothing.
    """
    session = _Session()
    svc = _svc(session, monkeypatch)
    # _existing_fingerprints: one stored line with the same value date, amount and E2E.
    session.execute_q.append(
        _Result([(date(2026, 6, 30), Decimal("-10.00"), "E2E-1", "Miete Mai", None)])
    )
    line = _line(end_to_end_id="E2E-1", bank_ref="CAMTREF", purpose="Miete Mai")
    imported, duplicates, superseded = await svc._stage_lines(_account(), [line])
    assert (imported, duplicates, superseded) == (0, 1, 0)
    # Only the fingerprint query ran. There is no suggestion and no insert.
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
    """Treat only one of two identical same-day payments as a duplicate.

    The store holds one of the two payments. The service marks exactly one incoming line
    as a duplicate and imports the other one.
    """
    session = _Session()
    svc = _svc(session, monkeypatch)
    session.execute_q.append(
        _Result([(date(2026, 6, 30), Decimal("-10.00"), "E2E-1", None, None)])
    )
    lines = [
        _line(end_to_end_id="E2E-1", bank_ref="R1"),
        _line(end_to_end_id="E2E-1", bank_ref="R2"),
    ]
    # Second line: an empty suggestion plus an insert that returns a row.
    session.execute_q.append(_Result([]))  # _suggest: candidates
    session.execute_q.append(_Result([uuid.uuid4()]))  # insert RETURNING
    imported, duplicates, _ = await svc._stage_lines(_account(), lines)
    assert (imported, duplicates) == (1, 1)


@pytest.mark.asyncio
async def test_stage_supersedes_stale_batch_total_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove the stale MT940 batch-total line when a CAMT split arrives.

    The CAMT split stages the single transactions. The service drops the old unbooked
    total line ("DATEI-NR. ...", total amount). A line without the batch pattern stays.
    """
    session = _Session()
    svc = _svc(session, monkeypatch)
    batch_raw = {"batch": "true", "batch_total": "-500.00", "batch_count": "2"}
    lines = [
        _line(amount=Decimal("-180.00"), bank_ref="S1", raw=dict(batch_raw)),
        _line(amount=Decimal("-320.00"), bank_ref="S2", raw=dict(batch_raw)),
    ]
    session.execute_q.append(_Result([]))  # fingerprints: empty
    for _ in lines:  # per line: empty suggestion plus a good insert
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
    )  # supersede candidates
    imported, duplicates, superseded = await svc._stage_lines(_account(), lines)
    assert (imported, duplicates, superseded) == (2, 0, 1)


def test_batch_file_number_extraction() -> None:
    assert (
        staging._batch_file_number("SAMMELUEBERWEISUNG DATEI-NR. 0000794247 ANZAHL 00000002")
        == "794247"
    )
    assert staging._batch_file_number("DATEI-NR. 0000802442") == "802442"
    assert staging._batch_file_number("Miete Juni") is None
    assert staging._batch_file_number(None) is None


@pytest.mark.asyncio
async def test_stage_supersede_scoped_by_file_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replace only the total line that carries the file number of the incoming split.

    Two batches share the same day and the same amount. The service replaces the total
    line whose `DATEI-NR.` matches the split. The other batch stays.
    """
    session = _Session()
    svc = _svc(session, monkeypatch)
    batch_raw = {
        "batch": "true",
        "batch_total": "-500.00",
        "batch_count": "2",
        "batch_info": "SAMMELUEBERWEISUNG DATEI-NR. 0000794247 ANZAHL 00000002",
    }
    lines = [
        _line(amount=Decimal("-180.00"), bank_ref="S1", raw=dict(batch_raw)),
        _line(amount=Decimal("-320.00"), bank_ref="S2", raw=dict(batch_raw)),
    ]
    session.execute_q.append(_Result([]))  # fingerprints: empty
    for _ in lines:  # per line: empty suggestion plus a good insert
        session.execute_q.append(_Result([]))
        session.execute_q.append(_Result([uuid.uuid4()]))
    session.execute_q.append(
        _Result(
            [
                (uuid.uuid4(), "SAMMELUEBERWEISUNG DATEI-NR. 0000794247 ANZAHL 00000002"),
                (uuid.uuid4(), "SAMMELUEBERWEISUNG DATEI-NR. 0000111111 ANZAHL 00000002"),
            ]
        )
    )  # supersede candidates: same day and amount, two different batches
    imported, _, superseded = await svc._stage_lines(_account(), lines)
    assert (imported, superseded) == (2, 1)


@pytest.mark.asyncio
async def test_stage_ignores_unparseable_batch_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line(bank_ref="S1", raw={"batch": "true", "batch_total": "kaputt"})
    session.execute_q.append(_Result([]))  # fingerprints
    session.execute_q.append(_Result([]))  # suggestion
    session.execute_q.append(_Result([uuid.uuid4()]))  # insert
    imported, _, superseded = await svc._stage_lines(_account(), [line])
    assert (imported, superseded) == (1, 0)


@pytest.mark.asyncio
async def test_stage_supersede_no_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line(bank_ref="S1", raw={"batch": "true", "batch_total": "-10.00"})
    session.execute_q.append(_Result([]))  # fingerprints
    session.execute_q.append(_Result([]))  # suggestion
    session.execute_q.append(_Result([uuid.uuid4()]))  # insert
    session.execute_q.append(_Result([]))  # supersede: no candidates
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
