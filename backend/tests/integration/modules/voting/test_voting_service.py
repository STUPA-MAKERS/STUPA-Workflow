"""Integration test for the voting service (T-15).

The test uses a real Postgres from testcontainers and a real schema. It checks
data-model section 5.3 and flows section 4.

`UNIQUE(vote,voter)` turns a double vote into a 409. `allowChange` lets a voter update
the ballot until the vote closes. The secret path writes `voted_marker` and
`secret_ballot` without a link to the identity. The percent quorum comes from the
eligible snapshot. `close` computes the `result` and fires `flow.fire(result_branch)`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import (
    ApplicationType,
    Gremium,
    GremiumMembership,
    GremiumRole,
)
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.flow.service import FlowService
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.modules.voting.models import Ballot, SecretBallot, Vote, VotedMarker
from app.modules.voting.service import VotingService
from app.shared.config_schemas import FormFieldDef, VoteConfig
from app.shared.errors import ConflictError, ForbiddenError

pytestmark = pytest.mark.integration

NOW = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)


class _Recorder:
    def __init__(self) -> None:
        self.actions: list[DispatchedAction] = []

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        self.actions.extend(actions)


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _seed(session: AsyncSession) -> tuple[Application, dict[str, State]]:
    """Create an application type, a form, a flow and an application in `voting`.

    The vote result moves the flow from `voting` to `approved`, `rejected` or `review`.
    """
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id, key=f"t-{uuid.uuid4()}", name_i18n={}, has_budget=False
    )
    session.add(app_type)
    await session.commit()

    forms = FormsService(session)
    await forms.create_form_version(
        app_type.id,
        FormVersionCreate(
            fields=[FormFieldDef(key="title", type="text", label={"de": "Titel"},
                                 required=True)],
            activate=True,
        ), "tester")

    flow = FlowVersion(
        version=1, active=True, editor_layout={}
    )
    session.add(flow)
    await session.flush()
    states = {
        "voting": State(flow_version_id=flow.id, key="voting", label_i18n={},
                        edit_allowed=False, is_initial=True),
        "approved": State(flow_version_id=flow.id, key="approved", label_i18n={},
                          edit_allowed=False),
        "rejected": State(flow_version_id=flow.id, key="rejected", label_i18n={},
                          edit_allowed=False),
        "review": State(flow_version_id=flow.id, key="review", label_i18n={},
                        edit_allowed=True),
    }
    session.add_all(list(states.values()))
    await session.flush()
    # #28: the vote state has two fixed exits, pass and fail. The close fires the branch.
    # A passed vote takes pass to approved. A rejected vote or a tie takes fail to
    # rejected, which is fail-closed.
    session.add_all([
        Transition(flow_version_id=flow.id, from_state_id=states["voting"].id,
                   to_state_id=states["approved"].id, label_i18n={},
                   branch="pass", actions=[], order=0),
        Transition(flow_version_id=flow.id, from_state_id=states["voting"].id,
                   to_state_id=states["rejected"].id, label_i18n={},
                   branch="fail", actions=[], order=1),
    ])
    await session.commit()

    apps = ApplicationsService(session)
    app, _ = await apps.create(
        ApplicationCreate.model_validate(
            {"typeId": str(app_type.id), "data": {"title": "T"},
             "applicantEmail": "a@example.org"}
        )
    )
    app_row = await session.get(Application, app.id)
    assert app_row is not None
    app_row.current_state_id = states["voting"].id
    await session.commit()
    return app_row, states


def _config(**over: object) -> dict:
    base: dict = {"options": ["yes", "no", "abstain"], "majorityRule": "simple"}
    base.update(over)
    return VoteConfig.model_validate(base).model_dump(by_alias=True)


async def _make_vote(
    session: AsyncSession, app: Application, *, eligible_count: int | None = None,
    **cfg: object,
) -> Vote:
    vote = Vote(application_id=app.id, eligible_group="grp", config=_config(**cfg),
                eligible_count=eligible_count, status="draft")
    session.add(vote)
    await session.commit()
    return vote


def _voter(sub: str) -> Principal:
    return Principal(sub=sub, permissions={"vote.cast"}, groups={"grp"})


async def test_double_vote_conflict_409(session: AsyncSession) -> None:
    app, _ = await _seed(session)
    vote = await _make_vote(session, app, allowChange=False)
    svc = VotingService(session)
    await svc.open(vote.id, now=NOW)

    assert (await svc.cast(vote.id, _voter("v1"), "yes", now=NOW)).status == "cast"
    with pytest.raises(ConflictError):
        await svc.cast(vote.id, _voter("v1"), "no", now=NOW)
    count = (await session.execute(
        select(func.count()).select_from(Ballot).where(Ballot.vote_id == vote.id)
    )).scalar_one()
    assert count == 1


async def test_allow_change_updates_ballot(session: AsyncSession) -> None:
    app, _ = await _seed(session)
    vote = await _make_vote(session, app, allowChange=True)
    svc = VotingService(session)
    await svc.open(vote.id, now=NOW)

    await svc.cast(vote.id, _voter("v1"), "yes", now=NOW)
    assert (await svc.cast(vote.id, _voter("v1"), "no", now=NOW)).status == "changed"
    rows = (await session.execute(
        select(Ballot.choice).where(Ballot.vote_id == vote.id)
    )).scalars().all()
    assert rows == ["no"]  # one row, updated in place


async def test_not_in_group_forbidden(session: AsyncSession) -> None:
    app, _ = await _seed(session)
    vote = await _make_vote(session, app)
    svc = VotingService(session)
    await svc.open(vote.id, now=NOW)
    outsider = Principal(sub="x", permissions={"vote.cast"}, groups={"other"})
    with pytest.raises(ForbiddenError):
        await svc.cast(vote.id, outsider, "yes", now=NOW)


async def test_secret_vote_unlinks_choice_from_voter(session: AsyncSession) -> None:
    app, _ = await _seed(session)
    vote = await _make_vote(session, app, secret=True)
    svc = VotingService(session)
    await svc.open(vote.id, now=NOW)

    await svc.cast(vote.id, _voter("v1"), "yes", now=NOW)
    await svc.cast(vote.id, _voter("v2"), "no", now=NOW)
    # The secret path also rejects a double vote with a 409.
    with pytest.raises(ConflictError):
        await svc.cast(vote.id, _voter("v1"), "no", now=NOW)

    markers = (await session.execute(
        select(VotedMarker.voter_sub).where(VotedMarker.vote_id == vote.id)
    )).scalars().all()
    secrets = (await session.execute(
        select(SecretBallot.choice).where(SecretBallot.vote_id == vote.id)
    )).scalars().all()
    ballots = (await session.execute(
        select(func.count()).select_from(Ballot).where(Ballot.vote_id == vote.id)
    )).scalar_one()
    assert sorted(markers) == ["v1", "v2"]      # who voted
    assert sorted(secrets) == ["no", "yes"]      # what the voters chose, no identity
    assert ballots == 0                          # no identifying ballot


def test_secret_ballot_has_no_timestamp_column() -> None:
    """No `at` column on a secret ballot, so no sub-and-time correlation channel."""
    assert "at" not in SecretBallot.__table__.columns
    assert set(SecretBallot.__table__.columns.keys()) == {"id", "vote_id", "choice"}


async def test_percent_quorum_denominator_is_roster_not_voters(
    session: AsyncSession,
) -> None:
    app, _ = await _seed(session)
    # The roster holds 20 eligible voters, for example the size of the Gremium. That
    # number does not depend on who logs in or who votes. No principal row exists for
    # these voters.
    vote = await _make_vote(
        session, app, eligible_count=20, quorum={"type": "percent", "value": 50}
    )
    svc = VotingService(session)
    await svc.open(vote.id, now=NOW)
    # 5 votes give 5/20 = 25%, which is below 50%. The vote misses the quorum, because
    # the denominator is the roster and not the voters. The old fail-open denominator
    # counted the voters alone and gave 5/5 = 100%.
    for i in range(5):
        await svc.cast(vote.id, _voter(f"v{i}"), "yes", now=NOW)

    pre = await svc.get(vote.id)
    assert pre.tally.eligible == 20
    assert pre.tally.quorum_met is False

    # A missed quorum blocks the close (#12). The service raises a 409 instead of a
    # silent rejected. The way out is to collect more votes or to cancel the vote.
    closer = Principal(sub="mgr", permissions={"vote.manage"})
    with pytest.raises(ConflictError):
        await svc.close(vote.id, closer)


@pytest.mark.parametrize(
    ("choices", "tie_break", "result", "target"),
    [
        (["yes", "yes", "no"], "rejected", "passed", "approved"),
        (["no", "no", "yes"], "rejected", "rejected", "rejected"),
        (["yes", "no"], "tie", "tie", "rejected"),  # tie → fail-closed → rejected
    ],
)
async def test_close_branches_to_flow(
    session: AsyncSession, choices: list[str], tie_break: str, result: str, target: str
) -> None:
    app, states = await _seed(session)
    vote = await _make_vote(session, app, tieBreak=tie_break)
    rec = _Recorder()
    svc = VotingService(session, rec)
    await svc.open(vote.id, now=NOW)
    for i, ch in enumerate(choices):
        await svc.cast(vote.id, _voter(f"v{i}"), ch, now=NOW)

    closer = Principal(sub="mgr", permissions={"vote.manage"})
    out = await svc.close(vote.id, closer)
    assert out.result == result
    assert out.new_state_id == states[target].id

    refreshed = await session.get(Application, app.id)
    assert refreshed is not None
    await session.refresh(refreshed)
    assert refreshed.current_state_id == states[target].id

    vote_row = await session.get(Vote, vote.id)
    assert vote_row is not None
    await session.refresh(vote_row)
    assert vote_row.status == "closed"
    assert vote_row.result == result


async def test_close_atomic_rolls_back_on_fire_failure(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the vote open when `fire` fails during the close.

    The session dependency rolls back, so the vote never gets stuck. A stuck vote is
    closed but never fired its branch.
    """
    app, states = await _seed(session)
    vote = await _make_vote(session, app)
    # Hold the ids before the rollback. The rollback expires the ORM objects, so a
    # later attribute access would start synchronous lazy IO.
    app_id, vote_id = app.id, vote.id
    voting_state_id, approved_state_id = states["voting"].id, states["approved"].id
    svc = VotingService(session)
    await svc.open(vote_id, now=NOW)
    await svc.cast(vote_id, _voter("v1"), "yes", now=NOW)

    async def _boom(*_a: object, **_k: object) -> object:
        raise ConflictError("forced", code="guard_failed")

    monkeypatch.setattr(FlowService, "fire", _boom)
    closer = Principal(sub="mgr", permissions={"vote.manage"})
    with pytest.raises(ConflictError):
        await svc.close(vote_id, closer)
    await session.rollback()  # emulates get_session on an exception

    vote_row = await session.get(Vote, vote_id)
    assert vote_row is not None
    await session.refresh(vote_row)
    assert vote_row.status == "open"
    assert vote_row.result is None

    refreshed = await session.get(Application, app_id)
    assert refreshed is not None
    await session.refresh(refreshed)
    assert refreshed.current_state_id == voting_state_id

    # The close is repeatable once `fire` works again.
    monkeypatch.undo()
    out = await svc.close(vote_id, closer)
    assert out.result == "passed"
    assert out.new_state_id == approved_state_id


async def test_concurrent_cast_same_voter_exactly_one_wins(
    migrated: tuple[str, str], session: AsyncSession
) -> None:
    """Let exactly one of two parallel casts by the same voter win.

    The two `cast` calls run over separate sessions. Exactly one ballot persists. The
    other call fails with a 409. The database UNIQUE constraint raises it, not the
    application logic.
    """
    app, _ = await _seed(session)
    vote = await _make_vote(session, app, allowChange=False)
    await VotingService(session).open(vote.id, now=NOW)

    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    try:
        async def _cast(choice: str) -> object:
            async with maker() as s:
                try:
                    return await VotingService(s).cast(
                        vote.id, _voter("v1"), choice, now=NOW
                    )
                except ConflictError as exc:
                    return exc

        first, second = await asyncio.gather(_cast("yes"), _cast("no"))
    finally:
        await eng.dispose()

    conflicts = [r for r in (first, second) if isinstance(r, ConflictError)]
    accepted = [r for r in (first, second) if not isinstance(r, ConflictError)]
    assert len(conflicts) == 1
    assert len(accepted) == 1
    count = (await session.execute(
        select(func.count()).select_from(Ballot).where(Ballot.vote_id == vote.id)
    )).scalar_one()
    assert count == 1


# AUD-027: the lifecycle (create, open, close, cancel) is gremium-scoped, like the
# scoped read. An admin, a global `vote.manage` holder and a per-Gremium `vote.manage`
# holder may act. A cross-tenant call is fail-closed. A per-Gremium holder may not act
# on a vote of another Gremium.
async def _gremium_member_with_vote_manage(
    session: AsyncSession, gremium_id: uuid.UUID
) -> Principal:
    """Build a principal that holds `vote.manage` through a Gremium role, not globally."""
    row = PrincipalRow(sub=f"gm-{uuid.uuid4()}", display_name="GM", email="gm@x.de")
    session.add(row)
    await session.flush()
    role = GremiumRole(
        gremium_id=gremium_id,
        key=f"r-{uuid.uuid4()}",
        name_i18n={"de": "VS"},
        permissions=["vote.manage"],
    )
    session.add(role)
    await session.flush()
    session.add(
        GremiumMembership(
            principal_id=row.id, gremium_id=gremium_id, gremium_role_id=role.id
        )
    )
    await session.commit()
    # No groups and no global permission. The Gremium role alone grants the right.
    return Principal(sub=row.sub, permissions=set())


async def test_assert_can_manage_admin_and_global_pass(session: AsyncSession) -> None:
    app, _ = await _seed(session)
    vote = await _make_vote(session, app)
    svc = VotingService(session)
    vote_row = await session.get(Vote, vote.id)
    assert vote_row is not None
    # An admin and a global `vote.manage` holder pass, independent of the Gremium.
    await svc.assert_can_manage(vote_row, Principal(sub="adm", roles=["admin"]))
    await svc.assert_can_manage(
        vote_row, Principal(sub="g", permissions={"vote.manage"})
    )
    # An identity with `vote.cast` but without manage is fail-closed.
    with pytest.raises(ForbiddenError):
        await svc.assert_can_manage(
            vote_row, Principal(sub="c", permissions={"vote.cast"})
        )


async def test_assert_can_manage_per_gremium_role(session: AsyncSession) -> None:
    """Let a per-Gremium `vote.manage` holder manage a vote of the own Gremium.

    The old router gate accepted a global permission only and locked this holder out.
    The holder still may not manage a vote of another Gremium.
    """
    app, _ = await _seed(session)
    # Bind the vote to the Gremium of the application. The `eligible_group` field holds
    # the Gremium UUID as text.
    type_row = await session.get(ApplicationType, app.type_id)
    assert type_row is not None and type_row.gremium_id is not None
    gremium_id = type_row.gremium_id
    vote = Vote(
        application_id=app.id,
        eligible_group=str(gremium_id),
        config=_config(),
        status="draft",
    )
    session.add(vote)
    await session.commit()

    holder = await _gremium_member_with_vote_manage(session, gremium_id)
    vote_row = await session.get(Vote, vote.id)
    assert vote_row is not None
    await VotingService(session).assert_can_manage(vote_row, holder)

    # The same holder may not manage a vote of another Gremium. Cross-tenant access is
    # fail-closed.
    other = Gremium(name="Other", slug=f"o-{uuid.uuid4()}")
    session.add(other)
    await session.flush()
    foreign_vote = Vote(
        application_id=None,
        eligible_group=str(other.id),
        config=_config(),
        status="draft",
    )
    session.add(foreign_vote)
    await session.commit()
    foreign_row = await session.get(Vote, foreign_vote.id)
    assert foreign_row is not None
    with pytest.raises(ForbiddenError):
        await VotingService(session).assert_can_manage(foreign_row, holder)


async def test_close_then_get_reports_result(session: AsyncSession) -> None:
    app, _ = await _seed(session)
    vote = await _make_vote(session, app)
    svc = VotingService(session)
    await svc.open(vote.id, now=NOW)
    await svc.cast(vote.id, _voter("v1"), "yes", now=NOW)
    await svc.close(vote.id, Principal(sub="mgr", permissions={"vote.manage"}))

    out = await svc.get(vote.id)
    assert out.status == "closed"
    assert out.result == "passed"
    assert out.tally.result == "passed"
    assert out.tally.counts["yes"] == 1
