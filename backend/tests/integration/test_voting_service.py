"""Integration (echte Postgres, testcontainers): Voting-Service (T-15).

Beweist gegen ein echtes Schema (data-model §5.3, flows §4):
``UNIQUE(vote,voter)`` (Doppelstimme → 409), ``allowChange`` (Update bis Schluss),
Geheim-Pfad (``voted_marker`` + ``secret_ballot`` ohne Identität), Prozent-Quorum aus
dem Eligible-Snapshot und ``close`` → ``result`` → ``flow.fire(result_branch)``."""

from __future__ import annotations

import asyncio
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
    # #28: vote-State hat zwei feste Ausgänge (pass/fail); close() feuert den Branch.
    # passed → pass → approved; rejected/tie → fail → rejected (fail-closed).
    session.add_all([
        Transition(flow_version_id=flow.id, from_state_id=states["voting"].id,
                   to_state_id=states["approved"].id, label_i18n={},
                   branch="pass", actions=[], order=0),
        Transition(flow_version_id=flow.id, from_state_id=states["voting"].id,
                   to_state_id=states["rejected"].id, label_i18n={},
                   branch="fail", actions=[], order=1),
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


def test_secret_ballot_has_no_timestamp_column() -> None:
    """Kein ``at`` an der Geheim-Stimme → kein sub+Zeit-Korrelationskanal."""
    assert "at" not in SecretBallot.__table__.columns
    assert set(SecretBallot.__table__.columns.keys()) == {"id", "vote_id", "choice"}


# --------------------------------------------------------------------------- #
# Prozent-Quorum: Nenner = maßgeblicher Roster, NICHT eingeloggte/abstimmende User
# --------------------------------------------------------------------------- #
async def test_percent_quorum_denominator_is_roster_not_voters(
    session: AsyncSession,
) -> None:
    app, _ = await _seed(session)
    # Roster: 20 Stimmberechtigte (z.B. Gremiumsgröße) — unabhängig davon, wer
    # eingeloggt ist oder abstimmt. Es existiert KEINE entsprechende principal-Zeile.
    vote = await _make_vote(
        session, app, eligible_count=20, quorum={"type": "percent", "value": 50}
    )
    svc = VotingService(session)
    await svc.open(vote.id, now=NOW)
    # 5 Stimmen → 5/20 = 25% < 50%: Quorum verfehlt (fail-closed). Mit dem alten
    # Fail-open-Nenner (nur Abstimmende) wären es 5/5 = 100% gewesen.
    for i in range(5):
        await svc.cast(vote.id, _voter(f"v{i}"), "yes", now=NOW)
    closer = Principal(sub="mgr", permissions={"vote.manage"})
    out = await svc.close(vote.id, closer)
    assert out.tally.eligible == 20
    assert out.tally.quorum_met is False
    assert out.result == "rejected"


# --------------------------------------------------------------------------- #
# close → result → flow.fire(result_branch)
# --------------------------------------------------------------------------- #
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

    # Vote ist geschlossen + Ergebnis persistiert.
    vote_row = await session.get(Vote, vote.id)
    assert vote_row is not None
    await session.refresh(vote_row)
    assert vote_row.status == "closed"
    assert vote_row.result == result


async def test_close_atomic_rolls_back_on_fire_failure(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Schlägt ``fire`` beim Schließen fehl, bleibt der Vote (nach Rollback der
    Session-Dependency) **offen** — kein »zu, aber Branch nie gefeuert« (stuck)."""
    app, states = await _seed(session)
    vote = await _make_vote(session, app)
    # IDs vor dem Rollback festhalten (Rollback expired die ORM-Objekte → späterer
    # Attribut-Zugriff würde sonst synchrones Lazy-IO auslösen).
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
    await session.rollback()  # emuliert get_session bei einer Exception

    vote_row = await session.get(Vote, vote_id)
    assert vote_row is not None
    await session.refresh(vote_row)
    assert vote_row.status == "open"   # nicht geschlossen
    assert vote_row.result is None

    refreshed = await session.get(Application, app_id)
    assert refreshed is not None
    await session.refresh(refreshed)
    assert refreshed.current_state_id == voting_state_id  # State unverändert

    # Re-Close funktioniert (fire nicht mehr gepatcht) → wiederholbar.
    monkeypatch.undo()
    out = await svc.close(vote_id, closer)
    assert out.result == "passed"
    assert out.new_state_id == approved_state_id


# --------------------------------------------------------------------------- #
# Echter nebenläufiger Cast — genau eine Stimme gewinnt (UNIQUE-Race)
# --------------------------------------------------------------------------- #
async def test_concurrent_cast_same_voter_exactly_one_wins(
    migrated: tuple[str, str], session: AsyncSession
) -> None:
    """Zwei parallele ``cast`` desselben Wählers über **separate** Sessions →
    genau eine Stimme persistiert, die andere 409 (DB-UNIQUE, nicht App-Logik)."""
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
