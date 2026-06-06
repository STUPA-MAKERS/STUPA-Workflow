"""Integration (echte Postgres, testcontainers): Voting-Service (T-15).

Beweist gegen ein echtes Schema (data-model §5.3, flows §4):
``UNIQUE(vote,voter)`` (Doppelstimme → 409), ``allowChange`` (Update bis Schluss),
Geheim-Pfad (``voted_marker`` + ``secret_ballot`` ohne Identität), Prozent-Quorum aus
dem Eligible-Snapshot und ``close`` → ``result`` → ``flow.fire(result_branch)``."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.models import FlowVersion, State, Transition
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
    """Typ + Form + Flow (voting→approved/rejected/review per voteResult) + Antrag in voting."""
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
        ),
    )

    flow = FlowVersion(
        application_type_id=app_type.id, version=1, active=True, editor_layout={}
    )
    session.add(flow)
    await session.flush()
    states = {
        "voting": State(flow_version_id=flow.id, key="voting", label_i18n={},
                        category="running", edit_allowed=False, is_initial=True),
        "approved": State(flow_version_id=flow.id, key="approved", label_i18n={},
                          category="closed", edit_allowed=False),
        "rejected": State(flow_version_id=flow.id, key="rejected", label_i18n={},
                          category="closed", edit_allowed=False),
        "review": State(flow_version_id=flow.id, key="review", label_i18n={},
                        category="open", edit_allowed=True),
    }
    session.add_all(list(states.values()))
    await session.flush()
    session.add_all([
        Transition(flow_version_id=flow.id, from_state_id=states["voting"].id,
                   to_state_id=states["approved"].id, label_i18n={},
                   guard={"voteResult": "passed"}, actions=[], order=0),
        Transition(flow_version_id=flow.id, from_state_id=states["voting"].id,
                   to_state_id=states["rejected"].id, label_i18n={},
                   guard={"voteResult": "rejected"}, actions=[], order=1),
        Transition(flow_version_id=flow.id, from_state_id=states["voting"].id,
                   to_state_id=states["review"].id, label_i18n={},
                   guard={"voteResult": "tie"}, actions=[], order=2),
    ])
    app_type.active_flow_version_id = flow.id
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


async def _make_vote(session: AsyncSession, app: Application, **cfg: object) -> Vote:
    vote = Vote(application_id=app.id, eligible_group="grp", config=_config(**cfg),
                status="draft")
    session.add(vote)
    await session.commit()
    return vote


def _voter(sub: str) -> Principal:
    return Principal(sub=sub, permissions={"vote.cast"}, groups={"grp"})


# --------------------------------------------------------------------------- #
# UNIQUE(vote,voter) — Doppelstimme → 409 (allowChange aus)
# --------------------------------------------------------------------------- #
async def test_double_vote_conflict_409(session: AsyncSession) -> None:
    app, _ = await _seed(session)
    vote = await _make_vote(session, app, allowChange=False)
    svc = VotingService(session)
    await svc.open(vote.id, now=NOW)

    assert (await svc.cast(vote.id, _voter("v1"), "yes", now=NOW)).status == "cast"
    with pytest.raises(ConflictError):
        await svc.cast(vote.id, _voter("v1"), "no", now=NOW)
    # genau eine Stimme persistiert.
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
    assert rows == ["no"]  # eine Zeile, aktualisiert


async def test_not_in_group_forbidden(session: AsyncSession) -> None:
    app, _ = await _seed(session)
    vote = await _make_vote(session, app)
    svc = VotingService(session)
    await svc.open(vote.id, now=NOW)
    outsider = Principal(sub="x", permissions={"vote.cast"}, groups={"other"})
    with pytest.raises(ForbiddenError):
        await svc.cast(vote.id, outsider, "yes", now=NOW)


# --------------------------------------------------------------------------- #
# Geheim-Pfad: keine choice↔voter-Verknüpfung
# --------------------------------------------------------------------------- #
async def test_secret_vote_unlinks_choice_from_voter(session: AsyncSession) -> None:
    app, _ = await _seed(session)
    vote = await _make_vote(session, app, secret=True)
    svc = VotingService(session)
    await svc.open(vote.id, now=NOW)

    await svc.cast(vote.id, _voter("v1"), "yes", now=NOW)
    await svc.cast(vote.id, _voter("v2"), "no", now=NOW)
    # Doppelstimme auch geheim → 409.
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
    assert sorted(markers) == ["v1", "v2"]      # wer abgestimmt hat
    assert sorted(secrets) == ["no", "yes"]      # was gewählt wurde (ohne Identität)
    assert ballots == 0                          # keine identifizierende Stimme


# --------------------------------------------------------------------------- #
# Prozent-Quorum aus Eligible-Snapshot
# --------------------------------------------------------------------------- #
async def test_open_snapshots_eligible_from_oidc_groups(session: AsyncSession) -> None:
    app, _ = await _seed(session)
    for i in range(4):
        session.add(PrincipalRow(sub=f"m{i}-{uuid.uuid4()}", oidc_groups=["grp"]))
    session.add(PrincipalRow(sub=f"out-{uuid.uuid4()}", oidc_groups=["other"]))
    await session.commit()

    vote = await _make_vote(session, app, quorum={"type": "percent", "value": 50})
    svc = VotingService(session)
    out = await svc.open(vote.id, now=NOW)
    assert out.tally.eligible == 4  # nur grp-Mitglieder


# --------------------------------------------------------------------------- #
# close → result → flow.fire(result_branch)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("choices", "tie_break", "result", "target"),
    [
        (["yes", "yes", "no"], "rejected", "passed", "approved"),
        (["no", "no", "yes"], "rejected", "rejected", "rejected"),
        (["yes", "no"], "tie", "tie", "review"),
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

    # Vote ist geschlossen + Ergebnis persistiert.
    vote_row = await session.get(Vote, vote.id)
    assert vote_row is not None
    await session.refresh(vote_row)
    assert vote_row.status == "closed"
    assert vote_row.result == result


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
