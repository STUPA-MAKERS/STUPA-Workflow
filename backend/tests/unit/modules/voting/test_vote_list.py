"""The vote list (``GET /votes``) without a database.

A result-queue fake drives every branch of ``app.modules.voting.listing``: the read
scope (meeting scope, ``application.read``, voter and manager keys), the search, the
gremium filter, the page decoration and the own ballots. The integration suite runs
the same queries against Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.livevote.service import MeetingService
from app.modules.voting import listing
from app.modules.voting.router import get_voting_service
from app.modules.voting.schemas import MyBallot, VoteListItem
from app.modules.voting.service import VotingService
from app.shared.config_schemas import VoteConfig
from app.shared.paging import Page
from tests._support.flow_fakes import fake_session, result

GID = UUID("00000000-0000-0000-0000-00000000c0de")
OTHER = UUID("00000000-0000-0000-0000-00000000beef")
CREATED = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _config(*, secret: bool = False) -> dict[str, Any]:
    return VoteConfig.model_validate(
        {"options": ["yes", "no", "abstain"], "majorityRule": "simple", "secret": secret}
    ).model_dump(by_alias=True)


def _vote(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(),
        "question": "Q?",
        "status": "open",
        "result": None,
        "config": _config(),
        "application_id": uuid4(),
        "meeting_id": None,
        "agenda_item_id": None,
        "eligible_group": str(GID),
        "created_at": CREATED,
        "opens_at": CREATED,
        "closed_at": None,
        "closes_at": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _sql(clause: Any) -> str:
    return str(clause.compile(dialect=postgresql.dialect()))


@pytest.fixture
def scope(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the meeting read scope and the gremium manage rights."""
    state: dict[str, Any] = {"visible": {GID}, "delegated": set(), "manage": {}}

    async def _meeting_scope(_self: MeetingService, _p: Principal) -> tuple[Any, Any]:
        return state["visible"], state["delegated"]

    async def _ids_for(_s: Any, _p: Principal, perm: str) -> set[UUID]:
        return set(state["manage"].get(perm, set()))

    monkeypatch.setattr(MeetingService, "meeting_read_scope", _meeting_scope)
    monkeypatch.setattr(listing, "gremium_ids_for", _ids_for)
    return state


# ------------------------------------------------------------------ read scope
async def test_scope_reader_of_applications_reads_every_standalone_vote(
    scope: dict[str, Any],
) -> None:
    reader = Principal(sub="r", permissions={"application.read"})
    clause = await listing.read_scope(fake_session(), reader)
    sql = _sql(clause)
    assert "vote.meeting_id IS NULL" in sql
    assert "eligible_group IN" not in sql


async def test_scope_all_meetings_for_view_all(scope: dict[str, Any]) -> None:
    scope["visible"] = None
    clause = await listing.read_scope(
        fake_session(), Principal(sub="r", permissions={"application.read_all"})
    )
    sql = _sql(clause)
    assert "meeting.gremium_id IN" not in sql
    assert "vote.meeting_id IS NOT NULL" in sql


async def test_scope_voter_and_manager_keys(scope: dict[str, Any]) -> None:
    scope["delegated"] = {uuid4()}
    scope["manage"] = {"vote.manage": {OTHER}, "session.manage": set()}
    principal = Principal(sub="v", groups={vote_group_key(GID), "oidc-group"})
    clause = await listing.read_scope(fake_session(), principal)
    params = clause.compile(dialect=postgresql.dialect()).params
    keys = [v for v in params.values() if isinstance(v, list) and v and isinstance(v[0], str)]
    assert sorted([str(GID), str(OTHER)]) in keys
    assert "meeting.gremium_id IN" in _sql(clause)


async def test_scope_without_any_key_reads_no_standalone_vote(scope: dict[str, Any]) -> None:
    clause = await listing.read_scope(fake_session(), Principal(sub="x"))
    sql = _sql(clause)
    # `or_(meeting, false())` folds to the meeting part alone.
    assert "eligible_group IN" not in sql
    assert "vote.meeting_id IS NULL" not in sql


# ------------------------------------------------------------------ search
def test_search_clause_empty_matches_all() -> None:
    assert _sql(listing._search_clause(None)) == "true"
    assert _sql(listing._search_clause(" \x00 ")) == "true"


def test_search_clause_escapes_wildcards() -> None:
    clause = listing._search_clause("50%_")
    compiled = clause.compile(dialect=postgresql.dialect())
    assert "ILIKE" in str(compiled).upper()
    assert "%50\\%\\_%" in compiled.params.values()


# ------------------------------------------------------------------ list
async def test_list_orders_decorates_and_reads_own_ballots(scope: dict[str, Any]) -> None:
    meeting_id, item_id = uuid4(), uuid4()
    live = _vote(meeting_id=meeting_id, agenda_item_id=item_id)
    secret = _vote(config=_config(secret=True), status="closed", result="passed")
    legacy = _vote(eligible_group="free-key", status="cancelled", question=None)
    db = fake_session(
        result(
            (live, "34. Sitzung", GID),
            (secret, None, None),
            (legacy, None, None),
        ),
        result((GID, "Studierendenparlament")),  # gremium names
        result((item_id, 3), (uuid4(), 1)),  # agenda numbers
        result((live.id, "yes")),  # open ballots
        result(secret.id),  # secret markers
    )
    db.scalar_results = [3]
    principal = Principal(sub="v", groups={vote_group_key(GID)})
    page = await listing.list_votes(
        db, principal, statuses=["open", "open", "closed", "cancelled"], q="Sitzung",
        gremium_id=GID, limit=10, offset=0,
    )
    assert page.total == 3
    first, second, third = page.items
    assert first.meeting_title == "34. Sitzung"
    assert first.agenda_position == 3
    assert first.gremium_name == "Studierendenparlament"
    assert first.my_ballot == MyBallot(cast=True, choice="yes")
    assert first.can_cast is True
    assert second.secret is True
    assert second.my_ballot == MyBallot(cast=True, choice=None)
    assert second.agenda_position is None
    assert third.gremium_id is None
    assert third.gremium_name is None
    assert third.my_ballot == MyBallot(cast=False)
    assert third.can_cast is False
    row_sql = _sql(db.statements[0])
    assert "ORDER BY CASE" in row_sql
    assert "coalesce(CAST(meeting.gremium_id AS TEXT), vote.eligible_group)" in row_sql


async def test_list_empty_page_skips_decoration(scope: dict[str, Any]) -> None:
    db = fake_session(result())
    page = await listing.list_votes(db, Principal(sub="x"), limit=5, offset=10)
    assert page.items == []
    assert page.total == 0
    assert page.offset == 10
    # Only the row query ran: no name, agenda or ballot query for an empty page.
    assert len(db.statements) == 1
    # The default leaves out the drafts.
    sql = str(db.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "vote.status IN ('open', 'closed', 'cancelled')" in sql


async def test_list_without_gremium_or_agenda_skips_those_queries(scope: dict[str, Any]) -> None:
    legacy = _vote(eligible_group="free-key", config=_config(secret=True))
    db = fake_session(result((legacy, None, None)), result())
    db.scalar_results = [1]
    page = await listing.list_votes(db, Principal(sub="x"), limit=5, offset=0)
    assert page.items[0].my_ballot.cast is False
    # Rows, then only the secret markers.
    assert len(db.statements) == 2


async def test_list_plain_votes_skip_the_marker_query(scope: dict[str, Any]) -> None:
    plain = _vote(status="closed", result="rejected")
    db = fake_session(result((plain, None, None)), result((GID, "StuPa")), result())
    db.scalar_results = [1]
    page = await listing.list_votes(db, Principal(sub="x"), limit=5, offset=0)
    assert page.items[0].my_ballot == MyBallot(cast=False)
    assert page.items[0].gremium_name == "StuPa"
    # Rows, gremium names, then only the open ballots.
    assert len(db.statements) == 3


async def test_service_delegates_to_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def _list(session: Any, principal: Principal, **kw: Any) -> Page[VoteListItem]:
        seen.update(kw)
        return Page[VoteListItem](items=[], total=0, limit=kw["limit"], offset=kw["offset"])

    monkeypatch.setattr(listing, "list_votes", _list)
    out = await VotingService(fake_session()).list_visible(Principal(sub="p"), q="x")
    assert out.total == 0
    assert seen == {"statuses": None, "gremium_id": None, "q": "x", "limit": 50, "offset": 0}


async def test_meeting_read_scope_all_and_scoped() -> None:
    svc = MeetingService(fake_session())
    assert await svc.meeting_read_scope(Principal(sub="a", roles=["admin"])) == (None, set())

    mid = uuid4()

    async def _visible(_p: Principal) -> set[UUID]:
        return {GID}

    async def _delegated(_sub: str) -> set[UUID]:
        return {mid}

    svc._visible_gremium_ids = _visible  # type: ignore[method-assign]
    svc._delegated_meeting_ids = _delegated  # type: ignore[method-assign]
    assert await svc.meeting_read_scope(Principal(sub="m")) == ({GID}, {mid})


# ------------------------------------------------------------------ router
class _ListService:
    def __init__(self) -> None:
        self.kw: dict[str, Any] = {}

    async def list_visible(self, principal: Principal, **kw: Any) -> Page[VoteListItem]:
        self.kw = {"sub": principal.sub, **kw}
        item = VoteListItem(
            id=uuid4(), status="open", secret=False, createdAt=CREATED, canCast=True
        )
        return Page[VoteListItem](items=[item], total=1, limit=kw["limit"], offset=kw["offset"])


def _client(svc: _ListService, *, signed_in: bool = True) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_voting_service] = lambda: svc
    if signed_in:
        app.dependency_overrides[get_current_principal] = lambda: Principal(sub="p")
        app.dependency_overrides[get_current_applicant] = lambda: None
    return TestClient(app)


def test_router_list_requires_auth_401() -> None:
    r = _client(_ListService(), signed_in=False).get("/api/votes")
    assert r.status_code == 401
    assert r.headers["content-type"] == "application/problem+json"


def test_router_list_passes_filters() -> None:
    svc = _ListService()
    r = _client(svc).get(
        "/api/votes",
        params=[("status", "open"), ("status", "draft"), ("gremiumId", str(GID)), ("q", "x"),
                ("limit", "20"), ("offset", "40")],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["canCast"] is True
    assert body["items"][0]["myBallot"] == {"cast": False, "choice": None}
    assert svc.kw == {
        "sub": "p",
        "statuses": ["open", "draft"],
        "gremium_id": GID,
        "q": "x",
        "limit": 20,
        "offset": 40,
    }


def test_router_list_rejects_unknown_status_422() -> None:
    r = _client(_ListService()).get("/api/votes", params={"status": "running"})
    assert r.status_code == 422
    assert r.headers["content-type"] == "application/problem+json"
