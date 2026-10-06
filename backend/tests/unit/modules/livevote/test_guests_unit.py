"""GuestService (#17) without a database: every branch of the guest rules.

A result-queue fake answers the queries in order. The audit hook runs its own two
statements (advisory lock, previous hash); the fake answers them apart from the queue.
The integration test `test_public_meeting.py` covers the real queries on Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.livevote import guests as guests_mod
from app.modules.livevote.guests import (
    CODE_ALPHABET,
    GuestEvents,
    GuestService,
    new_join_code,
    normalize_code,
    qr_matrix,
    token_hash,
)
from app.modules.livevote.models import MeetingGuest
from app.modules.voting.schemas import MyBallot, TallyOut, VoteOut
from app.shared.config_schemas import VoteConfig
from app.shared.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
)
from tests._support.flow_fakes import FakeResult, FakeSession, result

NOW = datetime(2026, 10, 6, 18, 52, tzinfo=UTC)
MID = UUID("00000000-0000-0000-0000-0000000000a1")
GID = UUID("00000000-0000-0000-0000-0000000000b2")


class GuestFakeSession(FakeSession):
    """FakeSession that answers the statements of the audit hook outside the queue."""

    async def execute(self, stmt: Any) -> FakeResult:
        text = str(stmt)
        if "pg_advisory_xact_lock" in text or "FROM audit_entry" in text:
            return FakeResult()
        return await super().execute(stmt)


def db(*results: FakeResult, scalars: list[Any] | None = None) -> Any:
    session = GuestFakeSession(list(results))
    session.scalar_results = list(scalars or [])
    return session


def meeting(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": MID,
        "gremium_id": GID,
        "title": "7. Sitzung",
        "date": None,
        "start_time": None,
        "status": "live",
        "started_at": None,
        "public_join": True,
        "guests_mode": "vote",
        "join_code": "7KQ4MP",
        "current_agenda_item_id": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def guest(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(),
        "meeting_id": MID,
        "seq": 1,
        "display_name": "Jana Roth",
        "status": "pending",
        "token_hash": token_hash("tok"),
        "requested_at": NOW,
        "decided_at": None,
        "decided_by": None,
        "admitted_at": None,
        "last_seen_at": NOW,
    }
    base.update(over)
    return SimpleNamespace(**base)


class Recorder:
    """Stand-in for BrokerPublisher that records the guest events."""

    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[tuple[str, Any]] = []
        self.fail = fail

    async def guest_requested(self, meeting_id: UUID, out: Any) -> None:
        if self.fail:
            raise RuntimeError("broker down")
        self.events.append(("requested", out))

    async def guest_updated(self, meeting_id: UUID, out: Any, reason: Any = None) -> None:
        self.events.append(("updated", (out, reason)))

    async def guest_counts(self, meeting_id: UUID, **kw: Any) -> None:
        self.events.append(("counts", kw))

    async def vote_tally(self, vote: Any) -> None:
        if self.fail:
            raise RuntimeError("broker down")
        self.events.append(("tally", vote))


# -- pure helpers ---------------------------------------------------------------------


def test_codes_tokens_and_qr() -> None:
    code = new_join_code()
    assert len(code) == 6 and set(code) <= set(CODE_ALPHABET)
    assert normalize_code(" 7kq-4mp ") == "7KQ4MP"
    assert token_hash("a") != token_hash("b") and len(token_hash("a")) == 32
    qr = qr_matrix("https://stupa.example/j/7KQ4MP")
    assert qr.size == len(qr.rows) and all(len(r) == qr.size for r in qr.rows)
    # The finder pattern sits in the top left corner.
    assert qr.rows[0].startswith("1111111")


def test_retry_after() -> None:
    assert GuestService._retry_after(guest(status="pending"), NOW) is None  # type: ignore[arg-type]
    assert GuestService._retry_after(guest(status="rejected", decided_at=None), NOW) is None  # type: ignore[arg-type]
    assert GuestService._retry_after(guest(status="rejected", decided_at=NOW), NOW) == 180  # type: ignore[arg-type]
    late = guest(status="removed", decided_at=NOW - timedelta(minutes=5))
    assert GuestService._retry_after(late, NOW) == 0  # type: ignore[arg-type]


# -- lookups and the lead -------------------------------------------------------------


async def test_meeting_and_guest_lookups_404() -> None:
    service = GuestService(db(result(), result()))
    with pytest.raises(NotFoundError):
        await service._meeting(MID)
    with pytest.raises(NotFoundError) as err:
        await service._guest(MID, uuid4(), for_update=True)
    assert err.value.code == "guest_not_found"


def test_assert_open() -> None:
    with pytest.raises(ConflictError) as closed:
        GuestService._assert_open(meeting(status="closed"))  # type: ignore[arg-type]
    assert closed.value.code == "meeting_closed"
    with pytest.raises(ConflictError) as off:
        GuestService._assert_open(meeting(public_join=False))  # type: ignore[arg-type]
    assert off.value.code == "meeting_not_public"


async def test_list_resolves_lead_names() -> None:
    lead = uuid4()
    rows = [guest(), guest(status="admitted", decided_by=lead, seq=2)]
    session = db(result(meeting()), result(*rows), result((lead, None, "lead@x.de")))
    out = await GuestService(session).list(MID)
    assert [g.decided_by_name for g in out] == [None, "lead@x.de"]
    assert await GuestService(db(result(meeting()), result())).list(MID) == []


async def test_counts() -> None:
    session = db(result(("admitted", 3), ("pending", 1)))
    assert await GuestService(session).counts(MID) == (3, 1)
    assert await GuestService(db(result())).counts(MID) == (0, 0)


@pytest.mark.parametrize(
    ("method", "status", "to", "action"),
    [
        ("admit", "pending", "admitted", "guest_admitted"),
        ("reject", "pending", "rejected", "guest_rejected"),
        ("remove", "admitted", "removed", "guest_removed"),
    ],
)
async def test_decisions(method: str, status: str, to: str, action: str) -> None:
    row = guest(status=status)
    lead = uuid4()
    session = db(
        result(meeting()),
        result(row),
        result((lead, "Lea Lead", None)),
        # publish: the meeting and the counts
        result(meeting()),
        result(("admitted", 1)),
        scalars=[lead],
    )
    recorder = Recorder()
    out = await getattr(GuestService(session, recorder), method)(MID, row.id, actor_sub="lead")  # type: ignore[arg-type]
    assert out.status == to and out.decided_by_name == "Lea Lead"
    assert row.decided_at is not None
    assert (row.admitted_at is not None) == (to == "admitted")
    [entry] = [a for a in session.added if type(a).__name__ == "AuditEntry"]
    assert entry.action == action and entry.data["guestId"] == str(row.id)
    assert "Jana" not in str(entry.data)
    assert [e[0] for e in recorder.events] == ["updated", "counts"]
    assert session.committed == 1


@pytest.mark.parametrize(
    ("method", "status", "code"),
    [("admit", "admitted", "guest_not_pending"), ("remove", "pending", "guest_not_admitted")],
)
async def test_decision_on_wrong_status_409(method: str, status: str, code: str) -> None:
    row = guest(status=status)
    session = db(result(meeting()), result(row))
    with pytest.raises(ConflictError) as err:
        await getattr(GuestService(session), method)(MID, row.id, actor_sub="lead")
    assert err.value.code == code


async def test_rename_and_pseudonymized_guest() -> None:
    row = guest()
    session = db(result(meeting()), result(row))
    out = await GuestService(session).rename(MID, row.id, "Jana R.", actor_sub="lead")
    assert out.display_name == "Jana R."
    gone = guest(display_name=None)
    with pytest.raises(ConflictError) as err:
        await GuestService(db(result(meeting()), result(gone))).rename(
            MID, gone.id, "X Y", actor_sub="lead"
        )
    assert err.value.code == "guest_pseudonymized"


async def test_admit_all() -> None:
    rows = [guest(), guest(seq=2)]
    session = db(result(meeting()), result(*rows), scalars=[None])
    out = await GuestService(session).admit_all(MID, actor_sub="lead")
    assert [g.status for g in out] == ["admitted", "admitted"]
    [entry] = [a for a in session.added if type(a).__name__ == "AuditEntry"]
    assert entry.action == "guest_admit_all" and entry.data["count"] == 2
    empty = db(result(meeting()), result())
    assert await GuestService(empty).admit_all(MID, actor_sub="lead") == []
    assert not [a for a in empty.added if type(a).__name__ == "AuditEntry"]


async def test_join_link_and_rotate() -> None:
    service = GuestService(db(result(meeting())), base_url="https://s.example/")
    link = await service.join_link(MID)
    assert link.join_url == "https://s.example/j/7KQ4MP" and link.qr.size >= 21
    with pytest.raises(ConflictError):
        await GuestService(db(result(meeting(join_code=None)))).join_link(MID)
    pending = guest()
    m = meeting()
    session = db(result(m), result(pending), scalars=[None])
    recorder = Recorder()
    out = await GuestService(session, recorder).rotate(MID, actor_sub="lead")  # type: ignore[arg-type]
    assert out.join_code == m.join_code != "7KQ4MP"
    assert session.deleted == [pending]
    updated = [e for e in recorder.events if e[0] == "updated"]
    assert updated[0][1][0].status == "expired" and updated[0][1][1] == "rotated"


async def test_assign_code_retries_a_collision() -> None:
    from sqlalchemy.exc import IntegrityError

    class Colliding(GuestFakeSession):
        flushes = 0

        async def flush(self) -> None:
            type(self).flushes += 1
            if type(self).flushes == 1:
                raise IntegrityError("insert", {}, Exception("duplicate"))

    session = Colliding()
    m = meeting(join_code=None)
    code = await GuestService(session).assign_code(m)  # type: ignore[arg-type]
    assert m.join_code == code and Colliding.flushes == 2

    class Always(GuestFakeSession):
        async def flush(self) -> None:
            raise IntegrityError("insert", {}, Exception("duplicate"))

    with pytest.raises(ConflictError):
        await GuestService(Always()).assign_code(meeting(join_code=None))  # type: ignore[arg-type]


async def test_free_code_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    session = db(scalars=[uuid4()] * 20)
    with pytest.raises(ConflictError) as err:
        await GuestService(session)._free_code()
    assert err.value.code == "join_code_exhausted"
    m = meeting(join_code="ABCDEF")
    await GuestService(db()).ensure_code(m)  # type: ignore[arg-type]
    assert m.join_code == "ABCDEF"
    fresh = meeting(join_code=None)
    await GuestService(db(scalars=[None])).ensure_code(fresh)  # type: ignore[arg-type]
    assert fresh.join_code is not None


async def test_switch_off_purge_pseudonymize_attended() -> None:
    pending = guest()
    admitted = guest(status="admitted", seq=2)
    session = db(result(pending), result(admitted), scalars=[None])
    events = await GuestService(session).switch_off(meeting(), actor_sub="lead", now=NOW)  # type: ignore[arg-type]
    assert admitted.status == "removed" and session.deleted == [pending]
    assert [(o.status, r) for o, r in events.updated] == [
        ("expired", "public_off"),
        ("removed", "public_off"),
    ]
    waiting = guest()
    purge = db(result(waiting))
    closed = await GuestService(purge).purge_on_close(meeting())  # type: ignore[arg-type]
    assert len(purge.statements) == 3
    assert [(o.status, r) for o, r in closed.updated] == [("expired", "meeting_closed")]
    assert "display_name" in str(purge.statements[2])
    rows = [guest(seq=5), guest(seq=9)]
    assert await GuestService(db(result(*rows))).pseudonymize(MID) == 2
    assert [(r.seq, r.display_name, r.token_hash) for r in rows] == [
        (1, None, None),
        (2, None, None),
    ]
    assert await GuestService(db(scalars=[3])).attended_count(MID) == 3
    assert await GuestService(db()).attended_count(MID) == 0


async def test_publish_paths() -> None:
    await GuestService(db()).publish(MID, GuestEvents(counts=True))  # no publisher: no-op
    quiet = Recorder()
    await GuestService(db(), quiet).publish(MID, GuestEvents())  # type: ignore[arg-type]
    assert quiet.events == []
    failing = Recorder(fail=True)
    out = GuestService._out(guest())  # type: ignore[arg-type]
    # A broker fault only logs.
    await GuestService(db(), failing).publish(MID, GuestEvents(requested=[out]))  # type: ignore[arg-type]


# -- the guest -----------------------------------------------------------------------


async def test_meeting_by_code_and_head() -> None:
    with pytest.raises(NotFoundError) as unknown:
        await GuestService(db(result())).meeting_by_code("zzz")
    assert unknown.value.code == "join_code_unknown"
    head = await GuestService(db(result(meeting()), scalars=["Fachschaft"])).head("7kq-4mp")
    assert head.code == "7KQ4MP" and head.gremium_name == "Fachschaft"


async def test_resolve_rules() -> None:
    with pytest.raises(UnauthorizedError):
        await GuestService(db()).resolve("7KQ4MP", None)
    with pytest.raises(NotFoundError) as unknown:
        await GuestService(db(result())).resolve("7KQ4MP", "tok")
    assert unknown.value.code == "guest_not_found"
    stale = db(result(guest()), result(meeting()))
    with pytest.raises(NotFoundError):
        await GuestService(stale).resolve("OLDOLD", "tok")
    admitted = guest(status="admitted")
    m, g = await GuestService(db(result(admitted), result(meeting()))).resolve("OLDOLD", "tok")
    assert g is admitted and m.id == MID
    off = db(result(guest()), result(meeting(public_join=False)))
    with pytest.raises(NotFoundError) as not_public:
        await GuestService(off).resolve("7KQ4MP", "tok")
    assert not_public.value.code == "meeting_not_public"


async def test_join_new_device() -> None:
    session = db(result(meeting()), scalars=[2, "FS"])
    recorder = Recorder()
    me, token = await GuestService(session, recorder).join("7KQ4MP", "Jana Roth", None, now=NOW)  # type: ignore[arg-type]
    assert token is not None and me.status == "pending" and me.number == 3
    [row] = [a for a in session.added if isinstance(a, MeetingGuest)]
    assert row.token_hash == token_hash(token)
    assert recorder.events[0][0] == "requested"


async def test_join_of_a_closed_or_hidden_meeting_is_unknown() -> None:
    session = db(result())
    with pytest.raises(NotFoundError) as err:
        await GuestService(session).join("C", "Jo Do", None, now=NOW)
    assert err.value.code == "join_code_unknown"
    query = str(session.statements[0])
    assert "meeting.status !=" in query and "meeting.public_join IS true" in query


async def test_join_same_device_rules() -> None:
    admitted = guest(status="admitted")
    with pytest.raises(ConflictError) as err:
        await GuestService(db(result(meeting()), result(admitted))).join(
            "C", "Jo Do", "tok", now=NOW
        )
    assert err.value.code == "already_admitted"
    rejected = guest(status="rejected", decided_at=NOW)
    with pytest.raises(RateLimitedError) as wait:
        await GuestService(db(result(meeting()), result(rejected))).join(
            "C", "Jo Do", "tok", now=NOW
        )
    assert wait.value.code == "retry_later" and wait.value.headers == {"Retry-After": "180"}
    # After the window the same row asks again.
    old = guest(status="rejected", decided_at=NOW - timedelta(minutes=4))
    recorder = Recorder()
    me, token = await GuestService(db(result(meeting()), result(old)), recorder).join(  # type: ignore[arg-type]
        "C", "Jo Do", "tok", now=NOW
    )
    assert token is None and me.status == "pending" and old.decided_at is None
    assert recorder.events[0][0] == "requested"
    # A waiting device replaces its name.
    waiting = guest()
    recorder = Recorder()
    me, token = await GuestService(db(result(meeting()), result(waiting)), recorder).join(  # type: ignore[arg-type]
        "C", "Jana R.", "tok", now=NOW
    )
    assert token is None and waiting.display_name == "Jana R."
    assert recorder.events[0][0] == "updated"


async def test_join_removed_left_and_other_meeting() -> None:
    removed = guest(status="removed", decided_at=NOW)
    with pytest.raises(RateLimitedError):
        await GuestService(db(result(meeting()), result(removed))).join(
            "C", "Jo Do", "tok", now=NOW
        )
    left = guest(status="left", decided_at=NOW)
    me, token = await GuestService(db(result(meeting()), result(left), scalars=[1])).join(
        "C", "Jo Do", "tok", now=NOW
    )
    assert token is not None and left.token_hash is None and me.number == 2
    for status in ("pending", "admitted"):
        elsewhere = guest(meeting_id=uuid4(), status=status)
        recorder = Recorder()
        session = db(result(meeting()), result(elsewhere))
        _, token = await GuestService(session, recorder).join(  # type: ignore[arg-type]
            "C", "Jo Do", "tok", now=NOW
        )
        assert token is not None
        assert (elsewhere.status, elsewhere.display_name, elsewhere.token_hash) == (
            "left",
            None,
            None,
        )
        assert elsewhere.decided_at == NOW
        # The other meeting hears about it, so its lead list and the device socket follow.
        left = [e for e in recorder.events if e[0] == "updated"]
        assert left and left[0][1][0].status == "left"
    rejected_elsewhere = guest(meeting_id=uuid4(), status="rejected")
    await GuestService(db(result(meeting()), result(rejected_elsewhere))).join(
        "C", "Jo Do", "tok", now=NOW
    )
    assert rejected_elsewhere.status == "rejected" and rejected_elsewhere.token_hash is None


async def test_me_rename_leave() -> None:
    row = guest(last_seen_at=NOW - timedelta(minutes=5))
    session = db(result(row), result(meeting()))
    me = await GuestService(session).me("7KQ4MP", "tok", now=NOW)
    assert me.view is None and row.last_seen_at == NOW and session.committed == 1
    fresh = guest(last_seen_at=NOW)
    session = db(result(fresh), result(meeting()))
    await GuestService(session).me("7KQ4MP", "tok", now=NOW)
    assert session.committed == 0
    # Rename while waiting, 409 afterwards.
    waiting = guest()
    out = await GuestService(db(result(waiting), result(meeting()))).rename_self(
        "7KQ4MP", "tok", "Jana R.", now=NOW
    )
    assert out.display_name == "Jana R."
    with pytest.raises(ConflictError):
        await GuestService(db(result(guest(status="admitted")), result(meeting()))).rename_self(
            "7KQ4MP", "tok", "X Y", now=NOW
        )
    # Leave pseudonymizes; a rejected guest keeps the status.
    leaving = guest(status="admitted")
    await GuestService(db(result(leaving), result(meeting()))).leave("7KQ4MP", "tok", now=NOW)
    assert (leaving.status, leaving.display_name, leaving.token_hash) == ("left", None, None)
    rejected = guest(status="rejected", decided_at=NOW)
    await GuestService(db(result(rejected), result(meeting()))).leave("7KQ4MP", "tok", now=NOW)
    assert rejected.status == "rejected" and rejected.display_name is None


async def test_cast_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeVoting:
        def __init__(self) -> None:
            self.casts: list[Any] = []

        async def cast_guest(
            self, vote_id: UUID, guest_id: UUID, choice: str, *, now: datetime
        ) -> Any:
            self.casts.append((vote_id, guest_id, choice))
            return SimpleNamespace(status="cast")

        async def get(self, vote_id: UUID) -> Any:
            return SimpleNamespace(id=vote_id)

    voting = FakeVoting()
    pending = guest()
    with pytest.raises(ForbiddenError) as not_admitted:
        await GuestService(db(result(pending), result(meeting()))).cast(
            "7KQ4MP",
            "tok",
            uuid4(),
            "yes",
            voting=voting,  # type: ignore[arg-type]
            now=NOW,  # type: ignore[arg-type]
        )
    assert not_admitted.value.code == "guest_not_admitted"
    admitted = guest(status="admitted")
    with pytest.raises(ForbiddenError) as watch:
        await GuestService(db(result(admitted), result(meeting(guests_mode="watch")))).cast(
            "7KQ4MP",
            "tok",
            uuid4(),
            "yes",
            voting=voting,  # type: ignore[arg-type]
            now=NOW,  # type: ignore[arg-type]
        )
    assert watch.value.code == "guests_watch_only"
    vote = SimpleNamespace(id=uuid4(), meeting_id=MID, agenda_item_id=uuid4())
    # Unknown vote, a vote of another meeting, a vote of a non-public item: 404.
    for got, non_public in (
        (None, None),
        (SimpleNamespace(id=vote.id, meeting_id=uuid4(), agenda_item_id=None), None),
        (vote, True),
    ):
        session = db(result(admitted), result(meeting()), scalars=[non_public])
        session.get_results = [got]
        with pytest.raises(NotFoundError):
            await GuestService(session).cast(
                "7KQ4MP",
                "tok",
                vote.id,
                "yes",
                voting=voting,  # type: ignore[arg-type]
                now=NOW,  # type: ignore[arg-type]
            )  # type: ignore[arg-type]
    for recorder in (Recorder(), Recorder(fail=True), None):
        session = db(result(admitted), result(meeting()), scalars=[False])
        session.get_results = [vote]
        out = await GuestService(session, recorder).cast(  # type: ignore[arg-type]
            "7KQ4MP",
            "tok",
            vote.id,
            "yes",
            voting=voting,  # type: ignore[arg-type]
            now=NOW,  # type: ignore[arg-type]
        )
        assert out.status == "cast"
    assert len(voting.casts) == 3


async def test_vote_is_public() -> None:
    assert await GuestService(db(scalars=[None])).vote_is_public(uuid4(), MID) is False
    assert await GuestService(db(scalars=[uuid4(), False])).vote_is_public(uuid4(), MID) is True


async def test_admitted_view_hides_non_public_content(monkeypatch: pytest.MonkeyPatch) -> None:
    app_id = uuid4()
    items = [
        SimpleNamespace(id=uuid4(), application_id=app_id, title=None, non_public=False, body="A"),
        SimpleNamespace(
            id=uuid4(), application_id=None, title="Personal", non_public=True, body="secret"
        ),
    ]
    config = VoteConfig.model_validate(
        {"options": ["yes", "no"], "majorityRule": "simple", "guestsVote": True}
    )
    vote = SimpleNamespace(
        id=uuid4(),
        agenda_item_id=items[0].id,
        question="Q?",
        config=config.model_dump(by_alias=True),
        status="open",
        opens_at=NOW,
        closed_at=None,
        result=None,
    )

    async def fake_get(self: Any, vote_id: UUID) -> VoteOut:
        return VoteOut(
            id=vote_id,
            eligibleGroup=str(GID),
            config=config,
            status="open",
            secret=False,
            tally=TallyOut(
                counts={}, eligible=3, voted=1, present=3, revealed=False, quorumMet=True
            ),
            guestsVote=True,
        )

    async def fake_ballot(self: Any, v: Any, voter: str, *, secret: bool) -> MyBallot:
        return MyBallot(cast=False)

    monkeypatch.setattr(guests_mod.VotingService, "get", fake_get)
    monkeypatch.setattr(guests_mod.VotingService, "my_ballot", fake_ballot)
    admitted = guest(status="admitted")
    session = db(
        result(admitted),
        result(meeting()),
        result(*items),
        result((app_id, {"title": "Zuschuss"})),
        result(("admitted", 1)),
        result(vote),
        scalars=[2, "FS"],
    )
    me = await GuestService(session).me("7KQ4MP", "tok", now=NOW)
    assert me.view is not None
    assert [(a.title, a.kind, a.body) for a in me.view.agenda] == [
        ("Zuschuss", "application", "A"),
        ("Personal", "freetext", None),
    ]
    assert me.view.present_members == 2 and me.view.admitted_guests == 1
    [gv] = me.view.votes
    assert gv.can_cast is True and gv.guests_vote is True


async def test_view_without_public_items() -> None:
    items = [
        SimpleNamespace(id=uuid4(), application_id=None, title="NÖ", non_public=True, body="x")
    ]
    admitted = guest(status="admitted")
    session = db(result(admitted), result(meeting()), result(*items), result(), scalars=[0, "FS"])
    me = await GuestService(session).me("7KQ4MP", "tok", now=NOW)
    assert me.view is not None and me.view.votes == []
