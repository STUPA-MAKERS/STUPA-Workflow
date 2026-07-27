"""Integration (real Postgres, testcontainers): deadlines and cron (T-44, flows §9.4).

These tests run against a real schema and the arq task `process_deadlines`. They prove:

* **Auto transition / requeue** — an expired deadline fires the referenced transition.
  The guard is `deadlinePassed`. The task writes the status and a `status_event` history
  row. `action_on_pass` then becomes NULL, so a second run does **not** fire again.
  Parallel workers stay idempotent.
* **Vote auto-close** — the task counts an open vote with an expired `closes_at`. It
  then fires the result branch (`voteResult`).
* **Reminder** — a deadline inside the lead window sends exactly **one**
  `deadline_approaching` mail. A second run stays silent because `reminded_at` is set.

The `SKIP LOCKED` selection and the partial indexes exist for real (migration 0014).
`now` is time-zone aware (UTC). The tests set the deadlines relative to real time.
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
from app.modules.notifications.queue import DirectMailQueue
from app.modules.voting.models import Ballot, Vote
from app.settings import load_settings
from app.shared.config_schemas import FormFieldDef, VoteConfig
from worker.deadlines import process_deadlines

pytestmark = pytest.mark.integration


class _Recorder:
    """Fake flow dispatcher that keeps Redis out of the cron-fired actions."""

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
        ), "tester")
    flow = FlowVersion(
        version=1, active=True, editor_layout={}
    )
    session.add(flow)
    await session.flush()
    states = {
        "vertagt": State(flow_version_id=flow.id, key="vertagt", label_i18n={},
                         edit_allowed=False, is_initial=True),
        "active": State(flow_version_id=flow.id, key="active", label_i18n={},
                        edit_allowed=True),
        "voting": State(flow_version_id=flow.id, key="voting", label_i18n={},
                        edit_allowed=False),
        "approved": State(flow_version_id=flow.id, key="approved", label_i18n={},
                          edit_allowed=False),
        "rejected": State(flow_version_id=flow.id, key="rejected", label_i18n={},
                          edit_allowed=False),
    }
    session.add_all(list(states.values()))
    await session.flush()
    session.add_all([
        # Requeue: vertagt moves to active when the deadline expires.
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
        assert moved.current_state_id == states["active"].id
        # Exactly one requeue transition in the history, next to the creation event.
        requeue_events = (await s.execute(
            select(StatusEvent).where(
                StatusEvent.application_id == app.id,
                StatusEvent.to_state_id == states["active"].id,
            )
        )).scalars().all()
        assert len(requeue_events) == 1
        total_first = (await s.execute(
            select(func.count()).select_from(StatusEvent)
            .where(StatusEvent.application_id == app.id)
        )).scalar_one()
        deadline = (await s.execute(select(Deadline))).scalars().one()
        assert deadline.action_on_pass is None  # consumed

    # A second run, from a parallel or a repeated worker, does not fire again.
    out2 = await process_deadlines(_ctx(maker))
    assert "actions=0" in out2
    async with maker() as s:
        total_second = (await s.execute(
            select(func.count()).select_from(StatusEvent)
            .where(StatusEvent.application_id == app.id)
        )).scalar_one()
        assert total_second == total_first  # idempotent, no double run


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
        assert moved.current_state_id == states["approved"].id  # the result branch fired


async def test_due_scans_are_bounded_oldest_first(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Every scan returns at most `limit` ids, oldest `due_at` first.

    With a backlog above `limit` a single tick would otherwise pull the whole cohort
    sequentially over the one-minute cadence (AUD-046). The remaining rows stay due, so
    nothing is lost.
    """
    base = datetime.now(UTC) - timedelta(hours=10)
    async with maker() as s:
        app_type, states = await _seed_flow(s)
        app = await _make_app(s, app_type, states["active"])
        svc = DeadlineService(s)
        # Five due auto deadlines and five due reminder deadlines, oldest first.
        for i in range(5):
            await svc.create(
                kind="requeue", due_at=base + timedelta(minutes=i),
                application_id=app.id, action_on_pass={"transitionId": str(uuid.uuid4())},
            )
        for i in range(5):
            await svc.create(
                kind="vote", due_at=base + timedelta(minutes=i), application_id=app.id,
            )

    async with maker() as s:
        svc = DeadlineService(s)
        now = datetime.now(UTC)
        # The action scan is capped at 3 and returns the three oldest action_on_pass rows.
        action_ids = await svc.due_action_deadline_ids(now, limit=3)
        assert len(action_ids) == 3
        rows = (await s.execute(
            select(Deadline).where(Deadline.id.in_(action_ids))
        )).scalars().all()
        due = sorted(r.due_at for r in rows)
        assert due == [base + timedelta(minutes=i) for i in range(3)]  # oldest first

        # The reminder scan is capped at 4. All ten deadlines have reminded_at IS NULL.
        reminder_ids = await svc.due_reminder_ids(now, timedelta(hours=24), limit=4)
        assert len(reminder_ids) == 4

        # Without a limit argument the default cap applies. It lies far above this
        # backlog, so all ten rows come back.
        assert len(await svc.due_reminder_ids(now, timedelta(hours=24))) == 10


async def test_reminder_sent_exactly_once(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as s:
        app_type, states = await _seed_flow(s)
        app = await _make_app(s, app_type, states["active"])
        # The seed of migration 0002 creates the `deadline_approaching` mail template.
        # Do not insert it here again. A second insert breaks the UNIQUE constraint on
        # `mail_template.key`.
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

    # A second run sends no second mail because reminded_at is set.
    out2 = await process_deadlines(_ctx(maker, queue))
    assert "reminders=0" in out2
    assert len(sender.sent) == 1


async def test_reminder_sent_late_for_already_passed_deadline(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """An expired deadline without a reminder still gets exactly one late reminder.

    The cron can stay down longer than the lead window. The task then sends the reminder
    late and sets `reminded_at`. The row leaves the scan index instead of leaking there
    forever (AUD-037).
    """
    async with maker() as s:
        app_type, states = await _seed_flow(s)
        app = await _make_app(s, app_type, states["active"])
        # due_at lies in the past, so the deadline already expired. The old two-sided
        # condition of due_at > now would never catch such a row again.
        await DeadlineService(s).create(
            kind="vote", due_at=datetime.now(UTC) - timedelta(hours=48),
            application_id=app.id,
        )

    sender = CapturingMailSender()
    queue = DirectMailQueue(sender)
    out = await process_deadlines(_ctx(maker, queue))
    assert "reminders=1" in out  # late, but sent
    assert len(sender.sent) == 1
    assert "a@example.org" in sender.sent[0].to

    async with maker() as s:
        deadline = (await s.execute(select(Deadline))).scalars().one()
        assert deadline.reminded_at is not None  # the row leaves the scan index

    # A second run sends no second late mail. The exactly-once rule holds.
    out2 = await process_deadlines(_ctx(maker, queue))
    assert "reminders=0" in out2
    assert len(sender.sent) == 1
