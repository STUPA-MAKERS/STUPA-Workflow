"""Unit tests of ``GremienService`` with a queued fake session (no database).

The integration suite (``tests/integration/modules/gremien``) runs the same reads on
Postgres. Here every branch of the Python side runs: the range rules, the cursor, the
order of the next meeting, the member and former rows, the roster counts, the matrix
cells and the decision rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import true

from app.modules.auth.principal import Principal
from app.modules.gremien import service as svc
from app.modules.gremien.service import GremienService
from app.shared.config_schemas import VoteConfig
from app.shared.errors import BadRequestError, NotFoundError, ValidationProblem
from tests._support.auth_fakes import fake_session, result

TZ = "Europe/Berlin"
G1 = uuid.uuid4()
G2 = uuid.uuid4()
ME = Principal(sub="me")
ADMIN = Principal(sub="admin", roles=["admin"])
PLAIN = VoteConfig.model_validate(
    {"options": ["yes", "no", "abstain"], "majorityRule": "simple"}
).model_dump(by_alias=True)
SECRET = VoteConfig.model_validate(
    {"options": ["yes", "no", "abstain"], "majorityRule": "absolute", "secret": True}
).model_dump(by_alias=True)
ELECTION = {
    "seats": 1,
    "candidates": [{"id": "c1", "name": "Jonas"}, {"id": "c2", "name": "Mara"}],
}


def _svc(*results: Any, gets: tuple[Any, ...] = ()) -> GremienService:
    return GremienService(fake_session(*results, gets=gets), TZ)


# ------------------------------------------------------------------ helpers
def test_month_helpers() -> None:
    assert svc.month_key((2026, 5)) == "2026-05"
    assert svc.parse_month("2026-05") == (2026, 5)
    assert svc.shift_month((2026, 1), -1) == (2025, 12)
    assert svc.shift_month((2026, 12), 1) == (2027, 1)
    assert svc.months_between((2025, 11), (2026, 2)) == [
        (2025, 11),
        (2025, 12),
        (2026, 1),
        (2026, 2),
    ]
    assert svc.logo_url(G1) == f"/api/gremien/{G1}/logo"


def test_month_range_defaults_to_six_months() -> None:
    months = svc.month_range(None, None, date(2026, 10, 15))
    assert months[0] == (2026, 5) and months[-1] == (2026, 10) and len(months) == 6


def test_month_range_given_bounds() -> None:
    assert svc.month_range("2026-01", "2026-02", date(2026, 10, 15)) == [(2026, 1), (2026, 2)]
    assert svc.month_range("2026-09", None, date(2026, 10, 15)) == [(2026, 9), (2026, 10)]
    assert len(svc.month_range("2024-11", "2026-10", date(2026, 10, 15))) == 24


@pytest.mark.parametrize(("start", "end"), [("2026-07", "2026-05"), ("2024-10", "2026-10")])
def test_month_range_refuses(start: str, end: str) -> None:
    with pytest.raises(ValidationProblem) as err:
        svc.month_range(start, end, date(2026, 10, 15))
    assert err.value.code == "invalid_month_range"


def test_cursor_round_trip() -> None:
    assert svc.decode_cursor(None) == 0
    assert svc.decode_cursor(svc.encode_cursor(60)) == 60


@pytest.mark.parametrize(
    "cursor",
    # bad base64, negative, "x|5", "nopipe", beyond the offset cap
    ["%%%", svc.encode_cursor(-1), "eHw1", "bm9waXBl", svc.encode_cursor(1_000_001)],
)
def test_cursor_refused(cursor: str) -> None:
    with pytest.raises(BadRequestError):
        svc.decode_cursor(cursor)


# ------------------------------------------------------------------ overview
async def test_overview_without_membership_is_empty() -> None:
    assert await _svc(result()).overview(ME) == []


async def test_overview_hides_own_gremien_from_a_capped_token() -> None:
    token = Principal(sub="me", scope_permissions=frozenset({"budget.write"}))
    service = _svc(result((G1, "member", None)))
    assert await service.overview(token) == []


async def test_overview_view_all_without_gremien_is_empty() -> None:
    assert await _svc(result(), result()).overview(ADMIN) == []


def _meeting(
    gid: uuid.UUID, status: str, day: date | None, start: time | None = None, **kw: Any
) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        gremium_id=gid,
        title=f"M {status}",
        date=day,
        start_time=start,
        end_time=None,
        status=status,
        started_at=kw.get("started_at"),
        closed_at=kw.get("closed_at"),
    )


async def test_overview_member_rows() -> None:
    g1 = SimpleNamespace(
        id=G1,
        name="AStA",
        slug="asta",
        quorum_percent=50,
        protocols_public=True,
        allow_vote_delegation=False,
    )
    g2 = SimpleNamespace(
        id=G2,
        name="STUPA",
        slug="stupa",
        quorum_percent=None,
        protocols_public=None,
        allow_vote_delegation=True,
    )
    later = _meeting(G1, "planned", date(2099, 2, 1))
    live = _meeting(G1, "live", date(2026, 10, 1))
    undated = _meeting(G1, "planned", None)
    only_undated = _meeting(G2, "planned", None)
    service = _svc(
        result((G1, "vorstand", {"de": "Vorstand"}), (G2, "member", None)),
        result(g1, g2),
        result((G1, 3)),
        result(later, live, undated, only_undated),
        result(G1),
    )
    rows = await service.overview(ME)
    first, second = rows
    assert (
        first.is_member and first.role_key == "vorstand" and first.role_name == {"de": "Vorstand"}
    )
    assert first.member_count == 3 and first.live and first.next_meeting is not None
    assert first.next_meeting.id == live.id
    assert first.logo_url == f"/api/gremien/{G1}/logo"
    assert first.protocols_public and not first.allow_vote_delegation
    assert second.role_name == {} and second.member_count == 0 and not second.live
    assert second.next_meeting is not None and second.next_meeting.id == only_undated.id
    assert second.logo_url is None and second.protocols_public is False


async def test_overview_view_all_marks_foreign_gremien() -> None:
    g2 = SimpleNamespace(
        id=G2,
        name="STUPA",
        slug="stupa",
        quorum_percent=None,
        protocols_public=False,
        allow_vote_delegation=False,
    )
    dated = _meeting(G2, "planned", date(2099, 1, 1), time(18, 0))
    earlier = _meeting(G2, "planned", date(2098, 1, 1))
    rows = await _svc(result(), result(g2), result(), result(dated, earlier), result()).overview(
        ADMIN
    )
    assert not rows[0].is_member and rows[0].role_key is None and rows[0].role_name is None
    assert rows[0].next_meeting is not None and rows[0].next_meeting.id == earlier.id


# ------------------------------------------------------------------ members
NOW = datetime.now(UTC)
PAST = datetime(2020, 1, 1, tzinfo=UTC)


def _membership(valid_until: datetime | None = None, valid_from: datetime | None = None) -> Any:
    return SimpleNamespace(
        principal_id=uuid.uuid4(),
        gremium_role_id=uuid.uuid4(),
        valid_from=valid_from,
        valid_until=valid_until,
    )


def _member_rows() -> list[tuple[Any, ...]]:
    return [
        (_membership(), "member", {"de": "Mitglied"}, "Zoe", "z@x.de", True, "z"),
        (_membership(), "member", None, None, "a@x.de", True, "a"),
        (_membership(), "protokoll", {"de": "Protokoll"}, "Paul", None, True, "p"),
        (_membership(), "vorstand", {"de": "Vorstand"}, "Me", "me@x.de", True, "me"),
        (_membership(), "manager", {"de": "Manager"}, "Max", "m@x.de", False, "m"),
        (_membership(valid_until=PAST), "member", {}, "Old", "o@x.de", True, "o"),
        (
            _membership(valid_from=datetime(2999, 1, 1, tzinfo=UTC)),
            "member",
            {},
            "Next",
            None,
            True,
            "n",
        ),
        (_membership(), "member", {}, None, None, None, None),
    ]


async def test_members_current_by_role_and_name() -> None:
    rows = await _svc(result(*_member_rows())).members(G1, ME, former=False)
    assert [(r.role_key, r.display_name or r.email) for r in rows] == [
        ("vorstand", "Me"),
        ("protokoll", "Paul"),
        ("member", "a@x.de"),
        ("member", "Zoe"),
    ]
    assert rows[0].is_self and not rows[1].is_self
    assert rows[2].role_name == {}


async def test_members_former() -> None:
    rows = await _svc(result(*_member_rows())).members(G1, ME, former=True)
    assert [r.display_name for r in rows] == ["Max", None, "Next", "Old"]
    assert not any(r.is_self for r in rows)


# ------------------------------------------------------------------ meetings
async def test_meetings_empty() -> None:
    assert await _svc(result()).meetings(G1) == []


async def test_meetings_counts_the_roster() -> None:
    closed = _meeting(
        G1,
        "closed",
        date(2026, 5, 10),
        time(18, 0),
        started_at=datetime(2026, 5, 10, 16, 0, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, 18, 0, tzinfo=UTC),
    )
    planned = _meeting(G1, "planned", None)
    member, left, guest = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    service = _svc(
        result(closed, planned),
        result((closed.id, 4)),
        result((closed.id, "final")),
        result(
            (closed.id, member, "present"),
            (closed.id, guest, "present"),
            (closed.id, left, "excused"),
        ),
        result(
            (member, None, None),
            (left, None, datetime(2026, 5, 1, tzinfo=UTC)),
            (uuid.uuid4(), datetime(2026, 6, 1, tzinfo=UTC), None),
        ),
    )
    first, second = await service.meetings(G1)
    assert (first.agenda_item_count, first.present_count, first.member_count) == (4, 2, 3)
    assert first.protocol_status == "final"
    # The planned meeting has the window "now": the member and the one who starts in June.
    assert (second.agenda_item_count, second.present_count, second.member_count) == (0, 0, 2)
    assert second.protocol_status is None


# ------------------------------------------------------------------ attendance
async def test_attendance_matrix_rows() -> None:
    me_id, guest_id, old_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    service = _svc(
        result(("2026-05", 2)),
        result((me_id, "2026-05", 2, 0, 0), (guest_id, "2026-05", 1, 1, 1)),
        result(
            (me_id, None, None, "vorstand", {"de": "Vorstand"}),
            (old_id, None, datetime(2026, 1, 1, tzinfo=UTC), "member", None),
        ),
        result((me_id, "Me", "me"), (guest_id, "Gast", "g")),
    )
    out = await service.attendance(G1, ME, from_month="2026-05", to_month="2026-06")
    assert out.from_month == "2026-05" and out.to_month == "2026-06"
    assert [(m.month, m.meetings) for m in out.months] == [("2026-05", 2), ("2026-06", 0)]
    assert [r.display_name for r in out.rows] == ["Gast", "Me"]
    guest, me = out.rows
    assert guest.role_key is None and guest.role_name is None and not guest.is_self
    assert [(c.member, c.present, c.excused, c.delegated) for c in guest.cells] == [
        (False, 1, 1, 1),
        (False, 0, 0, 0),
    ]
    assert me.is_self and me.role_key == "vorstand" and me.role_name == {"de": "Vorstand"}
    assert [(c.member, c.present) for c in me.cells] == [(True, 2), (True, 0)]


async def test_attendance_without_people() -> None:
    out = await _svc(result(), result(), result()).attendance(
        G1, ME, from_month=None, to_month=None
    )
    assert out.rows == [] and len(out.months) == 6


async def test_attendance_unknown_principal_row() -> None:
    pid = uuid.uuid4()
    out = await _svc(result(), result((pid, "2026-05", 1, 0, 0)), result(), result()).attendance(
        G1, ME, from_month="2026-05", to_month="2026-05"
    )
    assert out.rows[0].display_name is None and not out.rows[0].is_self


# ------------------------------------------------------------------ member attendance
async def test_member_attendance_unknown_principal() -> None:
    with pytest.raises(NotFoundError) as err:
        await _svc().member_attendance(G1, uuid.uuid4(), "2026-05")
    assert err.value.code == "member_not_found"


async def test_member_attendance_unrelated_principal() -> None:
    with pytest.raises(NotFoundError):
        await _svc(result(None), gets=(SimpleNamespace(display_name="X"),)).member_attendance(
            G1, uuid.uuid4(), "2026-05"
        )


async def test_member_attendance_without_meetings() -> None:
    out = await _svc(
        result(True), result(), gets=(SimpleNamespace(display_name="X"),)
    ).member_attendance(G1, uuid.uuid4(), "2026-12")
    assert out.meetings == [] and out.month == "2026-12" and out.display_name == "X"


async def test_member_attendance_states() -> None:
    m = [uuid.uuid4() for _ in range(5)]
    day = date(2026, 5, 1)
    service = _svc(
        result(True),
        result(*((mid, f"S{n}", day, time(18, 0)) for n, mid in enumerate(m))),
        result((m[0], "present"), (m[1], "excused"), (m[2], "absent"), (m[3], "excused")),
        result(
            (m[3], "Kai"),
        ),
        gets=(SimpleNamespace(display_name="Finn"),),
    )
    out = await service.member_attendance(G1, uuid.uuid4(), "2026-05")
    assert [(r.status, r.delegate_name) for r in out.meetings] == [
        ("present", None),
        ("excused", None),
        ("absent", None),
        ("delegated", "Kai"),
        ("absent", None),
    ]


# ------------------------------------------------------------------ decisions
@pytest.fixture
def open_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _scope(_session: Any, _principal: Any) -> Any:
        return true()

    monkeypatch.setattr(svc, "read_scope", _scope)


def _vote(**kw: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "question": "Q",
        "config": PLAIN,
        "kind": "motion",
        "application_id": None,
        "result": "passed",
        "meeting_id": None,
        "closed_at": datetime(2026, 5, 10, tzinfo=UTC),
        "election_result": None,
    }
    return SimpleNamespace(**(base | kw))


@pytest.mark.usefixtures("open_scope")
@pytest.mark.parametrize(
    ("kind", "res"),
    [(None, None), ("election", "passed"), ("application", "rejected"), ("motion", None)],
)
async def test_decisions_filters_build(kind: Any, res: Any) -> None:
    page = await _svc(result()).decisions(
        G1, ME, cursor=None, q="  ", result=res, kind=kind, since=date(2026, 1, 1)
    )
    assert page.items == [] and page.next_cursor is None


@pytest.mark.usefixtures("open_scope")
async def test_decisions_rows() -> None:
    app_id = uuid.uuid4()
    motion = _vote(application_id=app_id, meeting_id=uuid.uuid4())
    secret = _vote(config=SECRET, result="rejected")
    election = _vote(
        kind="election",
        config=ELECTION,
        result="elected",
        election_result={"counts": {"c1": 2}, "ballots": 3, "elected": ["c1", "c9"]},
    )
    pending = _vote(kind="election", config=ELECTION, result=None, election_result=None)
    service = _svc(
        result(
            (motion, "33. Sitzung", date(2026, 5, 10)),
            (secret, None, None),
            (election, None, None),
            (pending, None, None),
        ),
        result((app_id, {"title": " Lastenrad "}, Decimal("2890.00"))),
        result((motion.id, "yes", 2), (motion.id, "no", 1), (motion.id, None, 1)),
        result((secret.id, "abstain", 2)),
    )
    page = await service.decisions(G1, ME, cursor=None, q="Rad", result=None, kind=None, since=None)
    first, second, third, fourth = page.items
    assert first.kind == "application" and first.application_title == "Lastenrad"
    assert first.amount == Decimal("2890.00") and first.meeting_title == "33. Sitzung"
    assert first.counts is not None and (
        first.counts.yes,
        first.counts.no,
        first.counts.abstain,
    ) == (2, 1, 0)
    assert first.ballots == 4 and first.majority_rule == "simple" and not first.secret
    assert second.kind == "motion" and second.secret and second.majority_rule == "absolute"
    assert second.counts is not None and second.counts.abstain == 2 and second.ballots == 2
    assert third.kind == "election" and third.elected == ["Jonas", "c9"] and third.ballots == 3
    assert third.counts is None and third.majority_rule is None and third.secret
    assert fourth.elected == [] and fourth.ballots == 0


@pytest.mark.usefixtures("open_scope")
async def test_decisions_next_page() -> None:
    votes = [(_vote(), None, None) for _ in range(svc.DECISION_PAGE + 1)]
    service = _svc(result(*votes), result())
    page = await service.decisions(
        G1, ME, cursor=svc.encode_cursor(30), q=None, result=None, kind=None, since=None
    )
    assert len(page.items) == svc.DECISION_PAGE
    assert page.next_cursor == svc.encode_cursor(60)
