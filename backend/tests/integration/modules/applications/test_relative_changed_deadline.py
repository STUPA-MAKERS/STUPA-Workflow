"""F7 and F12: an edit moves a `relative_changed` deadline and writes an audit entry.

A `relative_changed` policy counts from `updated_at`. Before the fix a later edit kept
the old due time. Now the edit re-creates the deadline from the new `updated_at`. A
`relative_submitted` deadline stays where it is. Every edit writes an
`application_update` audit entry with the version number and the changed field keys,
never the values.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry
from app.modules.deadlines.models import Deadline, DeadlinePolicy
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.shared.config_schemas import FormFieldDef

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _seed(session: AsyncSession, kind: str) -> uuid.UUID:
    """Create a type, a form, a policy and a flow whose initial state uses the policy."""
    tag = uuid.uuid4().hex[:8]
    gremium = Gremium(name="G", slug=f"g-{tag}")
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id, key=f"t-{tag}", name_i18n={}, has_budget=False
    )
    policy = DeadlinePolicy(
        key=f"frist-{tag}", label={"de": "Frist"}, kind=kind, offset_days=3
    )
    session.add_all([app_type, policy])
    await session.commit()
    await FormsService(session).create_form_version(
        app_type.id,
        FormVersionCreate(
            fields=[
                FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
                FormFieldDef(key="note", type="text", label={"de": "Notiz"}),
            ],
            activate=True,
        ),
        "tester",
    )
    flow = FlowVersion(version=1, active=True, editor_layout={})
    session.add(flow)
    await session.flush()
    session.add(
        State(flow_version_id=flow.id, key="open", label_i18n={"de": "Offen"},
              edit_allowed=True, is_initial=True,
              config={"deadlinePolicyKey": policy.key})
    )
    await session.commit()
    return app_type.id


async def _create(session: AsyncSession, type_id: uuid.UUID) -> Application:
    out, _ = await ApplicationsService(session).create(
        ApplicationCreate.model_validate(
            {"typeId": str(type_id), "data": {"title": "Alt", "note": "geheim"},
             "applicantEmail": "a@example.org"}
        )
    )
    app = await session.get(Application, out.id)
    assert app is not None
    return app


async def _due(session: AsyncSession, app_id: uuid.UUID) -> Deadline:
    return (
        await session.scalars(
            select(Deadline)
            .where(Deadline.application_id == app_id, Deadline.kind == "flow_deadline")
            .execution_options(populate_existing=True)
        )
    ).one()


async def test_edit_moves_a_relative_changed_deadline(session: AsyncSession) -> None:
    type_id = await _seed(session, "relative_changed")
    app = await _create(session, type_id)
    before = await _due(session, app.id)
    before.reminded_at = datetime.now(UTC)
    # Move the anchor back, so the edit gives a visibly later due time.
    app.updated_at = datetime.now(UTC) - timedelta(days=2)
    before.due_at = app.updated_at + timedelta(days=3)
    old_due = before.due_at
    await session.commit()

    await ApplicationsService(session).patch(
        app.id, {"title": "Neu", "note": "geheim"}, changed_by="tester"
    )

    await session.refresh(app)
    after = await _due(session, app.id)
    assert after.due_at == app.updated_at + timedelta(days=3)
    assert after.due_at > old_due
    # The new due time needs a new reminder.
    assert after.reminded_at is None


async def test_edit_keeps_a_relative_submitted_deadline(session: AsyncSession) -> None:
    type_id = await _seed(session, "relative_submitted")
    app = await _create(session, type_id)
    before = await _due(session, app.id)
    deadline_id, due = before.id, before.due_at

    await ApplicationsService(session).patch(
        app.id, {"title": "Neu", "note": "geheim"}, changed_by="tester"
    )

    after = await _due(session, app.id)
    assert (after.id, after.due_at) == (deadline_id, due)


async def test_edit_writes_an_audit_entry_without_values(session: AsyncSession) -> None:
    type_id = await _seed(session, "relative_submitted")
    app = await _create(session, type_id)

    await ApplicationsService(session).patch(
        app.id, {"title": "Neuer Titel"}, changed_by="tester"
    )

    entries = (
        await session.scalars(
            select(AuditEntry).where(
                AuditEntry.action == "application_update",
                AuditEntry.target_id == str(app.id),
            )
        )
    ).all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actor == "tester"
    assert entry.target_type == "application"
    assert entry.data == {"version": 2, "changedFields": ["note", "title"]}
    dumped = json.dumps(entry.data)
    assert "Neuer Titel" not in dumped
    assert "geheim" not in dumped
