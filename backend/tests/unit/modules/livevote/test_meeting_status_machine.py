"""Meeting status machine, start and close side effects, and the A2 agenda summary.

F9 and O13: the status runs only planned, live, closed. A repeat of the current status
is a no-op. Every other change gives 409 ``invalid_status_transition``. O12: the close
gives 409 ``open_vote`` while a vote is open, and it cancels the draft votes. Z7: the
start sets ``started_at`` once. F12: create and update write an audit entry.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.livevote.models import Meeting
from app.modules.livevote.schemas import MeetingCreate, MeetingPatch
from app.modules.livevote.service import MeetingService
from app.modules.livevote.service import lifecycle as lifecycle_mod
from app.shared.errors import ConflictError

STATUSES = ("planned", "live", "closed")
ALLOWED = {("planned", "live"), ("live", "closed")}


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _Session:
    """``AsyncSession`` double: ``execute`` serves a FIFO queue, empty by default."""

    def __init__(self, *results: list[Any], scalars: list[Any] | None = None) -> None:
        self.results = list(results)
        self.scalars = list(scalars or [])
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, _stmt: Any) -> _Rows:
        return _Rows(self.results.pop(0) if self.results else [])

    async def scalar(self, _stmt: Any) -> Any:
        return self.scalars.pop(0) if self.scalars else None

    async def get(self, _model: Any, _ident: Any) -> Any:
        return None

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime(2026, 6, 8, tzinfo=UTC)

    async def commit(self) -> None:
        self.commits += 1


class _Publisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.states: list[Any] = []
        self.cancelled: list[Any] = []

    async def meeting_state(self, out: Any) -> None:
        self.states.append(out)

    async def vote_cancelled(self, vote: Any) -> None:
        if self.fail:
            raise RuntimeError("broker down")
        self.cancelled.append(vote)


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _record(_session: Any, **kw: Any) -> None:
        calls.append(kw)

    monkeypatch.setattr(lifecycle_mod, "audit_record", _record)
    return calls


@pytest.fixture
def voting(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Stand-in for ``VotingService``: the draft cancel and the vote read."""
    import app.modules.voting.service as voting_service_mod

    state = SimpleNamespace(drafts=[], cancel_calls=[], reads=[])

    class _Voting:
        def __init__(self, _session: Any) -> None: ...

        async def cancel_drafts_for_meeting(
            self, meeting_id: UUID, *, now: datetime, actor: str | None
        ) -> list[Any]:
            state.cancel_calls.append((meeting_id, now, actor))
            return list(state.drafts)

        async def get(self, vote_id: UUID) -> Any:
            state.reads.append(vote_id)
            return SimpleNamespace(id=vote_id)

    monkeypatch.setattr(voting_service_mod, "VotingService", _Voting)
    return state


def _admin() -> Principal:
    return Principal(sub="mgr", roles=["admin"])


def _meeting(status: str = "planned") -> Meeting:
    m = Meeting(gremium_id=uuid4(), title="GV")
    m.id = uuid4()
    m.status = status
    m.date = date(2026, 6, 20)
    m.start_time = time(18, 0)
    m.end_time = None
    m.started_at = None
    m.closed_at = None
    m.active_application_id = None
    m.current_agenda_item_id = None
    m.protokollant_id = uuid4()
    m.created_at = datetime(2026, 6, 8, tzinfo=UTC)
    return m


def _service(meeting: Meeting, *extra: list[Any], publisher: Any = None) -> MeetingService:
    # _get, then the open-vote check of a close (empty unless a test queues a vote).
    return MeetingService(_Session([meeting], *extra), publisher)  # type: ignore[arg-type]


@pytest.mark.parametrize("current", STATUSES)
@pytest.mark.parametrize("target", STATUSES)
async def test_status_machine(
    current: str, target: str, audit: list[dict[str, Any]], voting: SimpleNamespace
) -> None:
    m = _meeting(current)
    svc = _service(m)
    if current == target or (current, target) in ALLOWED:
        out = await svc.patch(m.id, MeetingPatch(status=target), _admin())  # type: ignore[arg-type]
        assert out.status == target
        assert m.status == target
        # A no-op status writes no audit entry.
        assert bool(audit) == (current != target)
    else:
        with pytest.raises(ConflictError) as ei:
            await svc.patch(m.id, MeetingPatch(status=target), _admin())  # type: ignore[arg-type]
        assert ei.value.code == "invalid_status_transition"
        assert m.status == current
        assert audit == []


async def test_close_with_open_vote_conflicts(
    audit: list[dict[str, Any]], voting: SimpleNamespace
) -> None:
    m = _meeting("live")
    svc = _service(m, [SimpleNamespace(id=uuid4(), status="open")])
    with pytest.raises(ConflictError) as ei:
        await svc.patch(m.id, MeetingPatch(status="closed"), _admin())
    assert ei.value.code == "open_vote"
    assert m.status == "live"
    assert m.closed_at is None
    assert voting.cancel_calls == []
    assert audit == []


async def test_close_cancels_drafts_and_publishes_after_commit(
    audit: list[dict[str, Any]], voting: SimpleNamespace
) -> None:
    m = _meeting("live")
    draft = SimpleNamespace(id=uuid4())
    voting.drafts = [draft]
    pub = _Publisher()
    svc = _service(m, publisher=pub)
    out = await svc.patch(m.id, MeetingPatch(status="closed"), _admin())
    assert out.status == "closed"
    [(meeting_id, now, actor)] = voting.cancel_calls
    assert meeting_id == m.id
    assert actor == "mgr"
    assert m.closed_at == now
    assert [v.id for v in pub.cancelled] == [draft.id]
    assert len(pub.states) == 1
    [entry] = audit
    assert entry["action"].value == "meeting_update"
    assert entry["data"]["changes"] == {"status": {"from": "live", "to": "closed"}}


async def test_close_broadcast_failure_keeps_the_close(
    audit: list[dict[str, Any]], voting: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Patch the logger, not caplog: an earlier `logging.config.fileConfig` in the
    # suite (Alembic) can disable the module logger, and caplog then sees nothing.
    warnings: list[str] = []
    monkeypatch.setattr(
        lifecycle_mod.logger, "warning", lambda msg, *args: warnings.append(msg % args)
    )
    m = _meeting("live")
    draft = SimpleNamespace(id=uuid4())
    voting.drafts = [draft]
    svc = _service(m, publisher=_Publisher(fail=True))
    out = await svc.patch(m.id, MeetingPatch(status="closed"), _admin())
    assert out.status == "closed"
    assert warnings == [f"vote_cancelled broadcast failed (vote={draft.id})"]


async def test_close_without_drafts_or_publisher(
    audit: list[dict[str, Any]], voting: SimpleNamespace
) -> None:
    m = _meeting("live")
    voting.drafts = [SimpleNamespace(id=uuid4())]
    out = await _service(m).patch(m.id, MeetingPatch(status="closed"), _admin())
    assert out.status == "closed"
    # Without a publisher nothing reads the cancelled votes back.
    assert voting.reads == []


async def test_start_sets_started_at_once(
    audit: list[dict[str, Any]], voting: SimpleNamespace
) -> None:
    m = _meeting("planned")
    svc = _service(m)
    out = await svc.patch(m.id, MeetingPatch(status="live"), _admin())
    assert m.started_at is not None
    assert out.started_at == m.started_at
    first = m.started_at
    # A repeated start is a no-op and keeps the stamp.
    await _service(m).patch(m.id, MeetingPatch(status="live"), _admin())
    assert m.started_at == first


async def test_start_keeps_an_existing_started_at(
    audit: list[dict[str, Any]], voting: SimpleNamespace
) -> None:
    m = _meeting("planned")
    stamp = datetime(2026, 6, 20, 18, 4, tzinfo=UTC)
    m.started_at = stamp
    await _service(m).patch(m.id, MeetingPatch(status="live"), _admin())
    assert m.started_at == stamp


async def test_planning_change_is_audited(
    audit: list[dict[str, Any]], voting: SimpleNamespace
) -> None:
    m = _meeting("planned")
    await _service(m).patch(
        m.id, MeetingPatch(date=date(2026, 7, 1), startTime=time(19, 0)), _admin()
    )
    [entry] = audit
    assert entry["target_type"] == "meeting"
    assert entry["target_id"] == str(m.id)
    assert entry["data"]["changes"] == {
        "date": {"from": "2026-06-20", "to": "2026-07-01"},
        "startTime": {"from": "18:00:00", "to": "19:00:00"},
    }


async def test_current_item_change_is_not_audited(
    audit: list[dict[str, Any]], voting: SimpleNamespace
) -> None:
    m = _meeting("live")
    item = uuid4()
    # _get, then the owner lookup of the item.
    svc = MeetingService(_Session([m], scalars=[m.id]))  # type: ignore[arg-type]
    await svc.patch(m.id, MeetingPatch(currentAgendaItemId=item), _admin())
    assert m.current_agenda_item_id == item
    assert audit == []


async def test_create_is_audited(audit: list[dict[str, Any]]) -> None:
    gid = uuid4()
    svc = MeetingService(_Session())  # type: ignore[arg-type]
    out = await svc.create(
        MeetingCreate(gremiumId=gid, title="GV", date=date(2026, 6, 20), startTime=time(18, 0)),
        _admin(),
    )
    [entry] = audit
    assert entry["action"].value == "meeting_create"
    assert entry["target_id"] == str(out.id)
    assert entry["data"]["gremiumId"] == str(gid)
    assert entry["data"]["status"] == "planned"
    assert entry["data"]["date"] == "2026-06-20"


# A2: the agenda summary of MeetingOut
async def test_agenda_summary_empty_list() -> None:
    assert await MeetingService(_Session())._agenda_summaries([]) == {}  # type: ignore[arg-type]


async def test_agenda_summary_counts_and_current_freetext_item() -> None:
    m1, m2 = _meeting("live"), _meeting("planned")
    first, current = uuid4(), uuid4()
    m1.current_agenda_item_id = current
    rows = [
        (m1.id, first, None, "Begrüßung"),
        (m1.id, current, None, "Haushalt"),
        (m2.id, uuid4(), None, "Andere"),
    ]
    out = await MeetingService(_Session(rows))._agenda_summaries([m1, m2])  # type: ignore[arg-type]
    count, item = out[m1.id]
    assert count == 2
    assert item is not None
    assert (item.position, item.title) == (2, "Haushalt")
    assert out[m2.id] == (1, None)


async def test_agenda_summary_application_item_takes_the_application_title() -> None:
    m = _meeting("live")
    item_id, app_id = uuid4(), uuid4()
    m.current_agenda_item_id = item_id
    session = _Session(
        [(m.id, item_id, app_id, None)],
        [(app_id, {"title": "  Antrag Sommerfest "})],
    )
    out = await MeetingService(session)._agenda_summaries([m])  # type: ignore[arg-type]
    _, item = out[m.id]
    assert item is not None
    assert (item.position, item.title) == (1, "Antrag Sommerfest")


async def test_agenda_summary_without_agenda() -> None:
    m = _meeting("planned")
    m.current_agenda_item_id = uuid4()  # a stale id that matches no row
    out = await MeetingService(_Session())._agenda_summaries([m])  # type: ignore[arg-type]
    assert out[m.id] == (0, None)


async def test_detail_and_list_carry_the_agenda_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.livevote.schemas import CurrentAgendaItemOut

    m = _meeting("live")
    m.started_at = datetime(2026, 6, 20, 18, 4, tzinfo=UTC)
    summary = (3, CurrentAgendaItemOut(position=2, title="Haushalt"))

    async def _summaries(_self: Any, meetings: list[Meeting]) -> dict[UUID, Any]:
        return {x.id: summary for x in meetings}

    monkeypatch.setattr(MeetingService, "_agenda_summaries", _summaries)
    detail = await MeetingService(_Session([m])).get(m.id, _admin())  # type: ignore[arg-type]
    listed = await MeetingService(_Session([m])).list(_admin())  # type: ignore[arg-type]
    for out in (detail, listed[0]):
        dumped = out.model_dump(by_alias=True)
        assert dumped["agendaItemCount"] == 3
        assert dumped["currentAgendaItem"] == {"position": 2, "title": "Haushalt"}
        assert dumped["startedAt"] == m.started_at


# #17: public participation in the lifecycle
class _Guests:
    calls: list[tuple[str, Any]] = []

    def __init__(self, _session: Any, publisher: Any = None) -> None:
        self.publisher = publisher

    async def ensure_code(self, meeting: Any) -> None:
        type(self).calls.append(("ensure_code", meeting.id))
        meeting.join_code = "7KQ4MP"

    async def purge_on_close(self, meeting: Any) -> None:
        type(self).calls.append(("purge", meeting.id))

    async def publish(self, meeting_id: UUID, events: Any) -> None:
        type(self).calls.append(("publish", events))


@pytest.fixture
def guests(monkeypatch: pytest.MonkeyPatch) -> type[_Guests]:
    _Guests.calls = []
    monkeypatch.setattr(lifecycle_mod, "GuestService", _Guests)
    return _Guests


async def test_create_public_meeting_gets_a_code(
    audit: list[dict[str, Any]], guests: type[_Guests]
) -> None:
    svc = MeetingService(_Session())  # type: ignore[arg-type]
    out = await svc.create(
        MeetingCreate(
            gremiumId=uuid4(),
            title="GV",
            date=date(2026, 6, 20),
            startTime=time(18, 0),
            publicJoin=True,
            guestsMode="watch",
        ),
        _admin(),
    )
    assert out.public_join is True and out.guests_mode == "watch"
    assert out.join_code == "7KQ4MP"
    assert audit[0]["data"]["publicJoin"] is True


async def test_close_purges_guests_and_public_patch_publishes(
    audit: list[dict[str, Any]], voting: SimpleNamespace, guests: type[_Guests]
) -> None:
    m = _meeting("live")
    await _service(m, publisher=_Publisher()).patch(m.id, MeetingPatch(status="closed"), _admin())
    assert ("purge", m.id) in guests.calls
    m = _meeting("live")
    m.public_join, m.guests_mode, m.join_code = False, "vote", None
    pub = _Publisher()
    out = await _service(m, publisher=pub).patch(m.id, MeetingPatch(publicJoin=True), _admin())
    assert out.public_join is True and out.join_code == "7KQ4MP"
    assert [c[0] for c in guests.calls][-2:] == ["ensure_code", "publish"]
    assert audit[-1]["action"].value == "meeting_public_join_changed"
