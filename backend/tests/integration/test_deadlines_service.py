"""Integration (echte Postgres, testcontainers): Deadlines/Cron (T-44, flows §9.4).

Beweist gegen ein echtes Schema + den arq-Task ``process_deadlines``:

* **Auto-Übergang / Wiedervorlage** — abgelaufene Frist feuert den referenzierten
  Übergang (Guard ``deadlinePassed``) → Status + ``status_event`` (Historie); danach
  ``action_on_pass=NULL`` → **kein** zweites Feuern (Idempotenz, parallele Worker).
* **Vote-Auto-Close** — offener Vote mit abgelaufenem ``closes_at`` wird ausgezählt
  und feuert den Ergebnis-Branch (``voteResult``).
* **Erinnerung** — Frist im Lead-Fenster sendet genau **eine** ``deadline_approaching``-
  Mail; ein zweiter Lauf bleibt stumm (``reminded_at``).

Die ``SKIP LOCKED``-Selektion + partiellen Indizes liegen real vor (Migration 0014);
``now`` ist zeitzonenbewusst (UTC), Fristen werden relativ zur Echtzeit gesetzt.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application, StatusEvent
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.deadlines.models import Deadline
from app.modules.deadlines.service import DeadlineService
from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.modules.notifications.mail import CapturingMailSender
from app.modules.notifications.models import MailTemplate, NotificationRule
from app.modules.notifications.queue import DirectMailQueue
from app.modules.voting.models import Ballot, Vote
from app.settings import load_settings
from app.shared.config_schemas import FormFieldDef, VoteConfig
from worker.deadlines import process_deadlines

pytestmark = pytest.mark.integration


class _Recorder:
    """Flow-Dispatcher-Fake — vermeidet Redis für cron-gefeuerte Actions."""

    def __init__(self) -> None:
        self.actions: list[DispatchedAction] = []

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        self.actions.extend(actions)


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #
async def _seed_flow(session: AsyncSession) -> tuple[ApplicationType, dict[str, State]]:
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id, key=f"t-{uuid.uuid4()}", name_i18n={}, has_budget=False
    )
    session.add(app_type)
    await session.commit()

    await FormsService(session).create_form_version(
        app_type.id,
        FormVersionCreate(
            fields=[FormFieldDef(key="title", type="text", label={"de": "T"}, required=True)],
            activate=True,
        ),
    )
    flow = FlowVersion(
        application_type_id=app_type.id, version=1, active=True, editor_layout={}
    )
    session.add(flow)
    await session.flush()
    states = {
        "vertagt": State(flow_version_id=flow.id, key="vertagt", label_i18n={},
                         category="open", edit_allowed=False, is_initial=True),
        "active": State(flow_version_id=flow.id, key="active", label_i18n={},
                        category="open", edit_allowed=True),
        "voting": State(flow_version_id=flow.id, key="voting", label_i18n={},
                        category="running", edit_allowed=False),
        "approved": State(flow_version_id=flow.id, key="approved", label_i18n={},
                          category="closed", edit_allowed=False),
        "rejected": State(flow_version_id=flow.id, key="rejected", label_i18n={},
                          category="closed", edit_allowed=False),
    }
    session.add_all(list(states.values()))
    await session.flush()
    session.add_all([
        # Wiedervorlage/Requeue: vertagt → active bei abgelaufener Frist.
        Transition(flow_version_id=flow.id, from_state_id=states["vertagt"].id,
                   to_state_id=states["active"].id, label_i18n={},
                   guard={"deadlinePassed": True}, actions=[], order=0),
        Transition(flow_version_id=flow.id, from_state_id=states["voting"].id,
                   to_state_id=states["approved"].id, label_i18n={},
                   branch="pass", actions=[], order=0),
        Transition(flow_version_id=flow.id, from_state_id=states["voting"].id,
                   to_state_id=states["rejected"].id, label_i18n={},
                   branch="fail", actions=[], order=1),
    ])
    app_type.active_flow_version_id = flow.id
    await session.commit()
    return app_type, states


async def _make_app(session: AsyncSession, app_type: ApplicationType, state: State) -> Application:
    app, _ = await ApplicationsService(session).create(
        ApplicationCreate.model_validate(
            {"typeId": str(app_type.id), "data": {"title": "T"},
             "applicantEmail": "a@example.org"}
        )
    )
    row = await session.get(Application, app.id)
    assert row is not None
    row.current_state_id = state.id
    await session.commit()
    return row


def _ctx(maker: async_sessionmaker[AsyncSession], queue: object | None = None) -> dict[str, object]:
    ctx: dict[str, object] = {
        "settings": load_settings(),
        "deadlines_sessionmaker": maker,
        "flow_dispatcher": _Recorder(),
    }
    if queue is not None:
        ctx["mail_queue"] = queue
    return ctx


# --------------------------------------------------------------------------- #
# Auto-transition / requeue + idempotency
# --------------------------------------------------------------------------- #
async def test_requeue_auto_transition_sets_status_and_history(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as s:
        app_type, states = await _seed_flow(s)
        app = await _make_app(s, app_type, states["vertagt"])
        transitions = (await s.execute(
            select(Transition).where(Transition.from_state_id == states["vertagt"].id)
        )).scalars().all()
        tid = transitions[0].id
        await DeadlineService(s).create(
            kind="requeue", due_at=datetime.now(UTC) - timedelta(minutes=1),
            application_id=app.id, action_on_pass={"transitionId": str(tid)},
        )

    out = await process_deadlines(_ctx(maker))
    assert "actions=1" in out

    async with maker() as s:
        moved = await s.get(Application, app.id)
        assert moved is not None
        assert moved.current_state_id == states["active"].id  # Status gesetzt
        # Genau ein Requeue-Übergang in der Historie (neben dem Anlege-Event).
        requeue_events = (await s.execute(
            select(StatusEvent).where(
                StatusEvent.application_id == app.id,
                StatusEvent.to_state_id == states["active"].id,
            )
        )).scalars().all()
        assert len(requeue_events) == 1  # Historie geschrieben
        total_first = (await s.execute(
            select(func.count()).select_from(StatusEvent)
            .where(StatusEvent.application_id == app.id)
        )).scalar_one()
        deadline = (await s.execute(select(Deadline))).scalars().one()
        assert deadline.action_on_pass is None  # konsumiert

    # Zweiter Lauf (paralleler/erneuter Worker): kein zweites Feuern.
    out2 = await process_deadlines(_ctx(maker))
    assert "actions=0" in out2
    async with maker() as s:
        total_second = (await s.execute(
            select(func.count()).select_from(StatusEvent)
            .where(StatusEvent.application_id == app.id)
        )).scalar_one()
        assert total_second == total_first  # idempotent — keine Doppelausführung


# --------------------------------------------------------------------------- #
# Vote auto-close
# --------------------------------------------------------------------------- #
async def test_vote_auto_close_fires_branch(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as s:
        app_type, states = await _seed_flow(s)
        app = await _make_app(s, app_type, states["voting"])
        config = VoteConfig.model_validate(
            {"options": ["yes", "no"], "majorityRule": "simple"}
        ).model_dump(by_alias=True)
        vote = Vote(
            application_id=app.id, eligible_group="grp", config=config,
            eligible_count=1, status="open", opens_at=datetime.now(UTC),
            closes_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        s.add(vote)
        await s.flush()
        s.add(Ballot(vote_id=vote.id, voter_sub="v1", choice="yes"))
        await s.commit()
        vote_id = vote.id

    out = await process_deadlines(_ctx(maker))
    assert "votes=1" in out

    async with maker() as s:
        closed = await s.get(Vote, vote_id)
        assert closed is not None
        assert closed.status == "closed"
        assert closed.result == "passed"
        moved = await s.get(Application, app.id)
        assert moved is not None
        assert moved.current_state_id == states["approved"].id  # Ergebnis-Branch gefeuert


# --------------------------------------------------------------------------- #
# Reminder — exactly once
# --------------------------------------------------------------------------- #
async def test_reminder_sent_exactly_once(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as s:
        app_type, states = await _seed_flow(s)
        app = await _make_app(s, app_type, states["active"])
        s.add(MailTemplate(
            key="deadline_soon",
            subject_i18n={"de": "Frist bald"},
            body_i18n={"de": "Frist {{ deadlineId }} läuft ab."},
        ))
        s.add(NotificationRule(
            event="deadline_approaching",
            recipients=[{"kind": "applicant"}],
            template_key="deadline_soon",
            enabled=True,
        ))
        await s.commit()
        await DeadlineService(s).create(
            kind="vote", due_at=datetime.now(UTC) + timedelta(minutes=30),
            application_id=app.id,
        )

    sender = CapturingMailSender()
    queue = DirectMailQueue(sender)
    out = await process_deadlines(_ctx(maker, queue))
    assert "reminders=1" in out
    assert len(sender.sent) == 1
    assert "a@example.org" in sender.sent[0].to

    async with maker() as s:
        deadline = (await s.execute(select(Deadline))).scalars().one()
        assert deadline.reminded_at is not None

    # Zweiter Lauf: keine zweite Mail (reminded_at gesetzt).
    out2 = await process_deadlines(_ctx(maker, queue))
    assert "reminders=0" in out2
    assert len(sender.sent) == 1
