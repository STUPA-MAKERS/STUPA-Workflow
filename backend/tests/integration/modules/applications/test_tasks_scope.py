"""Integration (real Postgres): the task list shows only what the principal can do.

`GET /applications/tasks` once loaded every confirmed application. It kept a vote state
for a voter of the application Gremium or for a plain member of the vote Gremium, and a
firable transition for every holder of the global `application.transition`. It did not
check the read access. A voter of Gremium A thus saw the title and the amount of an
application in a vote of Gremium B, and a transition holder saw every application.

The fixed rule:

* a task is always an application that the principal can read (the rule of the list),
* a ballot task needs an open vote that `POST /votes/{id}/ballot` takes from the
  principal now, and
* a transition task needs a manual transition with `requiresAction` that
  `POST /applications/{id}/transition` (or `/applicant-transition` for the creator)
  accepts from the principal.

`test_tasks_per_principal` names the exact tasks of each principal. The property test
`test_tasks_agree_with_the_action_routes` tries every action of every principal on every
application through the real routes, each one in a transaction that rolls back. A
listed task must have an accepted action, and an application that is not listed must
have none.

Test isolation: the `engine` fixture truncates the application, flow and vote tables,
NOT `principal` and `gremium`. Every unique key there carries a fresh tag per seed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db import get_session
from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.admin.models import ApplicationType, Gremium, GremiumMembership, GremiumRole
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import resolve_principal
from app.modules.flow.dispatch import NullActionDispatcher
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.flow.router import get_action_dispatcher
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.modules.voting.models import Vote
from app.settings import Settings, get_settings, load_settings
from app.shared.config_schemas import FormFieldDef

pytestmark = pytest.mark.integration

_VOTE_CONFIG: dict[str, Any] = {
    "options": ["yes", "no", "abstain"],
    "majorityRule": "simple",
    "secret": False,
}


@dataclass
class _World:
    principals: dict[str, Principal] = field(default_factory=dict)
    apps: dict[str, uuid.UUID] = field(default_factory=dict)
    # The open votes per application key.
    votes: dict[str, list[uuid.UUID]] = field(default_factory=dict)
    # Every transition of the flow, for the probes.
    transitions: list[Transition] = field(default_factory=list)


@pytest.fixture
async def db_engine(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(migrated[1])
    yield eng
    await eng.dispose()


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return load_settings(
        database_url=migrated[1],
        session_secret="session-secret-tasks-scope-0000",
        magic_link_secret="magic-link-secret-tasks-scope0",
        cookie_secure=False,
        # The probes send many writes from one client; the default limit needs Redis.
        rate_limit_enabled=False,
    )


async def _member(
    session: AsyncSession, sub: str, gremium: Gremium, perms: list[str], tag: str
) -> PrincipalRow:
    """Create a principal with an active membership and a role with ``perms``."""
    row = PrincipalRow(sub=sub, display_name=sub)
    role = GremiumRole(
        gremium_id=gremium.id,
        key=f"r-{sub}-{tag}"[:60],
        name_i18n={"de": sub},
        permissions=perms,
    )
    session.add_all([row, role])
    await session.flush()
    session.add(
        GremiumMembership(
            principal_id=row.id, gremium_id=gremium.id, gremium_role_id=role.id
        )
    )
    return row


async def _seed(maker: async_sessionmaker[AsyncSession]) -> _World:  # noqa: PLR0915
    world = _World()
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        g_a = Gremium(name="Gremium A", slug=f"a-{tag}")
        g_b = Gremium(name="Gremium B", slug=f"b-{tag}")
        session.add_all([g_a, g_b])
        await session.flush()

        # The principals. The gremium facts come from the database through
        # `resolve_principal`; the global permissions are set on the object.
        rows = {
            # A voter of Gremium A, no global right.
            "voter_a": await _member(session, f"voter-a-{tag}", g_a, ["vote.cast"], tag),
            # A member of Gremium A whose role holds no vote.cast.
            "plain_a": await _member(session, f"plain-a-{tag}", g_a, [], tag),
            # The lead of Gremium B with every gremium right, plus the global
            # transition right, but without the global read right.
            "lead_b": await _member(
                session,
                f"lead-b-{tag}",
                g_b,
                ["session.manage", "vote.manage", "vote.cast", "protocol.write"],
                tag,
            ),
        }
        for key in ("mitglied", "admin", "owner", "other", "token"):
            rows[key] = PrincipalRow(sub=f"{key}-{tag}", display_name=key)
            session.add(rows[key])
        await session.flush()

        type_a = ApplicationType(
            gremium_id=g_a.id, key=f"ta-{tag}", name_i18n={}, has_budget=False
        )
        type_b = ApplicationType(
            gremium_id=g_b.id, key=f"tb-{tag}", name_i18n={}, has_budget=False
        )
        session.add_all([type_a, type_b])
        await session.commit()
        for app_type in (type_a, type_b):
            await FormsService(session).create_form_version(
                app_type.id,
                FormVersionCreate(
                    fields=[
                        FormFieldDef(
                            key="title", type="text", label={"de": "Titel"}, required=True
                        )
                    ],
                    activate=True,
                ),
                "tester",
            )

        flow = FlowVersion(version=1, active=True, editor_layout={})
        session.add(flow)
        await session.flush()
        draft = State(
            flow_version_id=flow.id, key="draft", label_i18n={"de": "Eingang"},
            is_initial=True,
        )
        vote_a = State(
            flow_version_id=flow.id, key="vote-a", label_i18n={"de": "Abstimmung A"},
            kind="vote", config={"gremiumId": str(g_a.id)},
        )
        vote_b = State(
            flow_version_id=flow.id, key="vote-b", label_i18n={"de": "Abstimmung B"},
            kind="vote", config={"gremiumId": str(g_b.id)},
        )
        done = State(
            flow_version_id=flow.id, key="done", label_i18n={"de": "Fertig"},
            is_terminal=True,
        )
        session.add_all([draft, vote_a, vote_b, done])
        await session.flush()

        def _t(src: State, dst: State, **kw: Any) -> Transition:
            return Transition(
                flow_version_id=flow.id, from_state_id=src.id, to_state_id=dst.id,
                label_i18n={"de": "T"}, actions=[], **kw,
            )

        world.transitions = [
            # Open to every transition holder: a task.
            _t(draft, done, requires_action=True),
            # Optional: never a task, but the route fires it.
            _t(draft, done, requires_action=False, order=1),
            # Open to the applicant only: a task of the creator.
            _t(draft, done, requires_action=True, guard={"actorIsApplicant": True}, order=2),
            # Automatic: the worker fires it, nobody else.
            _t(draft, done, requires_action=True, automatic=True, guard={"hasField": "x"},
               order=3),
            # The vote outcome: never a manual action.
            _t(vote_a, done, branch="pass"),
            _t(vote_a, draft, branch="fail"),
            _t(vote_b, done, branch="pass"),
            _t(vote_b, draft, branch="fail"),
        ]
        session.add_all(world.transitions)
        await session.commit()

        svc = ApplicationsService(session)

        async def _app(app_type: ApplicationType, state: State, creator: str) -> uuid.UUID:
            payload = ApplicationCreate.model_validate(
                {
                    "typeId": str(app_type.id),
                    "data": {"title": "Antrag"},
                    "applicantEmail": "x@example.org",
                }
            )
            created, _ = await svc.create(payload, actor=rows[creator].sub)
            await session.execute(
                update(Application)
                .where(Application.id == created.id)
                .values(
                    current_state_id=state.id,
                    email_confirmed_at=datetime.now(UTC),
                    # The snapshot that the flow engine sets on entry into a vote state.
                    vote_gremium_id=(
                        uuid.UUID(state.config["gremiumId"]) if state.kind == "vote" else None
                    ),
                )
            )
            await session.commit()
            return created.id

        world.apps = {
            # Gremium A votes on an application of Gremium A.
            "a_vote": await _app(type_a, vote_a, "other"),
            # A vote state of Gremium A without an open vote.
            "a_vote_idle": await _app(type_a, vote_a, "other"),
            # An application of Gremium A in a vote of Gremium B. The old code showed
            # it to the voter of A, who can neither read it nor cast in it.
            "a_in_b": await _app(type_a, vote_b, "other"),
            "b_vote": await _app(type_b, vote_b, "other"),
            # Applications in the entry state, readable for the full readers only.
            "draft_a": await _app(type_a, draft, "other"),
            "draft_b": await _app(type_b, draft, "other"),
            # The own application of the applicant account.
            "own": await _app(type_b, draft, "owner"),
            "done": await _app(type_a, done, "other"),
        }
        for key, gremium in (("a_vote", g_a), ("a_in_b", g_b), ("b_vote", g_b)):
            vote = Vote(
                application_id=world.apps[key], eligible_group=str(gremium.id),
                question="Q", config=_VOTE_CONFIG, status="open", opens_at=datetime.now(UTC),
            )
            session.add(vote)
            await session.flush()
            world.votes[key] = [vote.id]
        # A draft vote does not open a ballot.
        session.add(
            Vote(
                application_id=world.apps["a_vote_idle"], eligible_group=str(g_a.id),
                question="Q", config=_VOTE_CONFIG, status="draft",
            )
        )
        world.votes["a_vote_idle"] = []
        await session.commit()

        now = datetime.now(UTC)
        for key in ("voter_a", "plain_a", "lead_b", "owner"):
            resolved = await resolve_principal(session, rows[key], now)
            world.principals[key] = Principal(
                sub=resolved.sub,
                roles=[],
                permissions=(
                    {"application.transition"} if key == "lead_b" else set()
                ),
                groups=resolved.groups,
            )
        world.principals["mitglied"] = Principal(
            sub=rows["mitglied"].sub, roles=["member"], permissions={"application.read"}
        )
        world.principals["admin"] = Principal(sub=rows["admin"].sub, roles=["admin"])
        # An OAuth agent token with `application.transition` but without the read right.
        world.principals["token"] = Principal(
            sub=rows["token"].sub,
            permissions={"application.transition"},
            scope_permissions=frozenset({"application.transition"}),
        )
    return world


@pytest.fixture
async def world(db_engine: AsyncEngine) -> _World:
    return await _seed(async_sessionmaker(db_engine, expire_on_commit=False))


@pytest.fixture
def api(settings: Settings) -> FastAPI:
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_action_dispatcher] = NullActionDispatcher
    application.dependency_overrides[get_current_applicant] = lambda: None
    return application


async def _call(
    api: FastAPI,
    db_engine: AsyncEngine,
    principal: Principal,
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
) -> httpx.Response:
    """Send one request in a transaction that rolls back afterwards.

    The session joins an outer transaction with savepoints, so the commit of a route
    stays inside it. Each probe therefore sees the seeded world, untouched.
    """
    async with db_engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )

        async def _session() -> AsyncIterator[AsyncSession]:
            yield session

        api.dependency_overrides[get_session] = _session
        api.dependency_overrides[get_current_principal] = lambda: principal
        try:
            transport = httpx.ASGITransport(app=api)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                return await client.request(method, url, json=body)
        finally:
            await session.close()
            await outer.rollback()


async def _tasks(api: FastAPI, db_engine: AsyncEngine, principal: Principal) -> set[uuid.UUID]:
    r = await _call(api, db_engine, principal, "GET", "/api/applications/tasks")
    assert r.status_code == 200, r.text
    return {uuid.UUID(item["id"]) for item in r.json()}


async def test_tasks_per_principal(
    world: _World, api: FastAPI, db_engine: AsyncEngine
) -> None:
    """Each principal sees exactly the applications that it can read and act on."""
    apps = world.apps
    expected = {
        # The ballot in Gremium A only. Not the idle vote state, and not the application
        # of Gremium A in the vote of Gremium B (no read access, no vote right there).
        "voter_a": {apps["a_vote"]},
        # A member without vote.cast reads the vote state of A, but cannot cast.
        "plain_a": set(),
        # The ballots of Gremium B. The global transition right gives no task on the
        # entry-state applications, because lead_b cannot read them.
        "lead_b": {apps["a_in_b"], apps["b_vote"]},
        # The global member reads everything, but has neither a vote nor a transition.
        "mitglied": set(),
        # The admin fires the open transition on every entry-state application. The
        # admin is in no Gremium, so no ballot.
        "admin": {apps["draft_a"], apps["draft_b"], apps["own"]},
        # The applicant account: the applicant transition of the own application.
        "owner": {apps["own"]},
        # The agent token reads nothing and never casts.
        "token": set(),
    }
    for key, principal in world.principals.items():
        assert await _tasks(api, db_engine, principal) == expected[key], key


async def _accepted_actions(
    api: FastAPI, db_engine: AsyncEngine, world: _World, principal: Principal, key: str
) -> list[str]:
    """Try every ballot and every task transition on one application. Return the accepted.

    A task transition is a transition with `requiresAction`. The probe tries it on the
    member route and on the applicant route. The automatic and the branch transitions
    are tried too: no route may accept them.
    """
    app_id = world.apps[key]
    accepted: list[str] = []
    for vote_id in world.votes.get(key, []):
        r = await _call(
            api, db_engine, principal, "POST", f"/api/votes/{vote_id}/ballot",
            {"choice": "yes"},
        )
        if r.status_code == 200:
            accepted.append(f"ballot:{vote_id}")
    for t in world.transitions:
        # An optional transition fires, but it is no task by definition.
        if not t.requires_action:
            continue
        for route in ("transition", "applicant-transition"):
            r = await _call(
                api, db_engine, principal, "POST", f"/api/applications/{app_id}/{route}",
                {"transitionId": str(t.id)},
            )
            if r.status_code == 200:
                assert not t.automatic and t.branch is None, (route, t.id)
                accepted.append(f"{route}:{t.id}")
    return accepted


async def test_tasks_agree_with_the_action_routes(
    world: _World, api: FastAPI, db_engine: AsyncEngine
) -> None:
    """A listed task has an accepted action; an unlisted application has none."""
    for name, principal in world.principals.items():
        tasks = await _tasks(api, db_engine, principal)
        for key, app_id in world.apps.items():
            accepted = await _accepted_actions(api, db_engine, world, principal, key)
            assert (app_id in tasks) == bool(accepted), (name, key, accepted)


async def test_transition_routes_refuse_an_unreadable_application(
    world: _World, api: FastAPI, db_engine: AsyncEngine
) -> None:
    """A holder of `application.transition` cannot list or fire on what it cannot read."""
    lead_b = world.principals["lead_b"]
    app_id = world.apps["draft_a"]
    r = await _call(api, db_engine, lead_b, "GET", f"/api/applications/{app_id}/transitions")
    assert r.status_code == 403
    first = world.transitions[0]
    r = await _call(
        api, db_engine, lead_b, "POST", f"/api/applications/{app_id}/transition",
        {"transitionId": str(first.id)},
    )
    assert r.status_code == 403
    # The admin reads it, so the same call passes.
    r = await _call(
        api, db_engine, world.principals["admin"], "GET",
        f"/api/applications/{app_id}/transitions",
    )
    assert r.status_code == 200
    assert {t["id"] for t in r.json()} == {
        str(world.transitions[0].id), str(world.transitions[1].id)
    }


async def test_token_without_read_right_is_refused(
    world: _World, api: FastAPI, db_engine: AsyncEngine
) -> None:
    """An agent token with `application.transition` alone gets no task and no transition."""
    token = world.principals["token"]
    assert await _tasks(api, db_engine, token) == set()
    for key in ("draft_a", "draft_b", "own"):
        app_id = world.apps[key]
        r = await _call(
            api, db_engine, token, "GET", f"/api/applications/{app_id}/transitions"
        )
        assert r.status_code == 403, key
        r = await _call(
            api, db_engine, token, "POST", f"/api/applications/{app_id}/transition",
            {"transitionId": str(world.transitions[0].id)},
        )
        assert r.status_code == 403, key


async def test_applicant_route_refuses_a_non_creator(
    world: _World, api: FastAPI, db_engine: AsyncEngine
) -> None:
    """Only the applicant and the creator fire an applicant transition."""
    applicant_t = world.transitions[2]
    app_id = world.apps["own"]
    url = f"/api/applications/{app_id}/applicant-transition"
    body = {"transitionId": str(applicant_t.id)}
    admin = world.principals["admin"]
    assert (await _call(api, db_engine, admin, "POST", url, body)).status_code == 403
    # The list route admits the same callers, so it offers nothing to the admin.
    assert (await _call(api, db_engine, admin, "GET", f"{url}s")).status_code == 403
    owner = world.principals["owner"]
    r = await _call(api, db_engine, owner, "GET", f"{url}s")
    assert r.status_code == 200
    assert [t["id"] for t in r.json()] == [str(applicant_t.id)]
    assert (await _call(api, db_engine, owner, "POST", url, body)).status_code == 200
