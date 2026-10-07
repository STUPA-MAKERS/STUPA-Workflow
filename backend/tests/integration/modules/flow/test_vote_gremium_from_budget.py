"""Flow variant B: the vote state takes its Gremium from the cost center (real Postgres).

The flow has the states `review` (initial), `auto` (an entry with an automatic exit),
`gvote` (a vote state with `gremiumSource: "budget"`), `asta` (the escalation), `done`
and `rejected`. The cost center tree is `T > C > L`: `C` names Gremium A as its deciding
Gremium, `L` inherits it, and the sibling `N` has none.

The tests walk the scenario of R10:

1. The application enters `gvote`; the engine stores Gremium A as the snapshot
   `vote_gremium_id`.
2. It is assignable ONLY in a meeting of Gremium A, and `addToNextSession` without a
   `gremiumId` puts it on the next meeting of Gremium A.
3. A member of A reads it and has the task (`isInVoteGremium`). A member of Gremium B
   (with the same global rights) neither reads it nor sees a task.
4. The vote of Gremium A closes, the branch fires, and the snapshot is cleared.

It also checks the fail-closed rule on every path: no cost center, or a cost center
without a deciding Gremium, hides the transition, gives 409 on the manual fire, the
force and the audit revert, and keeps the automatic transition from firing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import (
    ApplicationType,
    Gremium,
    GremiumMembership,
    GremiumRole,
)
from app.modules.applications.access import resolve_app_read
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_models import Budget
from app.modules.budget.tree_schemas import AssignBudgetRequest
from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.extras_dispatcher import FlowExtrasActionDispatcher
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.flow.service import FlowService
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.modules.livevote.agenda_service import AgendaService
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.voting.schemas import VoteCreate
from app.modules.voting.service import VotingService
from app.shared.config_schemas import FormFieldDef, VoteConfig
from app.shared.errors import ConflictError, ForbiddenError, ValidationProblem

pytestmark = pytest.mark.integration

ADMIN = Principal(sub="admin-flow-b", roles=["admin"], permissions={"application.transition"})


class _Recorder:
    def __init__(self) -> None:
        self.actions: list[DispatchedAction] = []

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        self.actions.extend(actions)


@dataclass
class _World:
    g_a: uuid.UUID
    g_b: uuid.UUID
    member_a: Principal
    member_b: Principal
    leaf: uuid.UUID
    no_gremium: uuid.UUID
    decider: uuid.UUID
    states: dict[str, uuid.UUID] = field(default_factory=dict)
    to_vote: uuid.UUID = uuid.UUID(int=0)
    escalate: uuid.UUID = uuid.UUID(int=0)
    app_type: uuid.UUID = uuid.UUID(int=0)


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


async def _member(session: AsyncSession, gremium: Gremium, tag: str) -> Principal:
    """A member of `gremium` with `vote.cast` and the global transition right."""
    row = PrincipalRow(sub=f"m-{gremium.slug}-{tag}", display_name="M", email=f"{tag}@x.de")
    role = GremiumRole(
        gremium_id=gremium.id, key=f"r-{gremium.slug}"[:60], name_i18n={"de": "R"},
        permissions=["vote.cast"],
    )
    session.add_all([row, role])
    await session.flush()
    session.add(
        GremiumMembership(principal_id=row.id, gremium_id=gremium.id, gremium_role_id=role.id)
    )
    return Principal(
        sub=row.sub, permissions={"application.transition"},
        groups={vote_group_key(str(gremium.id))},
    )


async def _seed(maker: async_sessionmaker[AsyncSession]) -> _World:
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        g_a = Gremium(name="AK A", slug=f"a-{tag}")
        g_b = Gremium(name="AK B", slug=f"b-{tag}")
        session.add_all([g_a, g_b])
        await session.flush()
        member_a = await _member(session, g_a, tag)
        member_b = await _member(session, g_b, tag)
        top = Budget(parent_id=None, key=f"T{tag}", path_key=f"T{tag}", name="Top")
        session.add(top)
        await session.flush()
        decider = Budget(
            parent_id=top.id, key="C", path_key=f"T{tag}-C", name="Ressort",
            decision_gremium_id=g_a.id,
        )
        none_node = Budget(parent_id=top.id, key="N", path_key=f"T{tag}-N", name="Ohne")
        session.add_all([decider, none_node])
        await session.flush()
        leaf = Budget(parent_id=decider.id, key="L", path_key=f"T{tag}-C-L", name="Blatt")
        app_type = ApplicationType(gremium_id=None, key=f"t-{tag}", name_i18n={},
                                   has_budget=False)
        session.add_all([leaf, app_type])
        await session.commit()
        await FormsService(session).create_form_version(
            app_type.id,
            FormVersionCreate(
                fields=[FormFieldDef(key="title", type="text", label={"de": "Titel"},
                                     required=True)],
                activate=True,
            ),
            "tester",
        )
        flow = FlowVersion(version=1, active=True, editor_layout={})
        session.add(flow)
        await session.flush()
        states = {
            "review": State(flow_version_id=flow.id, key="review", label_i18n={"de": "P"},
                            is_initial=True),
            "auto": State(flow_version_id=flow.id, key="auto", label_i18n={"de": "Auto"}),
            "gvote": State(flow_version_id=flow.id, key="gvote", label_i18n={"de": "GV"},
                           edit_allowed=False, kind="vote",
                           config={"gremiumSource": "budget"}),
            "asta": State(flow_version_id=flow.id, key="asta", label_i18n={"de": "AStA"}),
            "done": State(flow_version_id=flow.id, key="done", label_i18n={"de": "OK"},
                          is_terminal=True),
            "rejected": State(flow_version_id=flow.id, key="rejected",
                              label_i18n={"de": "Nein"}, is_terminal=True),
        }
        session.add_all(list(states.values()))
        await session.flush()

        def _t(src: str, dst: str, order: int, **kw: object) -> Transition:
            return Transition(
                flow_version_id=flow.id, from_state_id=states[src].id,
                to_state_id=states[dst].id, label_i18n={"de": f"{src}>{dst}"},
                order=order, **kw,
            )

        to_vote = _t("review", "gvote", 0, actions=[{"type": "addToNextSession"}])
        escalate = _t("gvote", "asta", 2, actions=[], guard={"isInVoteGremium": True})
        session.add_all([
            to_vote,
            _t("auto", "gvote", 0, actions=[], automatic=True),
            _t("gvote", "done", 0, actions=[], branch="pass"),
            _t("gvote", "rejected", 1, actions=[], branch="fail"),
            escalate,
            _t("asta", "done", 0, actions=[]),
        ])
        await session.commit()
        return _World(
            g_a=g_a.id, g_b=g_b.id, member_a=member_a, member_b=member_b,
            leaf=leaf.id, no_gremium=none_node.id, decider=decider.id,
            states={k: v.id for k, v in states.items()},
            to_vote=to_vote.id, escalate=escalate.id, app_type=app_type.id,
        )


async def _app(
    session: AsyncSession, world: _World, *, budget: uuid.UUID | None, state: str = "review"
) -> uuid.UUID:
    created, _ = await ApplicationsService(session).create(
        ApplicationCreate.model_validate(
            {"typeId": str(world.app_type), "data": {"title": "Antrag"},
             "applicantEmail": "a@example.org"}
        )
    )
    await session.execute(
        update(Application)
        .where(Application.id == created.id)
        .values(
            budget_id=budget, current_state_id=world.states[state],
            email_confirmed_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return created.id


async def _snapshot(session: AsyncSession, app_id: uuid.UUID) -> uuid.UUID | None:
    return await session.scalar(
        select(Application.vote_gremium_id)
        .where(Application.id == app_id)
        .execution_options(populate_existing=True)
    )


async def _meeting(session: AsyncSession, gremium: uuid.UUID, days: int) -> uuid.UUID:
    meeting = Meeting(gremium_id=gremium, title="Sitzung",
                      date=date.today() + timedelta(days=days), status="planned")
    session.add(meeting)
    await session.commit()
    return meeting.id


async def test_dynamic_vote_state_end_to_end(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    world = await _seed(maker)
    async with maker() as session:
        app_id = await _app(session, world, budget=world.leaf)
        meeting_a = await _meeting(session, world.g_a, 3)
        meeting_b = await _meeting(session, world.g_b, 3)

        listed = {
            t.id: t for t in await FlowService(session).available_transitions(app_id, ADMIN)
        }
        # The agenda Gremium of an action without `gremiumId` is the Gremium of the vote.
        assert listed[world.to_vote].adds_to_agenda is True
        assert listed[world.to_vote].agenda_gremium_id == world.g_a

        rec = _Recorder()
        await FlowService(session, rec).fire(app_id, world.to_vote, ADMIN)
        # 1. The snapshot is the Gremium that the leaf inherits from its parent.
        assert await _snapshot(session, app_id) == world.g_a

        # 2. Assignable only in a meeting of Gremium A.
        agenda = AgendaService(session)
        assert app_id in {a.application_id for a in await agenda.assignable(meeting_a)}
        assert app_id not in {a.application_id for a in await agenda.assignable(meeting_b)}
        # The post-commit action without `gremiumId` picks the next meeting of A.
        to_session = [a for a in rec.actions if a.type == "addToNextSession"]
        assert len(to_session) == 1
        await FlowExtrasActionDispatcher(maker).dispatch(to_session)
        items = (
            await session.scalars(
                select(MeetingAgendaItem.meeting_id).where(
                    MeetingAgendaItem.application_id == app_id
                )
            )
        ).all()
        assert list(items) == [meeting_a]

        # 3. A member of A reads it and has the task; a member of B does neither.
        await resolve_app_read(session, app_id, world.member_a, None)
        with pytest.raises(ForbiddenError):
            await resolve_app_read(session, app_id, world.member_b, None)
        listing = ApplicationsService(session)
        assert app_id in {t.id for t in await listing.list_tasks(world.member_a)}
        assert app_id not in {t.id for t in await listing.list_tasks(world.member_b)}
        # The escalation gate: only a member of the vote Gremium sees it.
        assert world.escalate in {
            t.id for t in await FlowService(session).available_transitions(
                app_id, world.member_a
            )
        }

        # The cost center is locked while the vote runs.
        with pytest.raises(ConflictError) as locked:
            await BudgetTreeService(session).assign_budget(
                app_id, AssignBudgetRequest.model_validate({"budgetId": str(world.leaf)})
            )
        assert locked.value.code == "budget_locked_by_vote"

        # 4. Only Gremium A can run the vote; its close fires the branch and clears the
        # snapshot.
        config = VoteConfig.model_validate(
            {"options": ["yes", "no", "abstain"], "majorityRule": "simple"}
        ).model_dump(by_alias=True)
        voting = VotingService(session)
        with pytest.raises(ValidationProblem) as mismatch:
            await voting.create(
                app_id,
                VoteCreate.model_validate({"config": config, "eligibleGroup": str(world.g_b)}),
                ADMIN,
            )
        assert mismatch.value.code == "eligible_group_mismatch"
        vote = await voting.create(
            app_id,
            VoteCreate.model_validate({"config": config, "eligibleGroup": str(world.g_a)}),
            ADMIN,
        )
        now = datetime.now(UTC)
        await voting.open(vote.id, now=now)
        await voting.cast(vote.id, world.member_a, "yes", now=now)
        closed = await voting.close(vote.id, ADMIN)
        assert closed.branch_fired is True
        state = await session.scalar(
            select(Application.current_state_id)
            .where(Application.id == app_id)
            .execution_options(populate_existing=True)
        )
        assert state == world.states["done"]
        assert await _snapshot(session, app_id) is None
        # Out of the vote: no committee read through the vote any more is needed for
        # the task; the task is gone.
        assert app_id not in {t.id for t in await listing.list_tasks(world.member_a)}


@pytest.mark.parametrize("budget_key", ["none", "no_gremium"])
async def test_fail_closed_without_a_deciding_gremium(
    maker: async_sessionmaker[AsyncSession], budget_key: str
) -> None:
    world = await _seed(maker)
    budget = None if budget_key == "none" else world.no_gremium
    async with maker() as session:
        app_id = await _app(session, world, budget=budget)
        flow = FlowService(session)
        # The list hides the transition.
        assert world.to_vote not in {
            t.id for t in await flow.available_transitions(app_id, ADMIN)
        }
        # The manual fire gives 409 with a clear code and changes nothing.
        with pytest.raises(ConflictError) as fired:
            await flow.fire(app_id, world.to_vote, ADMIN)
        assert fired.value.code == "no_vote_gremium"
        # The force gives 409 too.
        with pytest.raises(ConflictError) as forced:
            await flow.force_status(app_id, world.states["gvote"], ADMIN, note="x")
        assert forced.value.code == "no_vote_gremium"
        state = await session.scalar(
            select(Application.current_state_id)
            .where(Application.id == app_id)
            .execution_options(populate_existing=True)
        )
        assert state == world.states["review"]

        # The automatic transition does not fire.
        auto_id = await _app(session, world, budget=budget, state="auto")
        assert await flow.auto_advance(auto_id, ADMIN) is None
        assert await session.scalar(
            select(Application.current_state_id).where(Application.id == auto_id)
        ) == world.states["auto"]


async def test_automatic_entry_with_a_deciding_gremium(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    world = await _seed(maker)
    async with maker() as session:
        auto_id = await _app(session, world, budget=world.decider, state="auto")
        fired = await FlowService(session).auto_advance(auto_id, ADMIN)
        assert fired is not None
        assert fired.new_state_id == world.states["gvote"]
        assert await _snapshot(session, auto_id) == world.g_a


async def test_force_and_revert_follow_the_snapshot(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    world = await _seed(maker)
    async with maker() as session:
        app_id = await _app(session, world, budget=world.leaf)
        flow = FlowService(session)
        await flow.force_status(app_id, world.states["gvote"], ADMIN, note="x")
        assert await _snapshot(session, app_id) == world.g_a
        await flow.fire(app_id, world.escalate, world.member_a)
        # Leaving the vote state clears the snapshot.
        assert await _snapshot(session, app_id) is None

        # The deciding Gremium goes away. The revert back into the vote state must
        # refuse the application (409) instead of a vote without a Gremium.
        await session.execute(
            update(Budget).where(Budget.id == world.decider).values(decision_gremium_id=None)
        )
        await session.commit()
        with pytest.raises(ConflictError) as reverted:
            await flow.revert_status(
                app_id, from_state_id=world.states["gvote"],
                to_state_id=world.states["asta"], actor="admin", reverted_audit_id=1,
            )
        assert reverted.value.code == "no_vote_gremium"

        # With the Gremium back, the revert restores the snapshot.
        await session.execute(
            update(Budget).where(Budget.id == world.decider).values(
                decision_gremium_id=world.g_b
            )
        )
        await session.commit()
        await flow.revert_status(
            app_id, from_state_id=world.states["gvote"],
            to_state_id=world.states["asta"], actor="admin", reverted_audit_id=1,
        )
        assert await _snapshot(session, app_id) == world.g_b


async def test_fixed_gremium_vote_state_still_works(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Regression: a vote state with a fixed `gremiumId` keeps today's behaviour."""
    world = await _seed(maker)
    async with maker() as session:
        await session.execute(
            update(State)
            .where(State.id == world.states["gvote"])
            .values(config={"gremiumId": str(world.g_b)})
        )
        await session.commit()
        # No cost center at all: the fixed Gremium does not need one.
        app_id = await _app(session, world, budget=None)
        listed = {
            t.id: t for t in await FlowService(session).available_transitions(app_id, ADMIN)
        }
        assert listed[world.to_vote].agenda_gremium_id == world.g_b
        await FlowService(session).fire(app_id, world.to_vote, ADMIN)
        assert await _snapshot(session, app_id) == world.g_b
        await resolve_app_read(session, app_id, world.member_b, None)
        with pytest.raises(ForbiddenError):
            await resolve_app_read(session, app_id, world.member_a, None)
        # A fixed vote state does not lock the cost center.
        out = await BudgetTreeService(session).assign_budget(
            app_id, AssignBudgetRequest.model_validate({"budgetId": None})
        )
        assert out.budget_id is None
