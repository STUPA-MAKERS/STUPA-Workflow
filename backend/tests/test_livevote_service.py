"""MeetingService + BrokerPublisher (T-16).

Publisher: korrekte Event-Übersetzung **und** der Sicherheits-Guard »ohne Sitzung
kein Broadcast« (reiner Async-Vote darf nicht auf einen Live-Kanal leaken).
MeetingService: CRUD/Steuerung gegen eine schlanke Fake-Session (DB-Pfade liegen im
Integrationstest).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
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
        tally=TallyOut(
            counts={"yes": 3, "no": 1},
            eligible=10,
            voted=4,
            present=8,
            revealed=status == "closed" or not secret,
            quorumMet=True,
            leading="yes",
        ),
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

    def all(self) -> list[object]:
        # Aggregat-Queries (``_present_by_meeting`` u. Ä.) erwarten ``.all()`` — leer.
        return []


class _FakeSession:
    def __init__(self, existing: object = None) -> None:
        self.existing = existing
        self.commits = 0
        self.added: list[object] = []

    async def execute(self, _stmt: object) -> _Result:
        return _Result(self.existing)

    async def get(self, _model: object, _pk: object) -> object | None:
        # Gremium-Name-Lookup in ``_emit`` — für diese Tests nicht relevant.
        return None

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
    # Datum + Uhrzeit sind beim Anlegen Pflicht (Termin der Sitzung).
    out = await svc.create(
        MeetingCreate(
            gremiumId=gid, title="GV", date=date(2026, 6, 20), startTime=time(18, 0)
        ),
        _principal(),
    )
    assert out.status == "planned"
    assert out.gremium_id == gid
    assert session.commits == 1


@pytest.mark.asyncio
async def test_meeting_create_requires_date_and_time() -> None:
    """Ohne Datum/Uhrzeit ist ``MeetingCreate`` ungültig (Pflicht-Termin)."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        MeetingCreate(gremiumId=uuid4(), title="GV")  # type: ignore[call-arg]


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
    # Start verlangt einen Protokollanten — sonst lehnt der Service mit 409 ab.
    meeting.protokollant_id = uuid4()
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
async def test_service_patch_to_live_without_protokollant_conflicts() -> None:
    """planned→live ohne Protokollant → 409; der Status bleibt unverändert geplant."""
    meeting = Meeting(gremium_id=uuid4(), title="GV")
    meeting.id = uuid4()
    meeting.status = "planned"
    meeting.date = None
    meeting.active_application_id = None
    meeting.protokollant_id = None
    meeting.created_at = datetime(2026, 6, 8, tzinfo=UTC)
    svc = MeetingService(_FakeSession(existing=meeting))  # type: ignore[arg-type]
    with pytest.raises(ConflictError):
        await svc.patch(meeting.id, MeetingPatch(status="live"), _principal())
    assert meeting.status == "planned"


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


# ---------------------------------------------------------------- #14/#15/#16
def _meeting(status: str = "planned") -> Meeting:
    meeting = Meeting(gremium_id=uuid4(), title="GV")
    meeting.id = uuid4()
    meeting.status = status
    meeting.date = None
    meeting.closed_at = None
    meeting.active_application_id = None
    meeting.created_at = datetime(2026, 6, 8, tzinfo=UTC)
    return meeting


@pytest.mark.asyncio
async def test_service_patch_close_sets_closed_at() -> None:
    """#14: Status→closed stempelt ``closed_at`` (einmalig, fürs Protokoll-Ende)."""
    meeting = _meeting()
    svc = MeetingService(_FakeSession(existing=meeting))  # type: ignore[arg-type]
    out = await svc.patch(meeting.id, MeetingPatch(status="closed"), _principal())
    assert out.status == "closed"
    assert meeting.closed_at is not None
    first = meeting.closed_at
    # Erneutes »closed« (No-op) überschreibt den Stempel nicht.
    await svc.patch(meeting.id, MeetingPatch(status="closed"), _principal())
    assert meeting.closed_at == first


@pytest.mark.asyncio
async def test_service_patch_protokollant_locked_after_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#15: finalisiertes Protokoll ⇒ Protokollant nicht mehr änderbar (409)."""
    meeting = _meeting()

    async def _final(self, _mid):  # noqa: ANN001, ANN202
        return True

    monkeypatch.setattr(MeetingService, "_protocol_final", _final)
    svc = MeetingService(_FakeSession(existing=meeting))  # type: ignore[arg-type]
    with pytest.raises(ConflictError):
        await svc.patch(
            meeting.id, MeetingPatch(protokollantId=uuid4()), _principal()
        )


class _DeletableSession(_FakeSession):
    def __init__(self, existing: object = None) -> None:
        super().__init__(existing)
        self.deleted: list[object] = []

    async def delete(self, obj: object) -> None:
        self.deleted.append(obj)


def _audit_capture(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    import app.modules.livevote.service as livevote_service_mod

    calls: list[dict] = []

    async def _record(session, **kw):  # noqa: ANN001, ANN202
        calls.append(kw)

    monkeypatch.setattr(livevote_service_mod, "audit_record", _record)
    return calls


@pytest.mark.asyncio
async def test_service_delete_finalized_requires_special_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#16: Sitzung mit finalisiertem Protokoll löschen ⇒ nur mit
    ``meeting.delete_finalized``; ohne ⇒ 403 und nichts gelöscht."""
    from app.modules.auth.principal import Principal
    from app.shared.errors import ForbiddenError

    meeting = _meeting(status="closed")

    async def _final(self, _mid):  # noqa: ANN001, ANN202
        return True

    monkeypatch.setattr(MeetingService, "_protocol_final", _final)
    calls = _audit_capture(monkeypatch)
    session = _DeletableSession(existing=meeting)
    svc = MeetingService(session)  # type: ignore[arg-type]

    manager = Principal(sub="mgr", permissions={"meeting.manage"}, roles=["manager"])
    with pytest.raises(ForbiddenError):
        await svc.delete(meeting.id, manager)
    assert session.deleted == []
    assert calls == []

    privileged = Principal(
        sub="archiv",
        permissions={"meeting.manage", "meeting.delete_finalized"},
        roles=["manager"],
    )
    await svc.delete(meeting.id, privileged)
    assert session.deleted == [meeting]
    assert calls[0]["action"].value == "meeting_delete"
    assert calls[0]["data"]["finalizedProtocol"] is True


@pytest.mark.asyncio
async def test_service_delete_unfinalized_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#16: auch normales Löschen landet im Audit-Log (finalizedProtocol=False)."""
    meeting = _meeting()

    async def _final(self, _mid):  # noqa: ANN001, ANN202
        return False

    monkeypatch.setattr(MeetingService, "_protocol_final", _final)
    calls = _audit_capture(monkeypatch)
    session = _DeletableSession(existing=meeting)
    svc = MeetingService(session)  # type: ignore[arg-type]
    await svc.delete(meeting.id, _principal())
    assert session.deleted == [meeting]
    assert calls[0]["data"]["finalizedProtocol"] is False
    assert calls[0]["target_id"] == str(meeting.id)


@pytest.mark.asyncio
async def test_service_patch_closed_session_settings_frozen() -> None:
    """#15: geschlossene Sitzung ⇒ Datum/Zeit/Protokollant nicht mehr änderbar."""
    from datetime import date

    meeting = _meeting(status="closed")
    svc = MeetingService(_FakeSession(existing=meeting))  # type: ignore[arg-type]
    with pytest.raises(ConflictError):
        await svc.patch(
            meeting.id, MeetingPatch(date=date(2026, 7, 1)), _principal()
        )
    with pytest.raises(ConflictError):
        await svc.patch(
            meeting.id, MeetingPatch(protokollantId=uuid4()), _principal()
        )
    assert meeting.date is None


async def test_pool_substitute_sees_committee_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#7: Ein Stellvertreter-Pool-Mitglied sieht die Sitzungs-Timeline seiner Gremien
    (Mitglieds- ∪ Pool-Gremien), auch ohne eigene Mitgliedschaft."""
    from app.modules.auth.principal import Principal
    from app.modules.livevote import service as livevote_service_mod
    from tests.auth_fakes import fake_session, result

    member_g = uuid4()
    pool_g = uuid4()

    async def _members(_session, _sub, now=None):  # noqa: ANN001, ANN202
        return {member_g}

    monkeypatch.setattr(livevote_service_mod, "gremium_member_ids", _members)
    # execute(...).scalars().all() → das Pool-Gremium.
    svc = MeetingService(fake_session(result(pool_g)))
    visible = await svc._visible_gremium_ids(
        Principal(sub="sub-1", permissions=set())
    )
    assert visible == {member_g, pool_g}


async def test_pool_substitute_not_live_participant_without_delegation() -> None:
    """#7: Pool-Zugehörigkeit gibt NUR Timeline-Sicht, keinen Live-Kanal — der kommt
    erst über eine konkrete Delegation (is_participant)."""
    from app.modules.auth.principal import Principal
    from tests.auth_fakes import fake_session, result

    gremium = uuid4()
    meeting = uuid4()
    # is_member → kein Mitglied (leere Member-Gremien); _delegated_meeting_ids → keine.
    svc = MeetingService(fake_session(result(), result()))
    is_part = await svc.is_participant(
        meeting, gremium, Principal(sub="sub-1", permissions=set())
    )
    assert is_part is False


async def test_assert_can_read_denies_non_member(monkeypatch: pytest.MonkeyPatch) -> None:
    """#12 sec-audit: ein fremder eingeloggter Nutzer darf Sitzungs-Details (Roster
    etc.) NICHT lesen — kein Mitglied/Pool/Verwalter/Delegations-Empfänger."""
    from app.modules.auth.principal import Principal
    from app.modules.livevote import service as mod
    from app.shared.errors import ForbiddenError
    from tests.auth_fakes import fake_session, result

    meeting = Meeting(gremium_id=uuid4(), title="GV")
    meeting.id = uuid4()

    async def _none(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(mod, "gremium_member_ids", _none)
    # _get → meeting; pool-Query → leer; delegated-Query → leer.
    svc = MeetingService(fake_session(result(meeting), result(), result()))
    with pytest.raises(ForbiddenError):
        await svc.assert_can_read(meeting.id, Principal(sub="x", permissions=set()))


async def test_assert_can_read_allows_member(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mitglied des Sitzungs-Gremiums darf lesen."""
    from app.modules.auth.principal import Principal
    from app.modules.livevote import service as mod
    from tests.auth_fakes import fake_session, result

    meeting = Meeting(gremium_id=uuid4(), title="GV")
    meeting.id = uuid4()

    async def _member(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return {meeting.gremium_id}

    monkeypatch.setattr(mod, "gremium_member_ids", _member)
    svc = MeetingService(fake_session(result(meeting), result()))  # _get + pool
    await svc.assert_can_read(meeting.id, Principal(sub="x", permissions=set()))


# --------------------------------------------------------- #meeting-view-all (global read)
async def test_view_all_sees_every_committee() -> None:
    """#meeting-view-all: der globale Read-Holder sieht ALLE Gremien — _visible
    gibt ``None`` (= keine Gremium-Filterung) zurück, genau wie meeting.manage/Admin."""
    from app.modules.auth.principal import Principal
    from tests.auth_fakes import fake_session

    svc = MeetingService(fake_session())  # keine DB-Query nötig (Kurzschluss)
    visible = await svc._visible_gremium_ids(
        Principal(sub="viewer", permissions={"meeting.view_all"})
    )
    assert visible is None


async def test_view_all_is_live_participant_without_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#meeting-view-all: öffnet den Live-Read-Kanal gremiumsübergreifend, auch ohne
    Mitgliedschaft/Delegation (rein lesend — das Stimmrecht bleibt separat gegatet)."""
    from app.modules.auth.principal import Principal
    from app.modules.livevote import service as mod
    from tests.auth_fakes import fake_session

    async def _none(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(mod, "gremium_member_ids", _none)
    svc = MeetingService(fake_session())  # view_all kurzschließt vor jeder DB-Query
    is_part = await svc.is_participant(
        uuid4(), uuid4(), Principal(sub="viewer", permissions={"meeting.view_all"})
    )
    assert is_part is True


async def test_view_all_can_read_foreign_meeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#meeting-view-all: assert_can_read lässt den globalen Read-Holder ein Sitzungs-
    Detail eines FREMDEN Gremiums lesen (kein 403), ohne Mitglied/Delegierter zu sein."""
    from app.modules.auth.principal import Principal
    from app.modules.livevote import service as mod
    from tests.auth_fakes import fake_session, result

    meeting = Meeting(gremium_id=uuid4(), title="GV")
    meeting.id = uuid4()

    async def _none(_s, _sub, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(mod, "gremium_member_ids", _none)
    # _get → meeting; _visible kurzschließt via view_all (kein pool/delegated-Query nötig).
    svc = MeetingService(fake_session(result(meeting)))
    await svc.assert_can_read(
        meeting.id, Principal(sub="viewer", permissions={"meeting.view_all"})
    )
