"""F17, Z3, Z7: the header of the protocol.

* The excused members are their own group. The public variant names only the
  counts.
* Every keeper period is a header line, with the TOP numbers of the current agenda
  order or the time. The public variant leaves the keepers out.
* The start line uses the real start, else the planned start.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from app.modules.protocol.markdown import KeeperLine, ProtocolDoc, build_protocol_document
from app.modules.protocol.service import ProtocolService
from app.settings import get_settings
from tests._support.protocol_fakes import FakeResult, FakeSession, result

MID = uuid4()
GID = uuid4()


class _AttendanceSession(FakeSession):
    """Answer the attendance query with fixed rows of (status, name, sub)."""

    def __init__(self, rows: list[tuple[str, str | None, str]], **kw: Any) -> None:
        super().__init__(**kw)
        self.rows = rows

    async def execute(self, _stmt: Any) -> FakeResult:
        if "meeting_attendance" in str(_stmt).lower():
            return FakeResult(self.rows)
        return await super().execute(_stmt)


def _meeting(**over: Any) -> Any:
    base: dict[str, Any] = {
        "id": MID,
        "gremium_id": GID,
        "title": "GV",
        "date": date(2026, 6, 20),
        "start_time": time(18, 0),
        "started_at": None,
        "closed_at": None,
        "protokollant_id": None,
    }
    base.update(over)
    return cast("Any", SimpleNamespace(**base))


def _service(session: Any) -> ProtocolService:
    return ProtocolService(session, settings=get_settings())


ROWS = [
    ("present", "Anna", "a"),
    ("excused", "Cora", "c"),
    ("absent", None, "dirk-sub"),
    ("excused", "Eva", "e"),
]


async def test_internal_header_lists_the_excused_group() -> None:
    header = await _service(_AttendanceSession(ROWS))._header_meta(_meeting())
    assert header.present == ["Anna"]
    assert header.excused == ["Cora", "Eva"]
    assert header.absent == ["dirk-sub"]
    assert header.present_count == 1
    assert header.datalines == []


async def test_public_header_counts_only() -> None:
    session = _AttendanceSession(ROWS)
    session.keeper_rows = [SimpleNamespace(principal_id=uuid4(), from_at=datetime.now(UTC))]
    header = await _service(session)._header_meta(_meeting(), public=True)
    assert header.present == [] and header.excused == [] and header.absent == []
    assert header.keepers == [] and header.protokollant is None
    assert header.present_count == 1
    assert header.datalines == ["Anwesend: 1", "Entschuldigt: 2", "Abwesend: 1"]


async def test_header_lists_every_keeper_period() -> None:
    anna, bert = uuid4(), uuid4()
    item1, item2, gone = uuid4(), uuid4(), None
    session = _AttendanceSession(
        [],
        results=[
            result((anna, "Anna", None), (bert, None, "bert@x.de")),  # names
            result((MID, item1), (MID, item2)),  # agenda positions
        ],
    )
    session.keeper_rows = [
        SimpleNamespace(
            principal_id=anna,
            from_at=datetime(2026, 6, 20, 16, 4, tzinfo=UTC),
            to_at=datetime(2026, 6, 20, 17, 30, tzinfo=UTC),
            from_agenda_item_id=item1,
            to_agenda_item_id=gone,
        ),
        SimpleNamespace(
            principal_id=bert,
            from_at=datetime(2026, 6, 20, 17, 30, tzinfo=UTC),
            to_at=None,
            from_agenda_item_id=item2,
            to_agenda_item_id=None,
        ),
        # The planned handover is not part of the minutes.
        SimpleNamespace(
            principal_id=anna,
            from_at=None,
            to_at=None,
            from_agenda_item_id=None,
            to_agenda_item_id=None,
        ),
    ]
    header = await _service(session)._header_meta(_meeting(protokollant_id=bert))
    assert header.keepers == [
        KeeperLine(name="Anna", from_time="18:04", to_time="19:30", from_top=1, to_top=None),
        KeeperLine(name="bert@x.de", from_time="19:30", to_time=None, from_top=2, to_top=None),
    ]
    assert header.protokollant == "Anna, bert@x.de"


async def test_header_falls_back_to_the_assigned_protokollant() -> None:
    session = _AttendanceSession([])
    session.scalar_results = ["Frau Schmidt"]
    header = await _service(session)._header_meta(_meeting(protokollant_id=uuid4()))
    assert header.keepers == []
    assert header.protokollant == "Frau Schmidt"


def test_start_uses_the_real_start_else_the_planned_one() -> None:
    svc = _service(FakeSession())
    started = _meeting(started_at=datetime(2026, 6, 20, 16, 7, 33, tzinfo=UTC))
    assert svc._start_of(started) == (date(2026, 6, 20), time(18, 7))
    assert svc._start_of(_meeting()) == (date(2026, 6, 20), time(18, 0))
    assert svc._start_of(None) == (None, None)


def test_frontmatter_carries_keepers_excused_and_started_at() -> None:
    text = build_protocol_document(
        ProtocolDoc(
            title="GV",
            gremium_name=None,
            cd_variant=None,
            date=date(2026, 6, 20),
            start_time=time(18, 4),
            started_at="2026-06-20 18:04",
            protokollant="Anna, Bert",
            keepers=[
                KeeperLine(name="Anna", from_time="18:04", to_time="19:30", from_top=1, to_top=2),
                KeeperLine(name='Bert "B"', from_time="19:30"),
            ],
            present=["Anna"],
            excused=["Cora"],
            absent=["Dirk"],
            markdown="# Eins",
        )
    )
    assert 'started_at: "2026-06-20 18:04"' in text
    assert 'protokoll: "Anna, Bert"' in text
    assert (
        "keepers:\n"
        '  - name: "Anna"\n'
        '    from: "18:04"\n'
        '    to: "19:30"\n'
        '    from_top: "1"\n'
        '    to_top: "2"\n'
        '  - name: "Bert \\"B\\""\n'
        '    from: "19:30"\n'
    ) in text
    assert 'entschuldigt:\n  - "Cora"\n' in text


def test_frontmatter_without_keepers_keeps_the_legacy_shape() -> None:
    text = build_protocol_document(
        ProtocolDoc(
            title="GV", gremium_name=None, cd_variant=None, date=None, markdown="x"
        )
    )
    assert "keepers" not in text
    assert "started_at" not in text
    assert "entschuldigt" not in text
