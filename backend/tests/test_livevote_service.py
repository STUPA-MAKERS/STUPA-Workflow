"""MeetingService + BrokerPublisher (T-16).

Publisher: korrekte Event-Übersetzung **und** der Sicherheits-Guard »ohne Sitzung
kein Broadcast« (reiner Async-Vote darf nicht auf einen Live-Kanal leaken).
MeetingService: CRUD/Steuerung gegen eine schlanke Fake-Session (DB-Pfade liegen im
Integrationstest).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.livevote.models import Meeting
from app.modules.livevote.schemas import MeetingCreate, MeetingOut, MeetingPatch
from app.modules.livevote.service import BrokerPublisher, MeetingService, meeting_channel
from app.modules.voting.models import Vote
from app.modules.voting.schemas import TallyOut, VoteClosed, VoteOut
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, NotFoundError


class _CaptureBroker:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, object]]] = []

    async def publish(self, channel: str, message: dict[str, object]) -> None:
        self.messages.append((channel, message))

    def subscribe(self, channel: str):  # pragma: no cover - unused here
        raise NotImplementedError


def _vote_out(*, meeting_id, status: str = "open", secret: bool = False) -> VoteOut:
    config = VoteConfig.model_validate(
        {"options": ["yes", "no"], "majorityRule": "simple", "secret": secret}
    )
    return VoteOut(
        id=uuid4(),
        applicationId=uuid4(),
        meetingId=meeting_id,
        eligibleGroup="stupa",
        config=config,
        status=status,  # type: ignore[arg-type]
        secret=secret,
        tally=TallyOut(counts={"yes": 3, "no": 1}, eligible=10, quorumMet=True, leading="yes"),
    )


def test_meeting_channel() -> None:
    mid = uuid4()
    assert meeting_channel(mid) == f"meeting:{mid}"


@pytest.mark.asyncio
async def test_publisher_vote_opened_for_meeting_bound_vote() -> None:
    broker = _CaptureBroker()
    mid = uuid4()
    vote = _vote_out(meeting_id=mid)
    await BrokerPublisher(broker).vote_opened(vote)
    [(channel, msg)] = broker.messages
    assert channel == f"meeting:{mid}"
    assert msg["type"] == "vote_opened"
    assert msg["options"] == ["yes", "no"]


@pytest.mark.asyncio
async def test_publisher_skips_when_no_meeting() -> None:
    broker = _CaptureBroker()
    publisher = BrokerPublisher(broker)
    await publisher.vote_opened(_vote_out(meeting_id=None))
    await publisher.vote_tally(_vote_out(meeting_id=None))
    await publisher.vote_closed(
        VoteClosed(
            id=uuid4(),
            meetingId=None,
            result="passed",
            tally=TallyOut(counts={"yes": 1}, eligible=1, quorumMet=True),
        )
    )
    assert broker.messages == []


@pytest.mark.asyncio
async def test_publisher_vote_tally_and_closed() -> None:
    broker = _CaptureBroker()
    mid = uuid4()
    publisher = BrokerPublisher(broker)
    await publisher.vote_tally(_vote_out(meeting_id=mid))
    vid = uuid4()
    await publisher.vote_closed(
        VoteClosed(
            id=vid,
            meetingId=mid,
            result="rejected",
            tally=TallyOut(counts={"yes": 1, "no": 9}, eligible=10, quorumMet=True),
        )
    )
    tally_msg = broker.messages[0][1]
    closed_msg = broker.messages[1][1]
    assert tally_msg["type"] == "vote_tally"
    assert tally_msg["counts"] == {"yes": 3, "no": 1}
    assert closed_msg["type"] == "vote_closed"
    assert closed_msg["result"] == "rejected"
    assert closed_msg["voteId"] == str(vid)


@pytest.mark.asyncio
async def test_publisher_open_secret_vote_broadcasts_no_choice_counts() -> None:
    # Sicherheits-Regression (fix/secret-live-tally): der WS-/Beamer-Fan-out eines
    # OFFENEN geheimen Votes darf nur die Teilnahme tragen, keine Choice-Counts/leading.
    broker = _CaptureBroker()
    mid = uuid4()
    await BrokerPublisher(broker).vote_tally(_vote_out(meeting_id=mid, secret=True))
    [(channel, msg)] = broker.messages
    assert channel == f"meeting:{mid}"
    assert msg["type"] == "vote_tally"
    assert msg["secret"] is True
    assert msg["counts"] == {}            # kein Zwischenstand am Beamer/Mobile
    assert msg["leading"] is None
    assert msg["cast"] == 4               # nur Teilnahme: 3 + 1 von 10
    assert msg["eligible"] == 10
    assert {3, 1}.isdisjoint(v for v in msg.values() if type(v) is int)


@pytest.mark.asyncio
async def test_publisher_closed_secret_vote_reveals_full_aggregates() -> None:
    # Nach Close erscheinen die vollen Aggregate (über vote_closed; vote_tally bei
    # status=closed gäbe sie ebenfalls frei — Regel »Counts erst bei Close«).
    broker = _CaptureBroker()
    mid = uuid4()
    await BrokerPublisher(broker).vote_tally(
        _vote_out(meeting_id=mid, status="closed", secret=True)
    )
    [(_, msg)] = broker.messages
    assert msg["counts"] == {"yes": 3, "no": 1}
    assert msg["leading"] == "yes"


@pytest.mark.asyncio
async def test_publisher_meeting_state() -> None:
    broker = _CaptureBroker()
    mid, aid = uuid4(), uuid4()
    out = MeetingOut(
        id=mid,
        gremiumId=uuid4(),
        title="GV",
        status="live",
        activeApplicationId=aid,
        createdAt=datetime(2026, 6, 8, tzinfo=UTC),
    )
    await BrokerPublisher(broker).meeting_state(out)
    [(channel, msg)] = broker.messages
    assert channel == f"meeting:{mid}"
    assert msg == {
        "type": "meeting_state",
        "activeApplicationId": str(aid),
        "status": "live",
    }


# --------------------------------------------------------------------------- #
# MeetingService gegen Fake-Session
# --------------------------------------------------------------------------- #
class _Scalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value

    def scalars(self) -> _Scalars:
        # ``_votes_for`` (Meeting-Votes) erwartet ``.scalars().all()`` — leer reicht.
        return _Scalars([])


class _FakeSession:
    def __init__(self, existing: object = None) -> None:
        self.existing = existing
        self.commits = 0
        self.added: list[object] = []

    async def execute(self, _stmt: object) -> _Result:
        return _Result(self.existing)

    def add(self, obj: object) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()  # type: ignore[attr-defined]
        self.added.append(obj)

    async def flush(self) -> None:
        # DB-Server-Default nachstellen: ``created_at`` wird beim Insert gesetzt.
        for obj in self.added:
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime(2026, 6, 8, tzinfo=UTC)  # type: ignore[attr-defined]

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_service_create_sets_planned_and_commits() -> None:
    session = _FakeSession()
    svc = MeetingService(session)  # type: ignore[arg-type]
    gid = uuid4()
    out = await svc.create(MeetingCreate(gremiumId=gid, title="GV"), _principal())
    assert out.status == "planned"
    assert out.gremium_id == gid
    assert session.commits == 1


@pytest.mark.asyncio
async def test_service_get_not_found() -> None:
    svc = MeetingService(_FakeSession(existing=None))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.get(uuid4(), _principal())


@pytest.mark.asyncio
async def test_service_patch_applies_and_broadcasts_meeting_state() -> None:
    meeting = Meeting(gremium_id=uuid4(), title="GV")
    meeting.id = uuid4()
    meeting.status = "planned"
    meeting.date = None
    meeting.active_application_id = None
    meeting.created_at = datetime(2026, 6, 8, tzinfo=UTC)
    session = _FakeSession(existing=meeting)
    broker = _CaptureBroker()
    svc = MeetingService(session, BrokerPublisher(broker))  # type: ignore[arg-type]

    aid = uuid4()
    out = await svc.patch(
        meeting.id, MeetingPatch(status="live", activeApplicationId=aid), _principal()
    )
    assert out.status == "live"
    assert out.active_application_id == aid
    assert session.commits == 1
    [(channel, msg)] = broker.messages
    assert channel == f"meeting:{meeting.id}"
    assert msg["status"] == "live"


@pytest.mark.asyncio
async def test_service_patch_without_publisher_is_silent() -> None:
    meeting = Meeting(gremium_id=uuid4(), title="GV")
    meeting.id = uuid4()
    meeting.status = "planned"
    meeting.date = None
    meeting.active_application_id = None
    meeting.created_at = datetime(2026, 6, 8, tzinfo=UTC)
    svc = MeetingService(_FakeSession(existing=meeting))  # type: ignore[arg-type]
    out = await svc.patch(meeting.id, MeetingPatch(status="closed"), _principal())
    assert out.status == "closed"


@pytest.mark.asyncio
async def test_service_patch_closed_session_cannot_reopen() -> None:
    """»closed« ist terminal: ein Wieder-Öffnen (closed→live/planned) wird abgelehnt."""
    meeting = Meeting(gremium_id=uuid4(), title="GV")
    meeting.id = uuid4()
    meeting.status = "closed"
    meeting.date = None
    meeting.active_application_id = None
    meeting.created_at = datetime(2026, 6, 8, tzinfo=UTC)
    svc = MeetingService(_FakeSession(existing=meeting))  # type: ignore[arg-type]
    for target in ("live", "planned"):
        with pytest.raises(ConflictError):
            await svc.patch(meeting.id, MeetingPatch(status=target), _principal())
    # Status bleibt unverändert geschlossen.
    assert meeting.status == "closed"


@pytest.mark.asyncio
async def test_service_open_vote_returns_row() -> None:
    vote = Vote(application_id=uuid4(), eligible_group="stupa", config={})
    svc = MeetingService(_FakeSession(existing=vote))  # type: ignore[arg-type]
    assert await svc.open_vote(uuid4()) is vote


# --------------------------------------------------------------------------- #
# list() — Sitzungen wiederfinden (#104)
# --------------------------------------------------------------------------- #
class _ListResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _ListResult:
        return self

    def all(self) -> list:
        return self._rows


class _ListSession:
    """Liefert die je ``execute`` vorab gequeueten Zeilen (FIFO)."""

    def __init__(self, *result_sets: list) -> None:
        self._queue = list(result_sets)

    async def execute(self, _stmt: object) -> _ListResult:
        return _ListResult(self._queue.pop(0) if self._queue else [])


def _meeting_row(*, status: str = "planned") -> Meeting:
    m = Meeting(gremium_id=uuid4(), title="GV")
    m.id = uuid4()
    m.status = status
    m.date = None
    m.active_application_id = None
    m.created_at = datetime(2026, 6, 8, tzinfo=UTC)
    return m


@pytest.mark.asyncio
async def test_service_list_maps_protocol_and_keeps_order() -> None:
    m1, m2 = _meeting_row(), _meeting_row()
    pid = uuid4()
    session = _ListSession([m1, m2], [(m1.id, pid)])  # nur m1 hat ein Protokoll
    out = await MeetingService(session).list(_principal())  # type: ignore[arg-type]
    assert [o.id for o in out] == [m1.id, m2.id]
    assert out[0].protocol_id == pid
    assert out[1].protocol_id is None


@pytest.mark.asyncio
async def test_service_list_with_gremium_filter() -> None:
    m = _meeting_row()
    out = await MeetingService(_ListSession([m], [])).list(_principal(), m.gremium_id)  # type: ignore[arg-type]
    assert [o.id for o in out] == [m.id]


@pytest.mark.asyncio
async def test_service_list_empty_returns_empty() -> None:
    out = await MeetingService(_ListSession([])).list(_principal())  # type: ignore[arg-type]
    assert out == []


def _principal():  # noqa: ANN202
    from app.modules.auth.principal import Principal

    # Admin ⇒ can_control kurzschließt ohne DB-Query gegen die Fake-Session.
    return Principal(sub="mgr", permissions={"meeting.manage"}, roles=["admin"])


def test_meeting_patch_requires_at_least_one_field() -> None:
    import pytest as _pytest
    from pydantic import ValidationError

    with _pytest.raises(ValidationError):
        MeetingPatch()
