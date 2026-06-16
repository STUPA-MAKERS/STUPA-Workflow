"""Abdeckungs-Tests für das Live-Vote/Meeting-Modul (service/agenda/attendance/router).

Treibt die vier Service-/Router-Dateien gegen DB-lose Fakes auf ~100 % Zeilen-/
Branch-Abdeckung: alle Cursor-/Such-/RBAC-/Tally-/Anwesenheits-/Tagesordnungs-Pfade
sowie der REST-Router (Auth fail-closed, problem+json, Hintergrund-Mail, Vote-/
Agenda-Steuerung). WS-Pfade liegen in der bestehenden WS-Suite; hier nur die
``_authorize``-/``_serve``-Verzweigungen über schlanke WS-Doubles.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.livevote import router as router_mod
from app.modules.livevote import service as service_mod
from app.modules.livevote.agenda_service import AgendaService, _title_of
from app.modules.livevote.attendance_service import AttendanceService
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.connection import (
    WS_FORBIDDEN,
    WS_NOT_FOUND,
    WS_UNAUTHENTICATED,
)
from app.modules.livevote.locks import InMemoryLocker
from app.modules.livevote.models import Meeting
from app.modules.livevote.router import (
    _authorize,
    _serve,
    get_agenda_service,
    get_attendance_service,
    get_broker_rest,
    get_broker_ws,
    get_locker_ws,
    get_meeting_service,
    get_meeting_service_ws,
    get_voting_service,
    get_voting_service_ws,
)
from app.modules.livevote.service import (
    BrokerPublisher,
    MeetingService,
    _decode_cursor,
    _decode_offset,
    _encode_cursor,
    _encode_offset,
)
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)

# pytest-asyncio läuft im ``auto``-Modus (pyproject) — async-Tests brauchen keinen
# expliziten Marker; sync TestClient-Tests bleiben unmarkiert.


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Result:
    """Ergebnis-Double: ``scalar_one_or_none`` / ``scalars().all()`` / ``all()`` /
    ``first()`` aus einer Zeilen-Liste."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


def res(*rows: Any) -> _Result:
    return _Result(list(rows))


class _Bind:
    class dialect:  # noqa: D106
        name = "sqlite"


class _QueueSession:
    """``AsyncSession``-Double mit getrennten FIFO-Queues je Zugriffsart.

    * ``execute(stmt)`` → nächstes ``_Result`` aus ``executes`` (Default leer)
    * ``scalars(stmt)`` → nächstes ``_Scalars`` aus ``scalars_q`` (Default leer)
    * ``scalar(stmt)`` → nächster Wert aus ``scalar_q`` (Default ``None``)
    * ``get(model, id)`` → nächster Wert aus ``get_q`` (Default ``None``)
    """

    def __init__(
        self,
        *,
        executes: list[_Result] | None = None,
        scalars_q: list[list[Any]] | None = None,
        scalar_q: list[Any] | None = None,
        get_q: list[Any] | None = None,
        bind: bool = False,
    ) -> None:
        self.executes = list(executes or [])
        self.scalars_q = list(scalars_q or [])
        self.scalar_q = list(scalar_q or [])
        self.get_q = list(get_q or [])
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = 0
        self.flushed = 0
        self.bind = _Bind if bind else None
        self.last_statement: Any = None

    async def execute(self, _stmt: Any) -> _Result:
        self.last_statement = _stmt
        return self.executes.pop(0) if self.executes else _Result([])

    async def scalars(self, _stmt: Any) -> _Scalars:
        return _Scalars(self.scalars_q.pop(0) if self.scalars_q else [])

    async def scalar(self, _stmt: Any) -> Any:
        return self.scalar_q.pop(0) if self.scalar_q else None

    async def get(self, _model: Any, _ident: Any) -> Any:
        return self.get_q.pop(0) if self.get_q else None

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flushed += 1
        for obj in self.added:
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime(2026, 6, 8, tzinfo=UTC)

    async def commit(self) -> None:
        self.committed += 1


def _principal(*perms: str, roles: list[str] | None = None, sub: str = "p") -> Principal:
    return Principal(sub=sub, permissions=set(perms), roles=roles or [])


def _admin() -> Principal:
    return _principal("meeting.manage", roles=["admin"], sub="mgr")


def _meeting(*, status: str = "planned", gremium_id: UUID | None = None) -> Meeting:
    m = Meeting(gremium_id=gremium_id or uuid4(), title="GV")
    m.id = uuid4()
    m.status = status
    m.date = None
    m.start_time = None
    m.end_time = None
    m.closed_at = None
    m.active_application_id = None
    m.protokollant_id = None
    m.created_at = datetime(2026, 6, 8, tzinfo=UTC)
    return m


# =========================================================================== #
# service.py — Cursor-Helfer
# =========================================================================== #
def test_encode_decode_cursor_roundtrip() -> None:
    ts = datetime(2026, 6, 16, 18, 30)
    mid = uuid4()
    cur = _encode_cursor(ts, mid)
    assert _decode_cursor(cur) == (ts, mid)


def test_decode_cursor_empty_is_none() -> None:
    assert _decode_cursor(None) is None
    assert _decode_cursor("") is None


def test_decode_cursor_invalid_raises() -> None:
    with pytest.raises(BadRequestError):
        _decode_cursor("not-valid-base64-!@#")


def test_encode_decode_offset_roundtrip() -> None:
    assert _decode_offset(_encode_offset(40)) == 40


def test_decode_offset_empty_is_zero() -> None:
    assert _decode_offset(None) == 0
    assert _decode_offset("") == 0


def test_decode_offset_wrong_tag_raises() -> None:
    bad = _encode_cursor(datetime(2026, 6, 16), uuid4())  # kein "o|"-Tag
    with pytest.raises(BadRequestError):
        _decode_offset(bad)


def test_decode_offset_negative_raises() -> None:
    import base64

    raw = base64.urlsafe_b64encode(b"o|-5").decode()
    with pytest.raises(BadRequestError):
        _decode_offset(raw)


def test_decode_offset_garbage_raises() -> None:
    with pytest.raises(BadRequestError):
        _decode_offset("###not-base64###")


# =========================================================================== #
# service.py — _to_out (Defaults / votes-None)
# =========================================================================== #
def test_to_out_defaults_votes_none() -> None:
    m = _meeting()
    out = MeetingService._to_out(m)
    assert out.votes == []
    assert out.can_manage is False
    assert out.can_control is False


# =========================================================================== #
# service.py — RBAC-Helfer
# =========================================================================== #
async def test_can_manage_global_permission_shortcuts() -> None:
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc.can_manage(uuid4(), _principal("meeting.manage")) is True


async def test_can_manage_via_gremium_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    gid = uuid4()

    async def _perms(_s, _sub, _perm, now=None):  # noqa: ANN001, ANN202
        return {gid}

    monkeypatch.setattr(service_mod, "gremium_ids_with_permission", _perms)
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc.can_manage(gid, _principal()) is True
    assert await svc.can_manage(uuid4(), _principal()) is False


async def test_is_protokollant_none_and_match() -> None:
    m = _meeting()
    # protokollant_id None → False, ohne DB-Query.
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc._is_protokollant(m, _principal()) is False
    # gesetzt + _principal_id matcht.
    pid = uuid4()
    m.protokollant_id = pid
    svc2 = MeetingService(_QueueSession(executes=[res(pid)]))  # type: ignore[arg-type]
    assert await svc2._is_protokollant(m, _principal()) is True


async def test_can_write_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    m = _meeting()
    # 1) via can_manage (Admin) → True ohne Query.
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc.can_write(m, _admin()) is True

    # 2) nicht manage, aber Protokollant.
    async def _no_perm(_s, _sub, _perm, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(service_mod, "gremium_ids_with_permission", _no_perm)
    m.protokollant_id = uuid4()
    svc2 = MeetingService(_QueueSession(executes=[res(m.protokollant_id)]))  # type: ignore[arg-type]
    assert await svc2.can_write(m, _principal()) is True

    # 3) nicht manage, nicht Protokollant, aber protocol.write-Rolle.
    gid = m.gremium_id

    async def _write(_s, _sub, perm, now=None):  # noqa: ANN001, ANN202
        return {gid} if perm == "protocol.write" else set()

    monkeypatch.setattr(service_mod, "gremium_ids_with_permission", _write)
    m.protokollant_id = None
    svc3 = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc3.can_write(m, _principal()) is True


async def test_can_manage_votes_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    m = _meeting()
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc.can_manage_votes(m, _admin()) is True

    async def _none(_s, _sub, _perm, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(service_mod, "gremium_ids_with_permission", _none)
    # Protokollant-Zweig.
    m.protokollant_id = uuid4()
    svc2 = MeetingService(_QueueSession(executes=[res(m.protokollant_id)]))  # type: ignore[arg-type]
    assert await svc2.can_manage_votes(m, _principal()) is True

    # vote.manage-Rolle-Zweig.
    gid = m.gremium_id

    async def _vm(_s, _sub, perm, now=None):  # noqa: ANN001, ANN202
        return {gid} if perm == "vote.manage" else set()

    monkeypatch.setattr(service_mod, "gremium_ids_with_permission", _vm)
    m.protokollant_id = None
    svc3 = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc3.can_manage_votes(m, _principal()) is True


async def test_can_vote_admin() -> None:
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc.can_vote(_meeting(), _principal(roles=["admin"])) is True


async def test_can_vote_via_role(monkeypatch: pytest.MonkeyPatch) -> None:
    m = _meeting()
    gid = m.gremium_id

    async def _cast(_s, _sub, perm, now=None):  # noqa: ANN001, ANN202
        return {gid} if perm == "vote.cast" else set()

    monkeypatch.setattr(service_mod, "gremium_ids_with_permission", _cast)
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc.can_vote(m, _principal()) is True


async def test_can_vote_via_delegation(monkeypatch: pytest.MonkeyPatch) -> None:
    m = _meeting()

    async def _none(_s, _sub, _perm, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(service_mod, "gremium_ids_with_permission", _none)
    # _delegated_meeting_ids(voting_only=True) liefert die Sitzung.
    svc = MeetingService(_QueueSession(executes=[res(m.id)]))  # type: ignore[arg-type]
    assert await svc.can_vote(m, _principal()) is True


async def test_can_vote_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    m = _meeting()

    async def _none(_s, _sub, _perm, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(service_mod, "gremium_ids_with_permission", _none)
    svc = MeetingService(_QueueSession(executes=[res()]))  # type: ignore[arg-type]
    assert await svc.can_vote(m, _principal()) is False


async def test_is_member_admin_and_member(monkeypatch: pytest.MonkeyPatch) -> None:
    gid = uuid4()
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc.is_member(gid, _principal(roles=["admin"])) is True

    async def _members(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return {gid}

    monkeypatch.setattr(service_mod, "gremium_member_ids", _members)
    svc2 = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc2.is_member(gid, _principal()) is True
    assert await svc2.is_member(uuid4(), _principal()) is False


async def test_is_participant_member(monkeypatch: pytest.MonkeyPatch) -> None:
    gid = uuid4()

    async def _members(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return {gid}

    monkeypatch.setattr(service_mod, "gremium_member_ids", _members)
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc.is_participant(uuid4(), gid, _principal()) is True


async def test_is_participant_view_all() -> None:
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert (
        await svc.is_participant(
            uuid4(), uuid4(), _principal("meeting.view_all", sub="v")
        )
        is True
    )


async def test_is_participant_delegation(monkeypatch: pytest.MonkeyPatch) -> None:
    mid = uuid4()

    async def _none(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(service_mod, "gremium_member_ids", _none)
    # is_member False (kein view_all) → _delegated_meeting_ids liefert mid.
    svc = MeetingService(_QueueSession(executes=[res(mid)]))  # type: ignore[arg-type]
    assert await svc.is_participant(mid, uuid4(), _principal()) is True


async def test_delegated_meeting_ids_voting_only_branch() -> None:
    mid = uuid4()
    svc = MeetingService(_QueueSession(executes=[res(mid)]))  # type: ignore[arg-type]
    assert await svc._delegated_meeting_ids("sub", voting_only=True) == {mid}


async def test_visible_gremium_ids_admin_none() -> None:
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc._visible_gremium_ids(_principal(roles=["admin"])) is None
    assert await svc._visible_gremium_ids(_principal("meeting.manage")) is None
    assert await svc._visible_gremium_ids(_principal("meeting.view_all")) is None


async def test_visible_gremium_ids_member_union_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mg, pg = uuid4(), uuid4()

    async def _members(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return {mg}

    monkeypatch.setattr(service_mod, "gremium_member_ids", _members)
    # _substitute_pool_gremium_ids → pg.
    svc = MeetingService(_QueueSession(executes=[res(pg)]))  # type: ignore[arg-type]
    assert await svc._visible_gremium_ids(_principal()) == {mg, pg}


async def test_get_not_found() -> None:
    svc = MeetingService(_QueueSession(executes=[res()]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc._get(uuid4())


async def test_protocol_id_returns_value() -> None:
    pid = uuid4()
    svc = MeetingService(_QueueSession(executes=[res(pid)]))  # type: ignore[arg-type]
    assert await svc._protocol_id(uuid4()) == pid


async def test_name_for_none_and_value() -> None:
    assert await MeetingService._name_for(_QueueSession(), None) is None  # type: ignore[arg-type]
    from types import SimpleNamespace

    row = SimpleNamespace(display_name="Alice", email="a@x")
    sess = _QueueSession(get_q=[row])
    assert await MeetingService._name_for(sess, uuid4()) == "Alice"  # type: ignore[arg-type]
    # display_name None → email-Fallback.
    row2 = SimpleNamespace(display_name=None, email="b@x")
    sess2 = _QueueSession(get_q=[row2])
    assert await MeetingService._name_for(sess2, uuid4()) == "b@x"  # type: ignore[arg-type]
    # row None → None.
    assert await MeetingService._name_for(_QueueSession(), uuid4()) is None  # type: ignore[arg-type]


async def test_gremium_name_for_none_and_value() -> None:
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc._gremium_name_for(None) is None
    from types import SimpleNamespace

    svc2 = MeetingService(_QueueSession(get_q=[SimpleNamespace(name="StuPa")]))  # type: ignore[arg-type]
    assert await svc2._gremium_name_for(uuid4()) == "StuPa"
    svc3 = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc3._gremium_name_for(uuid4()) is None


async def test_emit_without_principal() -> None:
    m = _meeting()
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    out = await svc._emit(m, None)
    assert out.can_manage is False
    assert out.gremium_id == m.gremium_id


# =========================================================================== #
# service.py — _votes_for / _present_by_meeting / _vote_tallies
# =========================================================================== #
def _vote_row(
    *,
    meeting_id: UUID | None,
    status: str = "open",
    secret: bool = False,
    result: str | None = None,
    eligible: int = 0,
) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        id=uuid4(),
        meeting_id=meeting_id,
        application_id=uuid4(),
        agenda_item_id=uuid4(),
        question="Q?",
        eligible_group=str(uuid4()),
        config={"options": ["yes", "no"], "majorityRule": "simple", "secret": secret},
        status=status,
        result=result,
        eligible_count=eligible,
        created_at=datetime(2026, 6, 8, tzinfo=UTC),
    )


async def test_votes_for_empty() -> None:
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc._votes_for([]) == {}


async def test_present_by_meeting_empty() -> None:
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc._present_by_meeting([]) == {}


async def test_absent_delegated_by_meeting_empty() -> None:
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc._absent_delegated_by_meeting([]) == {}


async def test_absent_delegated_by_meeting_groups_rows() -> None:
    # FIX 2: liefert {(meeting, str(gremium)): Anzahl} für aktive Stimm-Delegationen
    # abwesender Delegierender.
    mid, gid = uuid4(), uuid4()
    sess = _QueueSession(executes=[res((mid, gid, 2))])
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc._absent_delegated_by_meeting([mid])
    assert out == {(mid, str(gid)): 2}


async def test_vote_tallies_empty() -> None:
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc._vote_tallies([]) == {}


async def test_votes_for_closed_revealed() -> None:
    mid = uuid4()
    vrow = _vote_row(meeting_id=mid, status="closed", result="passed", eligible=2)
    # execute()-Reihenfolge: _votes_for selektiert Votes (scalars().all()), dann
    # _vote_tallies (open ballots, secret ballots — je execute().all()), zuletzt
    # _present_by_meeting (execute().all()).
    sess = _QueueSession(
        executes=[
            res(vrow),  # votes
            res((vrow.id, "yes"), (vrow.id, "no")),  # open ballots
            res(),  # secret ballots
            res((mid, 2)),  # present_by_meeting
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc._votes_for([mid])
    assert mid in out
    item = out[mid][0]
    assert item.revealed is True
    assert item.counts == {"yes": 1, "no": 1}
    assert item.voted == 2
    assert item.present == 2


async def test_votes_for_secret_open_hidden() -> None:
    mid = uuid4()
    vrow = _vote_row(meeting_id=mid, status="open", secret=True, eligible=3)
    sess = _QueueSession(
        executes=[
            res(vrow),  # votes
            res(),  # open ballots (leer; secret)
            res((vrow.id, "yes")),  # secret ballots
            res((mid, 3)),  # present
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc._votes_for([mid])
    item = out[mid][0]
    assert item.revealed is False  # geheim + offen → verdeckt
    assert item.counts == {}
    assert item.leading is None
    assert item.voted == 1


async def test_votes_for_open_all_voted_revealed() -> None:
    mid = uuid4()
    vrow = _vote_row(meeting_id=mid, status="open", secret=False, eligible=2)
    sess = _QueueSession(
        executes=[
            res(vrow),  # votes
            res((vrow.id, "yes"), (vrow.id, "yes")),  # open ballots
            res(),  # secret ballots
            res((mid, 2)),  # present=2, voted=2 → revealed
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc._votes_for([mid])
    item = out[mid][0]
    assert item.revealed is True
    assert item.counts == {"yes": 2, "no": 0}


async def test_votes_for_open_proxy_denominator_hides_until_proxy_votes() -> None:
    # FIX 2: 2 Anwesende + 1 Stimm-Delegation eines Abwesenden → expected=3. Mit nur
    # 2 Stimmen (Anwesende) ist die Proxy-Stimme noch offen → verdeckt.
    mid = uuid4()
    gid = uuid4()
    vrow = _vote_row(meeting_id=mid, status="open", secret=False, eligible=5)
    vrow.eligible_group = str(gid)
    sess = _QueueSession(
        executes=[
            res(vrow),  # votes
            res((vrow.id, "yes"), (vrow.id, "yes")),  # open ballots: 2
            res(),  # secret ballots
            res((mid, 2)),  # present=2
            res((mid, gid, 1)),  # 1 Proxy-Stimme abwesender Delegierender → expected=3
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc._votes_for([mid])
    item = out[mid][0]
    assert item.revealed is False  # 2 < expected 3 → verdeckt
    assert item.counts == {}


async def test_votes_for_open_not_all_voted_hidden() -> None:
    mid = uuid4()
    vrow = _vote_row(meeting_id=mid, status="open", secret=False, eligible=5)
    sess = _QueueSession(
        executes=[
            res(vrow),  # votes
            res((vrow.id, "yes")),  # open ballots: 1
            res(),  # secret ballots
            res((mid, 3)),  # present=3 > voted=1 → hidden
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc._votes_for([mid])
    item = out[mid][0]
    assert item.revealed is False
    assert item.counts == {}


async def test_votes_for_skips_unbound_vote() -> None:
    # v.meeting_id None → wird in _votes_for übersprungen (continue).
    vrow = _vote_row(meeting_id=None)
    sess = _QueueSession(
        executes=[
            res(vrow),  # votes
            res(),  # open ballots
            res(),  # secret ballots
            res(),  # present
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    # _votes_for([some id]) — present_by_meeting wird mit der ID aufgerufen, aber
    # der Vote selbst hat meeting_id None und wird übersprungen.
    out = await svc._votes_for([uuid4()])
    assert out == {}


async def test_votes_for_config_not_dict() -> None:
    # v.config kein dict (hier eine VoteConfig-Instanz) → cfg-Zweig ``else {}`` in
    # _votes_for greift (opts leer, secret False); _vote_tallies validiert es trotzdem.
    from app.shared.config_schemas import VoteConfig

    mid = uuid4()
    vrow = _vote_row(meeting_id=mid, status="closed", result="passed")
    vrow.config = VoteConfig.model_validate(
        {"options": ["yes", "no"], "majorityRule": "simple"}
    )
    sess = _QueueSession(
        executes=[
            res(vrow),  # votes
            res(),  # open ballots
            res(),  # secret ballots
            res((mid, 0)),  # present
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc._votes_for([mid])
    item = out[mid][0]
    # cfg.get("options") aus der (Nicht-dict-)VoteConfig → leere Liste.
    assert item.options == []


async def test_vote_tallies_failed_reason_set() -> None:
    # status=closed + result gesetzt → failed_reason berechnet.
    mid = uuid4()
    vrow = _vote_row(meeting_id=mid, status="closed", result="rejected", eligible=10)
    sess = _QueueSession(
        executes=[
            res((vrow.id, "no"), (vrow.id, "no")),  # open ballots
            res(),  # secret ballots
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc._vote_tallies([vrow])
    counts, leading, reason = out[vrow.id]
    assert counts == {"yes": 0, "no": 2}
    assert reason in ("quorum", "majority")


# =========================================================================== #
# service.py — list / list_filter_gremien / list_timeline / _search_timeline
# =========================================================================== #
async def test_list_admin_no_filter() -> None:
    m = _meeting()
    sess = _QueueSession(
        executes=[
            res(m),  # select(Meeting) list
            res(),  # _decorate: proto rows
            res((m.gremium_id, "StuPa")),  # gremium names
            res(),  # _votes_for: votes
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc.list(_admin())
    assert [o.id for o in out] == [m.id]
    assert out[0].gremium_name == "StuPa"


async def test_list_with_gremium_filter_and_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = _meeting()

    async def _members(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return {m.gremium_id}

    monkeypatch.setattr(service_mod, "gremium_member_ids", _members)
    sess = _QueueSession(
        executes=[
            res(m.gremium_id),  # _substitute_pool_gremium_ids (in _visible)
            res(),  # _delegated_meeting_ids
            res(m),  # select(Meeting)
            res(),  # proto rows
            res((m.gremium_id, "G")),  # gremium names
            # _decorate non-admin perms:
            res(),  # session.manage
            res(),  # protocol.write
            res(),  # vote.manage
            res(),  # vote.cast
            res(uuid4()),  # _principal_id
            res(),  # _votes_for: votes
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc.list(_principal(), m.gremium_id)
    assert [o.id for o in out] == [m.id]


async def test_decorate_empty() -> None:
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc._decorate([], _admin()) == []


async def test_decorate_non_admin_protokollant_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = _meeting()
    my = uuid4()
    m.protokollant_id = my
    from types import SimpleNamespace

    async def _none(_s, _sub, _perm, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(service_mod, "gremium_ids_with_permission", _none)
    # Die vier Perm-Queries laufen über das gemockte ``gremium_ids_with_permission``
    # und verbrauchen KEINE execute()-Ergebnisse. Übrige execute()-Reihenfolge:
    # proto, gremium-names, protokollant-names, _principal_id, _votes_for(votes).
    sess = _QueueSession(
        executes=[
            res(),  # proto rows
            res((m.gremium_id, "G")),  # gremium names
            res((my, "Bob", "bob@x")),  # protokollant names
            res(my),  # _principal_id → matcht protokollant
            res(),  # _votes_for: votes
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc._decorate([m], _principal())
    assert out[0].protokollant_name == "Bob"
    assert out[0].can_write is True  # via is_prot
    assert out[0].can_manage_votes is True
    _ = SimpleNamespace  # keep import tidy


async def test_list_filter_gremien_admin_sorted() -> None:
    g1, g2 = uuid4(), uuid4()
    sess = _QueueSession(executes=[res((g1, "Zeta"), (g2, "alpha"))])
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc.list_filter_gremien(_admin())
    assert [g.name for g in out] == ["alpha", "Zeta"]


async def test_list_filter_gremien_non_admin_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    g1 = uuid4()

    async def _members(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return {g1}

    monkeypatch.setattr(service_mod, "gremium_member_ids", _members)
    sess = _QueueSession(
        executes=[
            res(),  # _substitute_pool
            res(),  # _delegated
            res((g1, "Beta")),  # rows
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc.list_filter_gremien(_principal())
    assert [g.name for g in out] == ["Beta"]


async def test_list_timeline_upcoming_pagination() -> None:
    m1, m2 = _meeting(status="live"), _meeting(status="planned")
    ts1 = datetime(2026, 6, 16, 9, 0)
    ts2 = datetime(2026, 6, 17, 9, 0)
    # limit=1 → 2 Zeilen geladen (has_more True), nur 1 zurück.
    sess = _QueueSession(
        executes=[
            res((m1, ts1), (m2, ts2)),  # timeline rows (limit+1)
            res(),  # _decorate proto
            res((m1.gremium_id, "G")),  # gremium names
            res(),  # _votes_for
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    page = await svc.list_timeline(_admin(), direction="upcoming", limit=1)
    assert len(page.items) == 1
    assert page.next_cursor is not None


async def test_list_timeline_past_with_cursor_and_gremium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = _meeting(status="closed")
    ts = datetime(2026, 6, 10, 9, 0)
    cursor = _encode_cursor(datetime(2026, 6, 16, 9, 0), uuid4())

    async def _members(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return {m.gremium_id}

    monkeypatch.setattr(service_mod, "gremium_member_ids", _members)
    sess = _QueueSession(
        executes=[
            res(m.gremium_id),  # _substitute_pool (in _visible)
            res(),  # _delegated
            res((m, ts)),  # rows (1 ≤ limit → no more)
            res(),  # proto
            res((m.gremium_id, "G")),  # names
            res(),  # session.manage
            res(),  # protocol.write
            res(),  # vote.manage
            res(),  # vote.cast
            res(uuid4()),  # principal_id
            res(),  # votes
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    page = await svc.list_timeline(
        _principal(),
        direction="past",
        cursor=cursor,
        limit=20,
        gremium_id=m.gremium_id,
    )
    assert [i.id for i in page.items] == [m.id]
    assert page.next_cursor is None


async def test_list_timeline_empty_rows_no_cursor() -> None:
    sess = _QueueSession(executes=[res()])  # no rows
    svc = MeetingService(sess)  # type: ignore[arg-type]
    page = await svc.list_timeline(_admin(), direction="upcoming")
    assert page.items == []
    assert page.next_cursor is None


async def test_list_timeline_past_without_cursor() -> None:
    # past-Richtung OHNE Cursor → ``if cur is not None``-False-Zweig (650->653).
    m = _meeting(status="closed")
    ts = datetime(2026, 6, 10, 9, 0)
    sess = _QueueSession(
        executes=[
            res((m, ts)),  # rows
            res(),  # proto
            res((m.gremium_id, "G")),  # names
            res(),  # votes
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    page = await svc.list_timeline(_admin(), direction="past")
    assert [i.id for i in page.items] == [m.id]


async def test_list_timeline_search_branch() -> None:
    m = _meeting()
    sess = _QueueSession(
        executes=[
            res(m),  # search rows (scalars().all())
            res(),  # proto
            res((m.gremium_id, "G")),  # names
            res(),  # votes
        ],
        bind=True,
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    page = await svc.list_timeline(_admin(), direction="upcoming", q="  GV  ")
    assert [i.id for i in page.items] == [m.id]


async def test_search_timeline_pagination_and_gremium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1, m2 = _meeting(), _meeting(gremium_id=None)
    m2.gremium_id = m1.gremium_id

    async def _members(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return {m1.gremium_id}

    monkeypatch.setattr(service_mod, "gremium_member_ids", _members)
    sess = _QueueSession(
        executes=[
            res(m1.gremium_id),  # _substitute_pool
            res(),  # _delegated
            res(m1, m2),  # search rows (limit+1 → has_more)
            res(),  # proto
            res((m1.gremium_id, "G")),  # names
            res(),  # session.manage
            res(),  # protocol.write
            res(),  # vote.manage
            res(),  # vote.cast
            res(uuid4()),  # principal_id
            res(),  # votes
        ],
        bind=True,
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    page = await svc.list_timeline(
        _principal(), direction="upcoming", q="GV", limit=1, gremium_id=m1.gremium_id
    )
    assert len(page.items) == 1
    assert page.next_cursor is not None


# =========================================================================== #
# service.py — create / _resolve_protokollant
# =========================================================================== #
async def test_create_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(_s, _sub, _perm, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(service_mod, "gremium_ids_with_permission", _none)
    from app.modules.livevote.schemas import MeetingCreate

    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError):
        await svc.create(
            MeetingCreate(
                gremiumId=uuid4(), title="GV", date=date(2026, 6, 20), startTime=time(18, 0)
            ),
            _principal(),
        )


async def test_create_ok_no_protokollant() -> None:
    from app.modules.livevote.schemas import MeetingCreate

    sess = _QueueSession()
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc.create(
        MeetingCreate(
            gremiumId=uuid4(), title="GV", date=date(2026, 6, 20), startTime=time(18, 0)
        ),
        _admin(),
    )
    assert out.status == "planned"
    assert sess.committed == 1


async def test_resolve_protokollant_none() -> None:
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc._resolve_protokollant(uuid4(), None) is None


async def test_resolve_protokollant_not_found() -> None:
    svc = MeetingService(_QueueSession(get_q=[None]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc._resolve_protokollant(uuid4(), uuid4())


async def test_resolve_protokollant_not_member(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    async def _none(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(service_mod, "gremium_member_ids", _none)
    svc = MeetingService(_QueueSession(get_q=[SimpleNamespace(sub="x")]))  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError):
        await svc._resolve_protokollant(uuid4(), uuid4())


async def test_resolve_protokollant_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    gid = uuid4()

    async def _member(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return {gid}

    monkeypatch.setattr(service_mod, "gremium_member_ids", _member)
    pid = uuid4()
    svc = MeetingService(_QueueSession(get_q=[SimpleNamespace(sub="x")]))  # type: ignore[arg-type]
    assert await svc._resolve_protokollant(gid, pid) == pid


# =========================================================================== #
# service.py — patch (alle Verzweigungen)
# =========================================================================== #
async def test_patch_wants_manage_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    m = _meeting()

    async def _none(_s, _sub, _perm, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(service_mod, "gremium_ids_with_permission", _none)
    from app.modules.livevote.schemas import MeetingPatch

    svc = MeetingService(_QueueSession(executes=[res(m)]))  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError):
        await svc.patch(m.id, MeetingPatch(date=date(2026, 7, 1)), _principal())


async def test_patch_wants_write_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    m = _meeting()

    async def _none(_s, _sub, _perm, now=None):  # noqa: ANN001, ANN202
        return set()

    async def _nomember(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(service_mod, "gremium_ids_with_permission", _none)
    monkeypatch.setattr(service_mod, "gremium_member_ids", _nomember)
    from app.modules.livevote.schemas import MeetingPatch

    # _get(meeting), then can_write: can_manage (perm none), _is_protokollant
    # (protokollant_id None → no query), protocol.write perm (none).
    svc = MeetingService(_QueueSession(executes=[res(m)]))  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError):
        await svc.patch(m.id, MeetingPatch(status="closed"), _principal())


async def test_patch_closed_reopen_conflict() -> None:
    m = _meeting(status="closed")
    from app.modules.livevote.schemas import MeetingPatch

    svc = MeetingService(_QueueSession(executes=[res(m)]))  # type: ignore[arg-type]
    with pytest.raises(ConflictError):
        await svc.patch(m.id, MeetingPatch(status="live"), _admin())


async def test_patch_closed_settings_frozen() -> None:
    m = _meeting(status="closed")
    from app.modules.livevote.schemas import MeetingPatch

    svc = MeetingService(_QueueSession(executes=[res(m)]))  # type: ignore[arg-type]
    with pytest.raises(ConflictError):
        await svc.patch(m.id, MeetingPatch(date=date(2026, 7, 1)), _admin())


async def test_patch_end_before_start_bad_request() -> None:
    m = _meeting()
    from app.modules.livevote.schemas import MeetingPatch

    svc = MeetingService(_QueueSession(executes=[res(m)]))  # type: ignore[arg-type]
    with pytest.raises(BadRequestError):
        await svc.patch(
            m.id,
            MeetingPatch(startTime=time(18, 0), endTime=time(17, 0)),
            _admin(),
        )


async def test_patch_protokollant_finalized_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = _meeting()

    async def _final(self, _mid):  # noqa: ANN001, ANN202
        return True

    monkeypatch.setattr(MeetingService, "_protocol_final", _final)
    from app.modules.livevote.schemas import MeetingPatch

    svc = MeetingService(_QueueSession(executes=[res(m)]))  # type: ignore[arg-type]
    with pytest.raises(ConflictError):
        await svc.patch(m.id, MeetingPatch(protokollantId=uuid4()), _admin())


async def test_patch_protokollant_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    m = _meeting()
    new_pid = uuid4()

    async def _final(self, _mid):  # noqa: ANN001, ANN202
        return False

    async def _member(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return {m.gremium_id}

    monkeypatch.setattr(MeetingService, "_protocol_final", _final)
    monkeypatch.setattr(service_mod, "gremium_member_ids", _member)
    from app.modules.livevote.schemas import MeetingPatch

    # _get; _resolve_protokollant get → row; _emit name/gremium/can_* (admin shortcut);
    # _votes_for empty.
    sess = _QueueSession(
        executes=[res(m)],
        get_q=[SimpleNamespace(sub="x")],
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc.patch(m.id, MeetingPatch(protokollantId=new_pid), _admin())
    assert m.protokollant_id == new_pid
    assert out.protokollant_id == new_pid


async def test_patch_going_live_without_protokollant_conflict() -> None:
    m = _meeting()
    m.protokollant_id = None
    from app.modules.livevote.schemas import MeetingPatch

    svc = MeetingService(_QueueSession(executes=[res(m)]))  # type: ignore[arg-type]
    with pytest.raises(ConflictError):
        await svc.patch(m.id, MeetingPatch(status="live"), _admin())


async def test_patch_going_live_ok_with_publisher() -> None:
    m = _meeting()
    m.protokollant_id = uuid4()
    from app.modules.livevote.schemas import MeetingPatch

    class _Pub:
        def __init__(self) -> None:
            self.states: list[Any] = []

        async def meeting_state(self, out: Any) -> None:
            self.states.append(out)

    pub = _Pub()
    # _get; _emit (name get → None, gremium get → None) + _votes_for empty.
    sess = _QueueSession(executes=[res(m)])
    svc = MeetingService(sess, pub)  # type: ignore[arg-type]
    out = await svc.patch(m.id, MeetingPatch(status="live", activeApplicationId=uuid4()), _admin())
    assert out.status == "live"
    assert len(pub.states) == 1


async def test_patch_close_stamps_closed_at() -> None:
    m = _meeting()
    from app.modules.livevote.schemas import MeetingPatch

    svc = MeetingService(_QueueSession(executes=[res(m)]))  # type: ignore[arg-type]
    out = await svc.patch(m.id, MeetingPatch(status="closed"), _admin())
    assert out.status == "closed"
    assert m.closed_at is not None


async def test_patch_set_times_and_end() -> None:
    m = _meeting()
    from app.modules.livevote.schemas import MeetingPatch

    svc = MeetingService(_QueueSession(executes=[res(m)]))  # type: ignore[arg-type]
    out = await svc.patch(
        m.id, MeetingPatch(startTime=time(18, 0), endTime=time(20, 0)), _admin()
    )
    assert m.start_time == time(18, 0)
    assert m.end_time == time(20, 0)
    assert out.start_time == time(18, 0)


async def test_patch_set_date() -> None:
    # Datum-Patch auf eine geplante Sitzung (greift Zeile 866: meeting.date = payload.date).
    m = _meeting()
    from app.modules.livevote.schemas import MeetingPatch

    svc = MeetingService(_QueueSession(executes=[res(m)]))  # type: ignore[arg-type]
    out = await svc.patch(m.id, MeetingPatch(date=date(2026, 7, 1)), _admin())
    assert m.date == date(2026, 7, 1)
    assert out.date == date(2026, 7, 1)


# =========================================================================== #
# service.py — broadcast_state / open_vote / agenda_item_has_vote / misc
# =========================================================================== #
async def test_broadcast_state_with_publisher() -> None:
    m = _meeting()

    class _Pub:
        def __init__(self) -> None:
            self.n = 0

        async def meeting_state(self, _out: Any) -> None:
            self.n += 1

    pub = _Pub()
    sess = _QueueSession(executes=[res(m)])
    svc = MeetingService(sess, pub)  # type: ignore[arg-type]
    await svc.broadcast_state(m.id, _admin())
    assert pub.n == 1


async def test_broadcast_state_no_publisher() -> None:
    m = _meeting()
    sess = _QueueSession(executes=[res(m)])
    svc = MeetingService(sess)  # type: ignore[arg-type]
    await svc.broadcast_state(m.id, _admin())  # kein Fehler, kein Broadcast


async def test_protocol_final_true_false() -> None:
    svc = MeetingService(_QueueSession(scalar_q=["final"]))  # type: ignore[arg-type]
    assert await svc._protocol_final(uuid4()) is True
    svc2 = MeetingService(_QueueSession(scalar_q=["draft"]))  # type: ignore[arg-type]
    assert await svc2._protocol_final(uuid4()) is False


async def test_open_vote_returns_row() -> None:
    from app.modules.voting.models import Vote

    vote = Vote(application_id=uuid4(), eligible_group="g", config={})
    svc = MeetingService(_QueueSession(executes=[res(vote)]))  # type: ignore[arg-type]
    assert await svc.open_vote(uuid4()) is vote


async def test_agenda_item_has_vote() -> None:
    svc = MeetingService(_QueueSession(executes=[res(uuid4())]))  # type: ignore[arg-type]
    assert await svc.agenda_item_has_vote(uuid4()) is True
    svc2 = MeetingService(_QueueSession(executes=[res()]))  # type: ignore[arg-type]
    assert await svc2.agenda_item_has_vote(uuid4()) is False


async def test_agenda_item_has_vote_excludes_cancelled() -> None:
    # FIX 1 (#cancel-reopen): das Guard-Statement MUSS abgebrochene Votes
    # ausblenden (status != 'cancelled') — sonst blockt ein einmal abgebrochener
    # Antrags-Vote das Neu-Eröffnen für immer.
    sess = _QueueSession(executes=[res()])
    svc = MeetingService(sess)  # type: ignore[arg-type]
    await svc.agenda_item_has_vote(uuid4())
    rendered = str(
        sess.last_statement.compile(  # type: ignore[attr-defined]
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "status" in rendered and "cancelled" in rendered


async def test_application_state_kind() -> None:
    svc = MeetingService(_QueueSession(scalar_q=["vote"]))  # type: ignore[arg-type]
    assert await svc.application_state_kind(uuid4()) == "vote"


async def test_gremium_quorum_percent() -> None:
    svc = MeetingService(_QueueSession(executes=[res(50)]))  # type: ignore[arg-type]
    assert await svc.gremium_quorum_percent(uuid4()) == 50


async def test_vote_eligible_count() -> None:
    p1, p2 = uuid4(), uuid4()
    rows = res(
        (p1, ["vote.cast"]),
        (p2, ["vote.cast"]),
        (p1, ["vote.cast"]),  # Duplikat → set dedupliziert
        (uuid4(), None),  # ohne vote.cast (perms None) → nicht gezählt
    )
    svc = MeetingService(_QueueSession(executes=[rows]))  # type: ignore[arg-type]
    assert await svc.vote_eligible_count(uuid4()) == 2


async def test_assert_can_read_delegation_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    m = _meeting()

    async def _none(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(service_mod, "gremium_member_ids", _none)
    # _get → m; _substitute_pool → empty; visible doesn't contain gremium;
    # _delegated_meeting_ids → m.id (allowed).
    sess = _QueueSession(executes=[res(m), res(), res(m.id)])
    svc = MeetingService(sess)  # type: ignore[arg-type]
    await svc.assert_can_read(m.id, _principal())  # kein Fehler


# =========================================================================== #
# agenda_service.py
# =========================================================================== #
def test_title_of_variants() -> None:
    assert _title_of(None) is None
    assert _title_of({}) is None
    assert _title_of({"title": "  Hi  "}) == "Hi"
    assert _title_of({"title": "   "}) is None
    assert _title_of({"title": 5}) is None


def _agenda_item(
    *,
    application_id: UUID | None = None,
    title: str | None = None,
    position: int = 0,
    non_public: bool = False,
    body: str | None = None,
) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        id=uuid4(),
        meeting_id=uuid4(),
        application_id=application_id,
        title=title,
        body=body,
        position=position,
        non_public=non_public,
    )


def _app_row(*, state_id: UUID | None, title: str | None = "App") -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        id=uuid4(),
        current_state_id=state_id,
        data={"title": title} if title else {},
        created_at=datetime(2026, 6, 8, tzinfo=UTC),
    )


def _state_row(*, gremium_id: UUID, kind: str = "vote") -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        id=uuid4(),
        kind=kind,
        config={"gremiumId": str(gremium_id)},
        label_i18n={"de": "Beschluss"},
    )


async def test_agenda_meeting_not_found() -> None:
    svc = AgendaService(_QueueSession(executes=[res()]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc._meeting(uuid4())


async def test_agenda_item_not_found() -> None:
    svc = AgendaService(_QueueSession(executes=[res()]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.item(uuid4(), uuid4())


async def test_agenda_item_found() -> None:
    item = _agenda_item()
    svc = AgendaService(_QueueSession(executes=[res(item)]))  # type: ignore[arg-type]
    assert await svc.item(uuid4(), item.id) is item


async def test_vote_states_filters_by_gremium() -> None:
    gid = uuid4()
    s_match = _state_row(gremium_id=gid)
    s_other = _state_row(gremium_id=uuid4())
    s_nodict = _state_row(gremium_id=gid)
    s_nodict.config = None
    svc = AgendaService(_QueueSession(scalars_q=[[s_match, s_other, s_nodict]]))  # type: ignore[arg-type]
    out = await svc._vote_states(gid)
    assert list(out.keys()) == [s_match.id]


async def test_agenda_list_empty() -> None:
    m = _meeting()
    sess = _QueueSession(executes=[res(m)], scalars_q=[[]])
    svc = AgendaService(sess)  # type: ignore[arg-type]
    assert await svc.list(m.id) == []


async def test_agenda_list_with_application_and_freetext() -> None:
    m = _meeting()
    gid = m.gremium_id
    state = _state_row(gremium_id=gid)
    app = _app_row(state_id=state.id, title="Mein Antrag")
    item_app = _agenda_item(application_id=app.id, position=0)
    item_free = _agenda_item(title="Freitext-TOP", position=1, body="Notiz")
    sess = _QueueSession(
        executes=[res(m)],  # _meeting
        scalars_q=[
            [item_app, item_free],  # agenda items
            [app],  # apps
            [state],  # states
        ],
    )
    svc = AgendaService(sess)  # type: ignore[arg-type]
    out = await svc.list(m.id)
    assert out[0].title == "Mein Antrag"
    assert out[0].state_label == {"de": "Beschluss"}
    assert out[1].title == "Freitext-TOP"
    assert out[1].state_label is None


async def test_agenda_list_app_without_state() -> None:
    m = _meeting()
    app = _app_row(state_id=None, title="Antrag")
    item = _agenda_item(application_id=app.id)
    sess = _QueueSession(
        executes=[res(m)],
        scalars_q=[
            [item],  # items
            [app],  # apps
            # state_ids empty → states={} (no scalars call)
        ],
    )
    svc = AgendaService(sess)  # type: ignore[arg-type]
    out = await svc.list(m.id)
    assert out[0].state_label is None
    assert out[0].title == "Antrag"


async def test_agenda_list_app_missing() -> None:
    # item references an application_id, but apps dict empty → app None branch.
    m = _meeting()
    item = _agenda_item(application_id=uuid4())
    sess = _QueueSession(
        executes=[res(m)],
        scalars_q=[
            [item],  # items
            [],  # apps empty
        ],
    )
    svc = AgendaService(sess)  # type: ignore[arg-type]
    out = await svc.list(m.id)
    assert out[0].title is None  # app None → r.title (None)


async def test_set_body_not_found() -> None:
    svc = AgendaService(_QueueSession(executes=[res()]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.set_body(uuid4(), uuid4(), body="x")


async def test_set_body_updates_all_fields() -> None:
    m = _meeting()
    item = _agenda_item(application_id=None, title="old")
    sess = _QueueSession(
        executes=[res(item), res(m)],  # set_body lookup, then list()._meeting
        scalars_q=[[]],  # list() agenda items empty
    )
    svc = AgendaService(sess)  # type: ignore[arg-type]
    await svc.set_body(m.id, item.id, body="**md**", title="new", non_public=True)
    assert item.body == "**md**"
    assert item.title == "new"
    assert item.non_public is True
    assert sess.committed == 1


async def test_set_body_title_ignored_for_application_top() -> None:
    m = _meeting()
    item = _agenda_item(application_id=uuid4(), title="orig")
    sess = _QueueSession(
        executes=[res(item), res(m)],
        scalars_q=[[]],
    )
    svc = AgendaService(sess)  # type: ignore[arg-type]
    await svc.set_body(m.id, item.id, title="ignored")
    assert item.title == "orig"  # Antrag-TOP erbt Titel → title nicht gesetzt


async def test_reorder() -> None:
    m = _meeting()
    a = _agenda_item(position=5)
    b = _agenda_item(position=9)
    sess = _QueueSession(
        executes=[res(m)],  # list()._meeting
        scalars_q=[
            [a, b],  # reorder rows
            [],  # list() items
        ],
    )
    svc = AgendaService(sess)  # type: ignore[arg-type]
    # b zuerst, dann a, dann eine unbekannte ID (None-Zweig).
    await svc.reorder(m.id, [b.id, a.id, uuid4()])
    assert b.position == 0
    assert a.position == 1


async def test_assignable_no_vote_states() -> None:
    m = _meeting()
    sess = _QueueSession(executes=[res(m)], scalars_q=[[]])  # _meeting, _vote_states empty
    svc = AgendaService(sess)  # type: ignore[arg-type]
    assert await svc.assignable(m.id) == []


async def test_assignable_filters_existing_and_maps() -> None:
    m = _meeting()
    gid = m.gremium_id
    state = _state_row(gremium_id=gid)
    app_in = _app_row(state_id=state.id, title="Neu")
    app_existing = _app_row(state_id=state.id, title="Schon dran")
    app_nostate = _app_row(state_id=None, title="Keiner")
    app_nostate.current_state_id = None
    sess = _QueueSession(
        executes=[
            res(m),  # _meeting
            res(app_existing.id),  # existing application_ids (scalars().all())
        ],
        scalars_q=[
            [state],  # _vote_states
            [app_existing.id],  # existing → set via scalars().all()
            [app_in, app_existing, app_nostate],  # candidate apps
        ],
    )
    # NOTE: existing uses session.scalars(...).all(); assignable apps uses scalars too.
    sess2 = _QueueSession(
        executes=[res(m)],
        scalars_q=[
            [state],  # _vote_states
            [app_existing.id],  # existing application_ids
            [app_in, app_existing, app_nostate],  # apps in vote-state
        ],
    )
    svc = AgendaService(sess2)  # type: ignore[arg-type]
    out = await svc.assignable(m.id)
    titles = [o.title for o in out]
    assert "Neu" in titles
    assert "Schon dran" not in titles  # bereits auf der TO
    # app_nostate has current_state_id None → state None branch.
    assert "Keiner" in titles
    _ = sess


async def test_next_position_empty_and_existing() -> None:
    svc = AgendaService(_QueueSession(executes=[res()]))  # type: ignore[arg-type]
    assert await svc._next_position(uuid4()) == 0
    svc2 = AgendaService(_QueueSession(executes=[res(4)]))  # type: ignore[arg-type]
    assert await svc2._next_position(uuid4()) == 5


async def test_add_freetext() -> None:
    m = _meeting()
    sess = _QueueSession(
        executes=[
            res(m),  # _meeting
            res(None),  # _next_position max → 0
            res(m),  # list()._meeting
        ],
        scalars_q=[[]],  # list() items
    )
    svc = AgendaService(sess)  # type: ignore[arg-type]
    await svc.add(m.id, title="  Begrüßung  ")
    assert sess.added[0].title == "Begrüßung"
    assert sess.committed == 1


async def test_add_application_not_found() -> None:
    m = _meeting()
    sess = _QueueSession(executes=[res(m)], get_q=[None])
    svc = AgendaService(sess)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.add(m.id, application_id=uuid4())


async def test_add_application_not_in_vote_state() -> None:
    m = _meeting()
    app = _app_row(state_id=uuid4())
    sess = _QueueSession(
        executes=[res(m)],
        scalars_q=[[]],  # _vote_states empty → app.current_state_id not in {} → conflict
        get_q=[app],
    )
    svc = AgendaService(sess)  # type: ignore[arg-type]
    with pytest.raises(ConflictError):
        await svc.add(m.id, application_id=app.id)


async def test_add_application_new() -> None:
    m = _meeting()
    gid = m.gremium_id
    state = _state_row(gremium_id=gid)
    app = _app_row(state_id=state.id)
    sess = _QueueSession(
        executes=[
            res(m),  # _meeting
            res(),  # existing lookup → None
            res(None),  # _next_position
            res(m),  # list()._meeting
        ],
        scalars_q=[
            [state],  # _vote_states
            [],  # list() items
        ],
        get_q=[app],
    )
    svc = AgendaService(sess)  # type: ignore[arg-type]
    await svc.add(m.id, application_id=app.id)
    assert sess.added and sess.added[0].application_id == app.id
    assert sess.committed == 1


async def test_add_application_already_present() -> None:
    m = _meeting()
    gid = m.gremium_id
    state = _state_row(gremium_id=gid)
    app = _app_row(state_id=state.id)
    sess = _QueueSession(
        executes=[
            res(m),  # _meeting
            res(uuid4()),  # existing lookup → present → no add
            res(m),  # list()._meeting
        ],
        scalars_q=[
            [state],  # _vote_states
            [],  # list() items
        ],
        get_q=[app],
    )
    svc = AgendaService(sess)  # type: ignore[arg-type]
    await svc.add(m.id, application_id=app.id)
    assert sess.added == []  # nichts hinzugefügt
    assert sess.committed == 0


async def test_remove_existing_and_missing() -> None:
    m = _meeting()
    item = _agenda_item()
    sess = _QueueSession(
        executes=[res(item), res(m)],  # remove lookup, list()._meeting
        scalars_q=[[]],  # list() items
    )
    svc = AgendaService(sess)  # type: ignore[arg-type]
    await svc.remove(m.id, item.id)
    assert sess.deleted == [item]
    assert sess.committed == 1

    # missing → no delete/commit.
    sess2 = _QueueSession(
        executes=[res(), res(m)],
        scalars_q=[[]],
    )
    svc2 = AgendaService(sess2)  # type: ignore[arg-type]
    await svc2.remove(m.id, uuid4())
    assert sess2.deleted == []
    assert sess2.committed == 0


# =========================================================================== #
# attendance_service.py
# =========================================================================== #
def _member(*, sub: str = "sub-1", display_name: str = "Alice") -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        id=uuid4(), sub=sub, display_name=display_name, email=f"{sub}@x"
    )


async def test_attendance_meeting_not_found() -> None:
    svc = AttendanceService(_QueueSession(executes=[res()]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc._meeting(uuid4())


async def test_attendance_members() -> None:
    gid = uuid4()
    m1, m2 = _member(sub="a"), _member(sub="b")
    sess = _QueueSession(executes=[res(m1, m2)])
    svc = AttendanceService(sess)  # type: ignore[arg-type]
    out = await svc.members(gid)
    assert [o.principal_id for o in out] == [m1.id, m2.id]


async def test_roster_maps_records_and_self() -> None:
    from types import SimpleNamespace

    meeting = _meeting()
    member = _member(sub="me", display_name="Me")
    other = _member(sub="other", display_name="Other")
    rec = SimpleNamespace(principal_id=member.id, status="present", source="self")
    sess = _QueueSession(
        executes=[
            res(meeting),  # _meeting
            res(member, other),  # _current_members
            res(rec),  # attendance records
        ]
    )
    svc = AttendanceService(sess)  # type: ignore[arg-type]
    out = await svc.roster(meeting.id, "me")
    by_pid = {o.principal_id: o for o in out}
    assert by_pid[member.id].status == "present"
    assert by_pid[member.id].is_self is True
    assert by_pid[other.id].status is None  # kein Record
    assert by_pid[other.id].is_self is False


async def test_set_self_not_member_forbidden() -> None:
    meeting = _meeting(status="live")
    member = _member(sub="someone-else")
    sess = _QueueSession(
        executes=[
            res(meeting),  # _meeting
            res(member),  # _current_members (requester not among them)
        ]
    )
    svc = AttendanceService(sess)  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError):
        await svc.set_self(meeting.id, "present", "i-am-not-a-member")


async def test_set_self_inserts_new() -> None:
    meeting = _meeting(status="live")
    member = _member(sub="me")
    sess = _QueueSession(
        executes=[
            res(meeting),  # _meeting
            res(member),  # _current_members (set_self)
            res(),  # _upsert existing → None → insert
            res(meeting),  # roster _meeting
            res(member),  # roster _current_members
            res(),  # roster records
        ]
    )
    svc = AttendanceService(sess)  # type: ignore[arg-type]
    out = await svc.set_self(meeting.id, "present", "me")
    assert sess.added and sess.added[0].status == "present"
    assert sess.added[0].source == "self"
    assert out[0].principal_id == member.id


async def test_set_self_updates_existing() -> None:
    from types import SimpleNamespace

    meeting = _meeting(status="live")
    member = _member(sub="me")
    existing = SimpleNamespace(status="absent", source="lead")
    sess = _QueueSession(
        executes=[
            res(meeting),  # _meeting
            res(member),  # _current_members
            res(existing),  # _upsert existing
            res(meeting),  # roster _meeting
            res(member),  # roster members
            res(existing),  # roster records (has principal_id? no—just for mapping)
        ]
    )
    # existing has no principal_id; give it one for roster mapping safety.
    existing.principal_id = member.id
    svc = AttendanceService(sess)  # type: ignore[arg-type]
    await svc.set_self(meeting.id, "present", "me")
    assert existing.status == "present"
    assert existing.source == "self"


async def test_set_for_not_member_not_found() -> None:
    meeting = _meeting(status="live")
    member = _member()
    sess = _QueueSession(
        executes=[
            res(meeting),  # _meeting
            res(member),  # _current_members
        ]
    )
    svc = AttendanceService(sess)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.set_for(meeting.id, uuid4(), "absent", "lead-sub")


async def test_set_for_ok() -> None:
    meeting = _meeting(status="live")
    member = _member(sub="target")
    sess = _QueueSession(
        executes=[
            res(meeting),  # _meeting
            res(member),  # _current_members
            res(),  # _upsert existing → None → insert
            res(meeting),  # roster _meeting
            res(member),  # roster members
            res(),  # roster records
        ]
    )
    svc = AttendanceService(sess)  # type: ignore[arg-type]
    out = await svc.set_for(meeting.id, member.id, "excused", "lead-sub")
    assert sess.added[0].source == "lead"
    assert sess.added[0].status == "excused"
    assert out[0].principal_id == member.id


# =========================================================================== #
# router.py — DI-Factories
# =========================================================================== #
def test_router_di_factories() -> None:
    from types import SimpleNamespace

    fake_app = SimpleNamespace(state=SimpleNamespace())
    req = SimpleNamespace(app=fake_app)
    ws = SimpleNamespace(app=fake_app)
    # ohne broker/locker auf state → Fallbacks (Singletons im Router-Modul).
    assert get_broker_rest(req) is router_mod._FALLBACK_BROKER  # type: ignore[arg-type]
    assert get_broker_ws(ws) is router_mod._FALLBACK_BROKER  # type: ignore[arg-type]
    assert get_locker_ws(ws) is router_mod._FALLBACK_LOCKER  # type: ignore[arg-type]

    # mit broker auf state → genau dieser.
    broker = InMemoryBroker()
    locker = InMemoryLocker()
    fake_app2 = SimpleNamespace(state=SimpleNamespace(broker=broker, locker=locker))
    req2 = SimpleNamespace(app=fake_app2)
    ws2 = SimpleNamespace(app=fake_app2)
    assert get_broker_rest(req2) is broker  # type: ignore[arg-type]
    assert get_broker_ws(ws2) is broker  # type: ignore[arg-type]
    assert get_locker_ws(ws2) is locker  # type: ignore[arg-type]

    sess = object()
    assert isinstance(get_meeting_service(sess, broker), MeetingService)  # type: ignore[arg-type]
    assert isinstance(get_meeting_service_ws(sess, broker), MeetingService)  # type: ignore[arg-type]
    assert isinstance(get_attendance_service(sess), AttendanceService)  # type: ignore[arg-type]
    assert isinstance(get_agenda_service(sess), AgendaService)  # type: ignore[arg-type]
    assert get_voting_service(sess) is not None  # type: ignore[arg-type]
    assert get_voting_service_ws(sess) is not None  # type: ignore[arg-type]


# =========================================================================== #
# router.py — REST via TestClient (Service-Fakes über dependency_overrides)
# =========================================================================== #
def _meeting_out(
    *,
    status: str = "live",
    can_write: bool = True,
    can_manage_votes: bool = True,
    gremium_id: UUID | None = None,
) -> Any:
    from app.modules.livevote.schemas import MeetingOut

    return MeetingOut(
        id=uuid4(),
        gremiumId=gremium_id or uuid4(),
        title="GV",
        status=status,  # type: ignore[arg-type]
        createdAt=datetime(2026, 6, 8, tzinfo=UTC),
        canWrite=can_write,
        canManageVotes=can_manage_votes,
    )


class _FakeMeetingService:
    """MeetingService-Double für die Router-Tests (nur die genutzten Methoden)."""

    def __init__(self) -> None:
        self.session = _QueueSession()
        self._can_manage = True
        self._meeting_out = _meeting_out()
        self.created: list[Any] = []
        self.deleted: list[Any] = []
        self.broadcasts = 0

    async def can_manage(self, gremium_id: UUID, principal: Principal) -> bool:
        return self._can_manage

    async def create(self, payload: Any, principal: Principal) -> Any:
        out = _meeting_out(status="planned")
        self.created.append(out)
        return out

    async def list(self, principal: Principal, gremium_id: UUID | None = None) -> list[Any]:
        return [self._meeting_out]

    async def list_timeline(self, principal: Principal, **kw: Any) -> Any:
        from app.modules.livevote.schemas import MeetingPage

        return MeetingPage(items=[self._meeting_out], nextCursor=None)

    async def list_filter_gremien(self, principal: Principal) -> list[Any]:
        from app.modules.livevote.schemas import MeetingGremiumOut

        return [MeetingGremiumOut(id=uuid4(), name="StuPa")]

    async def assert_can_read(self, meeting_id: UUID, principal: Principal) -> None:
        return None

    async def get(self, meeting_id: UUID, principal: Principal | None = None) -> Any:
        return self._meeting_out

    async def delete(self, meeting_id: UUID, principal: Principal) -> None:
        self.deleted.append(meeting_id)

    async def patch(self, meeting_id: UUID, payload: Any, principal: Principal) -> Any:
        return self._meeting_out

    async def broadcast_state(self, meeting_id: UUID, principal: Principal) -> None:
        self.broadcasts += 1

    async def agenda_item_has_vote(self, item_id: UUID) -> bool:
        return False

    async def application_state_kind(self, application_id: UUID) -> str | None:
        return "vote"

    async def gremium_quorum_percent(self, gremium_id: UUID) -> int | None:
        return None

    async def vote_eligible_count(self, gremium_id: UUID) -> int:
        return 7


class _FakeAttendanceService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def members(self, gremium_id: UUID) -> list[Any]:
        from app.modules.livevote.schemas import MeetingMemberOut

        return [MeetingMemberOut(principalId=uuid4(), displayName="A", email="a@x")]

    async def roster(self, meeting_id: UUID, requester_sub: str) -> list[Any]:
        self.calls.append("roster")
        return []

    async def set_self(self, meeting_id: UUID, status: Any, requester_sub: str) -> list[Any]:
        self.calls.append("set_self")
        return []

    async def set_for(
        self, meeting_id: UUID, principal_id: UUID, status: Any, requester_sub: str
    ) -> list[Any]:
        self.calls.append("set_for")
        return []


class _FakeAgendaService:
    def __init__(self) -> None:
        from types import SimpleNamespace

        self.item_row = SimpleNamespace(id=uuid4(), application_id=None)
        self.calls: list[str] = []

    async def list(self, meeting_id: UUID) -> list[Any]:
        self.calls.append("list")
        return []

    async def assignable(self, meeting_id: UUID) -> list[Any]:
        self.calls.append("assignable")
        return []

    async def item(self, meeting_id: UUID, item_id: UUID) -> Any:
        return self.item_row

    async def add(self, meeting_id: UUID, application_id, title, non_public=False) -> list[Any]:  # noqa: ANN001
        self.calls.append("add")
        return []

    async def remove(self, meeting_id: UUID, item_id: UUID) -> list[Any]:
        self.calls.append("remove")
        return []

    async def reorder(self, meeting_id: UUID, item_ids: list[UUID]) -> list[Any]:
        self.calls.append("reorder")
        return []

    async def set_body(  # noqa: ANN001
        self, meeting_id, item_id, body=None, title=None, non_public=None
    ) -> list[Any]:
        self.calls.append("set_body")
        return []


class _FakeVotingService:
    def __init__(self) -> None:
        from types import SimpleNamespace

        self.created: list[Any] = []
        self.deleted: list[Any] = []
        self._vote = SimpleNamespace(id=uuid4(), meeting_id=None)

    async def create(self, application_id, payload, *, meeting_id, agenda_item_id):  # noqa: ANN001
        self.created.append((application_id, meeting_id, agenda_item_id))
        return self._vote

    async def open(self, vote_id, *, now):  # noqa: ANN001
        from app.modules.voting.schemas import TallyOut, VoteOut
        from app.shared.config_schemas import VoteConfig

        return VoteOut(
            id=vote_id,
            applicationId=uuid4(),
            meetingId=None,
            eligibleGroup="g",
            config=VoteConfig.model_validate(
                {"options": ["yes", "no"], "majorityRule": "simple"}
            ),
            status="open",  # type: ignore[arg-type]
            secret=False,
            tally=TallyOut(counts={}, eligible=0, quorumMet=True),
        )

    async def delete(self, vote_id, *, meeting_id):  # noqa: ANN001
        self.deleted.append((vote_id, meeting_id))


@pytest.fixture
def fakes() -> dict[str, Any]:
    return {
        "meeting": _FakeMeetingService(),
        "attendance": _FakeAttendanceService(),
        "agenda": _FakeAgendaService(),
        "voting": _FakeVotingService(),
    }


@pytest.fixture
def app(fakes: dict[str, Any]) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_meeting_service] = lambda: fakes["meeting"]
    application.dependency_overrides[get_attendance_service] = lambda: fakes["attendance"]
    application.dependency_overrides[get_agenda_service] = lambda: fakes["agenda"]
    application.dependency_overrides[get_voting_service] = lambda: fakes["voting"]
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _login(app: FastAPI, *perms: str, roles: list[str] | None = None) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="p", permissions=set(perms), roles=roles or []
    )


# ---- create_meeting --------------------------------------------------------
def test_create_meeting_requires_auth(client: TestClient) -> None:
    assert client.post("/api/meetings", json={}).status_code == 401


def test_create_meeting_ok_schedules_mail(app: FastAPI, client: TestClient) -> None:
    _login(app, "meeting.manage")
    body = {
        "gremiumId": str(uuid4()),
        "title": "GV",
        "date": "2026-06-20",
        "startTime": "18:00:00",
    }
    r = client.post("/api/meetings", json=body)
    assert r.status_code == 200
    assert r.json()["status"] == "planned"


# ---- list_meeting_members --------------------------------------------------
def test_list_meeting_members_forbidden(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._can_manage = False
    _login(app, "x")
    r = client.get(f"/api/gremien/{uuid4()}/meeting-members")
    assert r.status_code == 403
    assert r.headers["content-type"] == "application/problem+json"


def test_list_meeting_members_ok(app: FastAPI, client: TestClient) -> None:
    _login(app, "meeting.manage")
    r = client.get(f"/api/gremien/{uuid4()}/meeting-members")
    assert r.status_code == 200
    assert len(r.json()) == 1


# ---- list / timeline / filter-gremien --------------------------------------
def test_list_meetings_ok(app: FastAPI, client: TestClient) -> None:
    _login(app)
    r = client.get("/api/meetings")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_list_meetings_timeline_ok(app: FastAPI, client: TestClient) -> None:
    _login(app)
    r = client.get("/api/meetings/timeline?direction=upcoming&limit=5")
    assert r.status_code == 200
    assert r.json()["nextCursor"] is None


def test_list_meeting_filter_gremien_ok(app: FastAPI, client: TestClient) -> None:
    _login(app)
    r = client.get("/api/meetings/gremien")
    assert r.status_code == 200
    assert r.json()[0]["name"] == "StuPa"


# ---- get / delete ----------------------------------------------------------
def test_get_meeting_ok(app: FastAPI, client: TestClient) -> None:
    _login(app)
    r = client.get(f"/api/meetings/{uuid4()}")
    assert r.status_code == 200


def test_delete_meeting_ok(app: FastAPI, client: TestClient, fakes) -> None:
    _login(app)
    mid = uuid4()
    r = client.delete(f"/api/meetings/{mid}")
    assert r.status_code == 204
    assert fakes["meeting"].deleted == [mid]


# ---- patch -----------------------------------------------------------------
def test_patch_meeting_non_live(app: FastAPI, client: TestClient, fakes) -> None:
    # patch returns status "live" by default; force a non-live to skip protocol branch.
    fakes["meeting"]._meeting_out = _meeting_out(status="planned")
    _login(app)
    r = client.patch(f"/api/meetings/{uuid4()}", json={"status": "planned"})
    assert r.status_code == 200
    assert r.json()["status"] == "planned"


def test_patch_meeting_going_live_creates_protocol(
    app: FastAPI, client: TestClient, fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    # patch returns live; the router then creates the protocol and re-reads.
    fakes["meeting"]._meeting_out = _meeting_out(status="live")

    class _FakeProtocolService:
        def __init__(self, session: Any) -> None:
            self.session = session

        async def get_or_create(self, meeting_id: UUID, *, author: str) -> Any:
            return object()

    import app.modules.protocol.service as protocol_service_mod

    monkeypatch.setattr(protocol_service_mod, "ProtocolService", _FakeProtocolService)
    _login(app)
    r = client.patch(f"/api/meetings/{uuid4()}", json={"status": "live"})
    assert r.status_code == 200
    assert r.json()["status"] == "live"


# ---- attendance ------------------------------------------------------------
def test_list_attendance_ok(app: FastAPI, client: TestClient, fakes) -> None:
    _login(app)
    r = client.get(f"/api/meetings/{uuid4()}/attendance")
    assert r.status_code == 200
    assert "roster" in fakes["attendance"].calls


def test_set_own_attendance_ok(app: FastAPI, client: TestClient, fakes) -> None:
    _login(app)
    r = client.put(f"/api/meetings/{uuid4()}/attendance/me", json={"status": "present"})
    assert r.status_code == 200
    assert "set_self" in fakes["attendance"].calls


def test_set_member_attendance_forbidden(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(can_write=False)
    _login(app)
    r = client.put(
        f"/api/meetings/{uuid4()}/attendance/{uuid4()}", json={"status": "absent"}
    )
    assert r.status_code == 403


def test_set_member_attendance_ok(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(can_write=True)
    _login(app)
    r = client.put(
        f"/api/meetings/{uuid4()}/attendance/{uuid4()}", json={"status": "present"}
    )
    assert r.status_code == 200
    assert "set_for" in fakes["attendance"].calls


# ---- agenda ----------------------------------------------------------------
def test_list_agenda_ok(app: FastAPI, client: TestClient, fakes) -> None:
    _login(app)
    r = client.get(f"/api/meetings/{uuid4()}/agenda")
    assert r.status_code == 200
    assert "list" in fakes["agenda"].calls


def test_list_assignable_ok(app: FastAPI, client: TestClient, fakes) -> None:
    _login(app)
    r = client.get(f"/api/meetings/{uuid4()}/agenda/assignable")
    assert r.status_code == 200
    assert "assignable" in fakes["agenda"].calls


def test_add_agenda_item_forbidden(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(can_write=False)
    _login(app)
    r = client.post(f"/api/meetings/{uuid4()}/agenda", json={"title": "TOP"})
    assert r.status_code == 403


def test_add_agenda_item_ok(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(can_write=True)
    _login(app)
    r = client.post(f"/api/meetings/{uuid4()}/agenda", json={"title": "TOP"})
    assert r.status_code == 200
    assert "add" in fakes["agenda"].calls


def test_remove_agenda_item_forbidden(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(can_write=False)
    _login(app)
    r = client.delete(f"/api/meetings/{uuid4()}/agenda/{uuid4()}")
    assert r.status_code == 403


def test_remove_agenda_item_ok(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(can_write=True)
    _login(app)
    r = client.delete(f"/api/meetings/{uuid4()}/agenda/{uuid4()}")
    assert r.status_code == 200
    assert "remove" in fakes["agenda"].calls


def test_reorder_agenda_forbidden(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(can_write=False)
    _login(app)
    r = client.put(
        f"/api/meetings/{uuid4()}/agenda/order", json={"itemIds": [str(uuid4())]}
    )
    assert r.status_code == 403


def test_reorder_agenda_ok(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(can_write=True)
    _login(app)
    r = client.put(
        f"/api/meetings/{uuid4()}/agenda/order", json={"itemIds": [str(uuid4())]}
    )
    assert r.status_code == 200
    assert "reorder" in fakes["agenda"].calls


def test_set_agenda_body_forbidden(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(can_write=False)
    _login(app)
    r = client.patch(f"/api/meetings/{uuid4()}/agenda/{uuid4()}", json={"body": "x"})
    assert r.status_code == 403


def test_set_agenda_body_conflict_when_not_live(
    app: FastAPI, client: TestClient, fakes
) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(status="planned", can_write=True)
    _login(app)
    r = client.patch(f"/api/meetings/{uuid4()}/agenda/{uuid4()}", json={"body": "x"})
    assert r.status_code == 409


def test_set_agenda_body_ok_broadcasts(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(status="live", can_write=True)
    _login(app)
    r = client.patch(
        f"/api/meetings/{uuid4()}/agenda/{uuid4()}", json={"title": "Rename"}
    )
    assert r.status_code == 200
    assert "set_body" in fakes["agenda"].calls
    assert fakes["meeting"].broadcasts == 1


# ---- open_meeting_vote -----------------------------------------------------
def test_open_vote_forbidden(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(can_manage_votes=False)
    _login(app)
    r = client.post(
        f"/api/meetings/{uuid4()}/votes", json={"agendaItemId": str(uuid4())}
    )
    assert r.status_code == 403


def test_open_vote_not_live_conflict(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(status="planned", can_manage_votes=True)
    _login(app)
    r = client.post(
        f"/api/meetings/{uuid4()}/votes", json={"agendaItemId": str(uuid4())}
    )
    assert r.status_code == 409


def test_open_vote_freetext_top_ok(app: FastAPI, client: TestClient, fakes) -> None:
    # item.application_id None → freetext, skip the application_id branches.
    fakes["meeting"]._meeting_out = _meeting_out(status="live", can_manage_votes=True)
    _login(app)
    r = client.post(
        f"/api/meetings/{uuid4()}/votes",
        json={"agendaItemId": str(uuid4()), "question": "Pass?"},
    )
    assert r.status_code == 200
    assert fakes["voting"].created


def test_open_vote_application_top_with_quorum_and_eligible(
    app: FastAPI, client: TestClient, fakes
) -> None:
    from types import SimpleNamespace

    # application TOP with explicit quorum_percent + eligible_count.
    fakes["agenda"].item_row = SimpleNamespace(id=uuid4(), application_id=uuid4())
    fakes["meeting"]._meeting_out = _meeting_out(status="live", can_manage_votes=True)
    _login(app)
    r = client.post(
        f"/api/meetings/{uuid4()}/votes",
        json={
            "agendaItemId": str(uuid4()),
            "quorumPercent": 50,
            "eligibleCount": 9,
        },
    )
    assert r.status_code == 200


def test_open_vote_application_already_has_vote_conflict(
    app: FastAPI, client: TestClient, fakes
) -> None:
    from types import SimpleNamespace

    fakes["agenda"].item_row = SimpleNamespace(id=uuid4(), application_id=uuid4())
    fakes["meeting"]._meeting_out = _meeting_out(status="live", can_manage_votes=True)

    async def _has_vote(item_id: UUID) -> bool:
        return True

    fakes["meeting"].agenda_item_has_vote = _has_vote  # type: ignore[assignment]
    _login(app)
    r = client.post(
        f"/api/meetings/{uuid4()}/votes", json={"agendaItemId": str(uuid4())}
    )
    assert r.status_code == 409


def test_open_vote_application_not_in_vote_state_conflict(
    app: FastAPI, client: TestClient, fakes
) -> None:
    from types import SimpleNamespace

    fakes["agenda"].item_row = SimpleNamespace(id=uuid4(), application_id=uuid4())
    fakes["meeting"]._meeting_out = _meeting_out(status="live", can_manage_votes=True)

    async def _kind(application_id: UUID) -> str | None:
        return "normal"

    fakes["meeting"].application_state_kind = _kind  # type: ignore[assignment]
    _login(app)
    r = client.post(
        f"/api/meetings/{uuid4()}/votes", json={"agendaItemId": str(uuid4())}
    )
    assert r.status_code == 409


def test_open_vote_default_quorum_from_gremium(
    app: FastAPI, client: TestClient, fakes
) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(status="live", can_manage_votes=True)

    async def _quorum(gremium_id: UUID) -> int | None:
        return 60

    fakes["meeting"].gremium_quorum_percent = _quorum  # type: ignore[assignment]
    _login(app)
    r = client.post(
        f"/api/meetings/{uuid4()}/votes", json={"agendaItemId": str(uuid4())}
    )
    assert r.status_code == 200


# ---- delete_meeting_vote ---------------------------------------------------
def test_delete_meeting_vote_forbidden(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(can_manage_votes=False)
    _login(app)
    r = client.delete(f"/api/meetings/{uuid4()}/votes/{uuid4()}")
    assert r.status_code == 403


def test_delete_meeting_vote_ok(app: FastAPI, client: TestClient, fakes) -> None:
    fakes["meeting"]._meeting_out = _meeting_out(can_manage_votes=True)
    _login(app)
    vid = uuid4()
    r = client.delete(f"/api/meetings/{uuid4()}/votes/{vid}")
    assert r.status_code == 200
    assert fakes["voting"].deleted and fakes["voting"].deleted[0][0] == vid


# =========================================================================== #
# router.py — WebSocket _authorize / _serve (ohne echte WS-Verbindung)
# =========================================================================== #
class _FakeWS:
    def __init__(self) -> None:
        self.closed_code: int | None = None
        self.accepted = False
        self.sent: list[Any] = []

    async def close(self, code: int) -> None:
        self.closed_code = code

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: Any) -> None:
        self.sent.append(data)


class _AuthMeetings:
    def __init__(self, *, raise_not_found: bool = False, participant: bool = True) -> None:
        self._raise = raise_not_found
        self._participant = participant

    async def get(self, meeting_id: UUID, principal: Principal | None = None) -> Any:
        if self._raise:
            raise NotFoundError("nope")
        return _meeting_out()

    async def is_participant(self, meeting_id, gremium_id, principal) -> bool:  # noqa: ANN001
        return self._participant


async def test_authorize_unauthenticated() -> None:
    ws = _FakeWS()
    out = await _authorize(ws, uuid4(), None, _AuthMeetings(), beamer=False)  # type: ignore[arg-type]
    assert out is None
    assert ws.closed_code == WS_UNAUTHENTICATED


async def test_authorize_not_found() -> None:
    ws = _FakeWS()
    out = await _authorize(
        ws, uuid4(), _principal(), _AuthMeetings(raise_not_found=True), beamer=False  # type: ignore[arg-type]
    )
    assert out is None
    assert ws.closed_code == WS_NOT_FOUND


async def test_authorize_beamer_needs_manage() -> None:
    ws = _FakeWS()
    out = await _authorize(
        ws, uuid4(), _principal(), _AuthMeetings(), beamer=True  # type: ignore[arg-type]
    )
    assert out is None
    assert ws.closed_code == WS_FORBIDDEN
    assert ws.sent and ws.sent[0]["code"] == "not_eligible"


async def test_authorize_beamer_ok() -> None:
    ws = _FakeWS()
    out = await _authorize(
        ws, uuid4(), _principal("meeting.manage"), _AuthMeetings(), beamer=True  # type: ignore[arg-type]
    )
    assert out is not None


async def test_authorize_voter_not_participant() -> None:
    ws = _FakeWS()
    out = await _authorize(
        ws,  # type: ignore[arg-type]
        uuid4(),
        _principal(),
        _AuthMeetings(participant=False),  # type: ignore[arg-type]
        beamer=False,
    )
    assert out is None
    assert ws.closed_code == WS_FORBIDDEN


async def test_authorize_voter_ok() -> None:
    ws = _FakeWS()
    out = await _authorize(
        ws, uuid4(), _principal(), _AuthMeetings(participant=True), beamer=False  # type: ignore[arg-type]
    )
    assert out is not None


async def test_serve_returns_early_on_unauthorized() -> None:
    # _authorize returns None (unauthenticated) → _serve returns without accept().
    ws = _FakeWS()
    await _serve(
        ws,  # type: ignore[arg-type]
        uuid4(),
        None,
        _AuthMeetings(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        beamer=False,
    )
    assert ws.accepted is False


async def test_serve_accepts_and_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _FakeWS()

    class _FakeConn:
        def __init__(self, *a: Any, **kw: Any) -> None:
            self.ran = False

        async def run(self) -> None:
            self.ran = True

    monkeypatch.setattr(router_mod, "LiveVoteConnection", _FakeConn)
    await _serve(
        ws,  # type: ignore[arg-type]
        uuid4(),
        _principal("meeting.manage"),
        _AuthMeetings(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        InMemoryBroker(),
        InMemoryLocker(),
        beamer=True,
    )
    assert ws.accepted is True


# =========================================================================== #
# router.py — get_ws_principal + WS-Routen (meeting_socket/beamer_socket)
# =========================================================================== #
async def test_get_ws_principal_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.livevote.router import get_ws_principal

    captured: dict[str, Any] = {}

    async def _resolve(ws: Any, session: Any, settings: Any) -> Principal:
        captured["called"] = True
        return _principal("x")

    monkeypatch.setattr(router_mod, "resolve_ws_principal", _resolve)
    out = await get_ws_principal(object(), object(), object())  # type: ignore[arg-type]
    assert captured.get("called") is True
    assert out is not None
    assert out.sub == "p"


async def test_meeting_and_beamer_socket_call_serve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.livevote.router import beamer_socket, meeting_socket

    calls: list[bool] = []

    async def _fake_serve(*a: Any, beamer: bool, **kw: Any) -> None:
        calls.append(beamer)

    monkeypatch.setattr(router_mod, "_serve", _fake_serve)
    mid = uuid4()
    await meeting_socket(object(), mid, None, object(), object(), object(), object())  # type: ignore[arg-type]
    await beamer_socket(object(), mid, None, object(), object(), object(), object())  # type: ignore[arg-type]
    assert calls == [False, True]


# =========================================================================== #
# service.py — Restabdeckung: Publisher / channel / assert_can_read / get /
#              timeline-cursor / delete
# =========================================================================== #
def _capture_broker() -> Any:
    class _Cap:
        def __init__(self) -> None:
            self.messages: list[tuple[str, dict[str, object]]] = []

        async def publish(self, channel: str, message: dict[str, object]) -> None:
            self.messages.append((channel, message))

    return _Cap()


async def test_meeting_channel_helper() -> None:
    from app.modules.livevote.service import meeting_channel

    mid = uuid4()
    assert meeting_channel(mid) == f"meeting:{mid}"


async def test_broker_publisher_all_events() -> None:
    from app.modules.voting.schemas import TallyOut, VoteClosed, VoteOut
    from app.shared.config_schemas import VoteConfig

    broker = _capture_broker()
    pub = BrokerPublisher(broker)
    mid = uuid4()
    cfg = VoteConfig.model_validate(
        {"options": ["yes", "no"], "majorityRule": "simple", "secret": False}
    )
    vote = VoteOut(
        id=uuid4(),
        applicationId=uuid4(),
        meetingId=mid,
        eligibleGroup="g",
        config=cfg,
        status="open",  # type: ignore[arg-type]
        secret=False,
        tally=TallyOut(counts={"yes": 1}, eligible=2, quorumMet=True, leading="yes"),
    )
    await pub.meeting_state(_meeting_out(gremium_id=mid))
    await pub.vote_opened(vote)
    await pub.vote_tally(vote)
    await pub.vote_closed(
        VoteClosed(
            id=uuid4(),
            meetingId=mid,
            result="passed",
            tally=TallyOut(counts={"yes": 1}, eligible=2, quorumMet=True),
        )
    )
    await pub.vote_cancelled(vote)
    assert len(broker.messages) == 5
    types = {m["type"] for _, m in broker.messages}
    assert types == {
        "meeting_state",
        "vote_opened",
        "vote_tally",
        "vote_closed",
        "vote_cancelled",
    }


async def test_broker_publisher_skips_unbound_votes() -> None:
    from app.modules.voting.schemas import TallyOut, VoteClosed, VoteOut
    from app.shared.config_schemas import VoteConfig

    broker = _capture_broker()
    pub = BrokerPublisher(broker)
    cfg = VoteConfig.model_validate(
        {"options": ["yes", "no"], "majorityRule": "simple"}
    )
    unbound = VoteOut(
        id=uuid4(),
        applicationId=uuid4(),
        meetingId=None,
        eligibleGroup="g",
        config=cfg,
        status="open",  # type: ignore[arg-type]
        secret=False,
        tally=TallyOut(counts={}, eligible=0, quorumMet=True),
    )
    await pub.vote_opened(unbound)
    await pub.vote_tally(unbound)
    await pub.vote_cancelled(unbound)
    await pub.vote_closed(
        VoteClosed(
            id=uuid4(),
            meetingId=None,
            result="passed",
            tally=TallyOut(counts={}, eligible=0, quorumMet=True),
        )
    )
    assert broker.messages == []


async def test_assert_can_read_visible_returns() -> None:
    # _visible_gremium_ids None (admin) → frühes return ohne Delegations-Query.
    m = _meeting()
    svc = MeetingService(_QueueSession(executes=[res(m)]))  # type: ignore[arg-type]
    await svc.assert_can_read(m.id, _admin())


async def test_assert_can_read_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    m = _meeting()

    async def _none(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(service_mod, "gremium_member_ids", _none)
    # _get → m; _substitute_pool → empty (visible {}); _delegated → empty → 403.
    svc = MeetingService(_QueueSession(executes=[res(m), res(), res()]))  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError):
        await svc.assert_can_read(m.id, _principal())


async def test_get_with_votes_and_protocol() -> None:
    mid = uuid4()
    m = _meeting()
    m.id = mid
    vrow = _vote_row(meeting_id=mid, status="closed", result="passed", eligible=1)
    sess = _QueueSession(
        executes=[
            res(m),  # _get
            res(vrow),  # _votes_for: votes
            res((vrow.id, "yes")),  # open ballots
            res(),  # secret ballots
            res((mid, 1)),  # present
            res(uuid4()),  # _protocol_id
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    out = await svc.get(mid, _admin())
    assert out.protocol_id is not None
    assert len(out.votes) == 1


async def test_list_timeline_upcoming_with_cursor() -> None:
    m = _meeting(status="planned")
    ts = datetime(2026, 6, 20, 9, 0)
    cursor = _encode_cursor(datetime(2026, 6, 18, 9, 0), uuid4())
    sess = _QueueSession(
        executes=[
            res((m, ts)),  # rows (1 ≤ limit)
            res(),  # proto
            res((m.gremium_id, "G")),  # names
            res(),  # votes
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    page = await svc.list_timeline(
        _admin(), direction="upcoming", cursor=cursor, limit=20
    )
    assert [i.id for i in page.items] == [m.id]
    assert page.next_cursor is None


async def test_delete_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    m = _meeting()

    async def _none(_s, _sub, _perm, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(service_mod, "gremium_ids_with_permission", _none)
    svc = MeetingService(_QueueSession(executes=[res(m)]))  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError):
        await svc.delete(m.id, _principal())


async def test_delete_finalized_requires_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = _meeting(status="closed")

    async def _final(self, _mid):  # noqa: ANN001, ANN202
        return True

    monkeypatch.setattr(MeetingService, "_protocol_final", _final)
    svc = MeetingService(_QueueSession(executes=[res(m)]))  # type: ignore[arg-type]
    # Admin darf zwar verwalten, aber finalisiert → braucht meeting.delete_finalized.
    with pytest.raises(ForbiddenError):
        await svc.delete(m.id, _principal("meeting.manage", sub="mgr"))


async def test_delete_ok_audits(monkeypatch: pytest.MonkeyPatch) -> None:
    m = _meeting()
    calls: list[dict[str, Any]] = []

    async def _final(self, _mid):  # noqa: ANN001, ANN202
        return False

    async def _record(session: Any, **kw: Any) -> None:
        calls.append(kw)

    monkeypatch.setattr(MeetingService, "_protocol_final", _final)
    monkeypatch.setattr(service_mod, "audit_record", _record)
    sess = _QueueSession(executes=[res(m)])
    svc = MeetingService(sess)  # type: ignore[arg-type]
    await svc.delete(m.id, _admin())
    assert sess.deleted == [m]
    assert sess.committed == 1
    assert calls[0]["data"]["finalizedProtocol"] is False


# =========================================================================== #
# attendance_service.py — _ensure_not_closed Raise-Branch
# =========================================================================== #
async def test_attendance_ensure_not_closed_raises() -> None:
    closed = _meeting(status="closed")
    with pytest.raises(ConflictError):
        AttendanceService._ensure_not_closed(closed)
    # Offene Sitzung → kein Fehler.
    AttendanceService._ensure_not_closed(_meeting(status="live"))


async def test_set_self_conflict_when_closed_via_service() -> None:
    closed = _meeting(status="closed")
    sess = _QueueSession(executes=[res(closed)])
    svc = AttendanceService(sess)  # type: ignore[arg-type]
    with pytest.raises(ConflictError):
        await svc.set_self(closed.id, "present", "me")
    assert sess.committed == 0
