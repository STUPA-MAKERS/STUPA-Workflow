"""Integration (real Postgres, testcontainers): the ApplicationsService life cycle.

The tests prove against a real schema. Create splits off
the PII and writes v1 plus the initial state. PATCH writes a new version with a diff and
syncs the amount. An edit lock gives 409. The timeline, the version history, the list
filters and the comment visibility work. Anonymization empties the PII and keeps the
application.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Applicant, SubmissionVersion
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


def _fields() -> list[FormFieldDef]:
    return [
        FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
        FormFieldDef.model_validate(
            {
                "key": "cost",
                "type": "currency",
                "label": {"de": "Kosten"},
                "isPromoted": True,
                "promoteTarget": "amount",
            }
        ),
        FormFieldDef.model_validate(
            {"key": "note", "type": "text", "label": {"de": "Notiz"}, "isPII": True}
        ),
    ]


async def _seed_type(
    session: AsyncSession,
    *,
    has_budget: bool = False,
    fields: list[FormFieldDef] | None = None,
) -> tuple[ApplicationType, State, State]:
    """Create a type with an active form version and a flow.

    The flow holds an initial state and a locked state.
    """
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id,
        key=f"t-{uuid.uuid4()}",
        name_i18n={},
        has_budget=has_budget,
    )
    session.add(app_type)
    await session.commit()

    forms = FormsService(session)
    await forms.create_form_version(
        app_type.id, FormVersionCreate(fields=fields or _fields(), activate=True), "tester")

    flow = FlowVersion(version=1, active=True, editor_layout={})
    session.add(flow)
    await session.flush()
    draft = State(
        flow_version_id=flow.id,
        key="draft",
        label_i18n={"de": "Entwurf"},
        edit_allowed=True,
        is_initial=True,
    )
    locked = State(
        flow_version_id=flow.id,
        key="voting",
        label_i18n={"de": "Abstimmung"},
        edit_allowed=False,
    )
    session.add_all([draft, locked])
    await session.commit()
    return app_type, draft, locked


def _create_payload(app_type_id: uuid.UUID) -> ApplicationCreate:
    return ApplicationCreate.model_validate(
        {
            "typeId": str(app_type_id),
            "data": {"title": "Mein Antrag", "cost": "100.00", "note": "geheim"},
            "applicantEmail": "Antrag@Example.ORG",
            "applicantName": "Erika",
            "lang": "de",
        }
    )


async def test_create_separates_pii_and_writes_v1(session: AsyncSession) -> None:
    """Split off the PII and write v1.

    EmailStr lowercases the domain, and the citext match ignores case.
    """
    app_type, draft, _ = await _seed_type(session)
    svc = ApplicationsService(session)

    app, email = await svc.create(_create_payload(app_type.id))
    assert email == "Antrag@example.org"
    assert app.current_state_id == draft.id
    assert app.amount == Decimal("100.00")
    assert app.currency == "EUR"
    assert app.gremium_id == app_type.gremium_id

    applicant = (
        await session.execute(select(Applicant).where(Applicant.application_id == app.id))
    ).scalar_one()
    assert applicant.email == "Antrag@example.org"
    assert applicant.name == "Erika"
    hit = await session.scalar(select(Applicant).where(Applicant.email == "antrag@EXAMPLE.org"))
    assert hit is not None and hit.id == applicant.id

    versions = (
        await session.scalars(
            select(SubmissionVersion).where(SubmissionVersion.application_id == app.id)
        )
    ).all()
    assert [v.version for v in versions] == [1]
    assert versions[0].changed_by == "applicant"

    timeline = await svc.timeline(app.id)
    assert [e.to_state_id for e in timeline] == [draft.id]
    assert timeline[0].actor == "applicant"


async def test_create_invalid_data_422_before_db(session: AsyncSession) -> None:
    """Answer 422 for a missing title before any DB write."""
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(app_type.id),
            "data": {"cost": "5.00"},
            "applicantEmail": "x@example.org",
        }
    )
    with pytest.raises(ValidationProblem) as ei:
        await svc.create(payload)
    assert ei.value.status == 422
    assert ei.value.errors is not None
    assert any(e.field == "title" for e in ei.value.errors)


async def test_patch_creates_version_and_diff(session: AsyncSession) -> None:
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))

    out = await svc.patch(
        app.id,
        {"title": "Geändert", "cost": "150.00", "note": "geheim"},
        changed_by="applicant",
    )
    assert out.version == 2
    assert out.amount == Decimal("150.00")

    versions = await svc.versions(app.id)
    assert [v.version for v in versions] == [1, 2]
    v2 = versions[1]
    assert v2.diff is not None
    assert v2.diff["changed"]["title"] == {"old": "Mein Antrag", "new": "Geändert"}
    assert "cost" in v2.diff["changed"]


async def test_patch_preserves_system_title_field(session: AsyncSession) -> None:
    """A type without an own `title` field uses the system title field.

    The runtime puts that system title field in front of the form. `patch()` whitelists
    against the pinned fields, and those do not hold `title`. Without the system field,
    every update would lose `data.title`.

    The form has no explicit `title` field, as on the live instance.
    """
    no_title_fields = [
        FormFieldDef.model_validate(
            {
                "key": "cost",
                "type": "currency",
                "label": {"de": "Kosten"},
                "isPromoted": True,
                "promoteTarget": "amount",
            }
        ),
        FormFieldDef.model_validate(
            {"key": "note", "type": "text", "label": {"de": "Notiz"}}
        ),
    ]
    app_type, _, _ = await _seed_type(session, fields=no_title_fields)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))
    assert (await svc.get(app.id, include_pii=False)).data["title"] == "Mein Antrag"

    out = await svc.patch(
        app.id,
        {"title": "Mein Antrag", "cost": "120.00", "note": "x"},
        changed_by="applicant",
    )
    assert out.data["title"] == "Mein Antrag"

    refreshed = await svc.get(app.id, include_pii=False)
    assert refreshed.data["title"] == "Mein Antrag"


async def test_patch_invalid_data_422_no_new_version(session: AsyncSession) -> None:
    """Answer 422 for a missing title and write no v2."""
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))
    with pytest.raises(ValidationProblem):
        await svc.patch(app.id, {"cost": "1.00"}, changed_by="applicant")
    versions = await svc.versions(app.id)
    assert [v.version for v in versions] == [1]


async def test_patch_locked_state_409(session: AsyncSession) -> None:
    app_type, _, locked = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))

    app.current_state_id = locked.id
    await session.commit()

    with pytest.raises(ConflictError):
        await svc.patch(app.id, {"title": "X", "cost": "1.00", "note": "g"}, changed_by="applicant")


async def test_list_filters_and_paging(session: AsyncSession) -> None:
    """Filter and page the list.

    An actor other than "applicant" sets `email_confirmed_at` at once. Without it the
    unconfirmed guest submissions stay invisible in the list.
    """
    app_type, draft, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    a1, _ = await svc.create(_create_payload(app_type.id), actor="admin")
    p2 = _create_payload(app_type.id)
    p2.data = {"title": "Solarpanel", "cost": "5.00", "note": "g"}
    await svc.create(p2, actor="admin")

    page = await svc.list_applications(type_id=app_type.id, limit=50, offset=0)
    assert page.total == 2

    by_state = await svc.list_applications(state_ids=[draft.id], limit=50, offset=0)
    assert by_state.total == 2

    by_q = await svc.list_applications(q="solarpanel", limit=50, offset=0)
    assert by_q.total == 1
    assert by_q.items[0].id != a1.id

    empty = await svc.list_applications(q="nichtvorhanden", limit=50, offset=0)
    assert empty.total == 0


async def test_comment_visibility(session: AsyncSession) -> None:
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))

    await svc.add_comment(
        app.id,
        author="admin",
        author_kind="principal",
        body="intern",
        visibility="internal",
    )
    await svc.add_comment(
        app.id,
        author=None,
        author_kind="applicant",
        body="öffentlich",
        visibility="public",
    )

    principal_view = await svc.list_comments(app.id, include_internal=True)
    assert {c.body for c in principal_view} == {"intern", "öffentlich"}

    applicant_view = await svc.list_comments(app.id, include_internal=False)
    assert [c.body for c in applicant_view] == ["öffentlich"]


async def test_unconfirmed_guest_app_hidden_from_principal_item_reads(
    session: AsyncSession,
) -> None:
    """Hide an unconfirmed guest application from the item routes of a principal.

    The actor "applicant" leaves `email_confirmed_at` NULL. For a principal or a Gremium the
    router passes `allow_unconfirmed=False`, so every item route gives 404, as the list
    hides it, and leaks no existence oracle. The owning applicant comes through the magic
    link with the default `allow_unconfirmed=True` and reads the application in full.
    """
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))
    assert app.email_confirmed_at is None

    with pytest.raises(NotFoundError):
        await svc.get(app.id, include_pii=True, allow_unconfirmed=False)
    with pytest.raises(NotFoundError):
        await svc.effective_form(app.id, allow_unconfirmed=False)
    with pytest.raises(NotFoundError):
        await svc.timeline(app.id, allow_unconfirmed=False)
    with pytest.raises(NotFoundError):
        await svc.versions(app.id, allow_unconfirmed=False)
    with pytest.raises(NotFoundError):
        await svc.list_comments(app.id, include_internal=True, allow_unconfirmed=False)
    with pytest.raises(NotFoundError):
        await svc.patch(
            app.id, {"title": "neu"}, changed_by="admin", allow_unconfirmed=False
        )

    out = await svc.get(app.id, include_pii=False)
    assert out.id == app.id
    assert (await svc.timeline(app.id)) != []
    assert (await svc.versions(app.id)) != []
    await svc.effective_form(app.id)
    assert (await svc.list_comments(app.id, include_internal=False)) == []


async def test_confirmed_app_readable_by_principal_item_reads(
    session: AsyncSession,
) -> None:
    """Let a principal read an application that an actor other than "applicant" confirmed."""
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id), actor="admin")
    assert app.email_confirmed_at is not None

    out = await svc.get(app.id, include_pii=True)
    assert out.id == app.id
    assert (await svc.timeline(app.id)) != []
    assert (await svc.versions(app.id)) != []


async def test_create_drops_unknown_keys(session: AsyncSession) -> None:
    """Drop unknown keys, also from v1."""
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(app_type.id),
            "data": {"title": "T", "cost": "1.00", "note": "g", "junk": "x" * 50},
            "applicantEmail": "x@example.org",
        }
    )
    app, _ = await svc.create(payload)
    out = await svc.get(app.id, include_pii=False)
    assert "junk" not in out.data
    v1 = (await svc.versions(app.id))[0]
    assert "junk" not in (v1.data or {})


async def test_patch_drops_unknown_keys(session: AsyncSession) -> None:
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))
    out = await svc.patch(
        app.id,
        {"title": "Neu", "cost": "2.00", "note": "g", "evil": {"a": 1}},
        changed_by="applicant",
    )
    assert "evil" not in out.data
    v2 = (await svc.versions(app.id))[1]
    assert "evil" not in (v2.data or {})
    assert "evil" not in (v2.diff or {}).get("added", {})


async def test_patch_has_budget_context_from_type(session: AsyncSession) -> None:
    """Take the has_budget context of a patch from the type.

    The type has a budget but no pot. A field that the has_budget flag makes visible and
    required must stay required on edit, else a user could drop it. A patch without `reason`
    gives 422.
    """
    cond_fields = [
        FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
        FormFieldDef.model_validate(
            {
                "key": "reason",
                "type": "text",
                "label": {"de": "Begründung"},
                "required": True,
                "visibleIf": {"==": [{"var": "has_budget"}, True]},
            }
        ),
    ]
    app_type, _, _ = await _seed_type(session, has_budget=True, fields=cond_fields)
    svc = ApplicationsService(session)
    app, _ = await svc.create(
        ApplicationCreate.model_validate(
            {
                "typeId": str(app_type.id),
                "data": {"title": "T", "reason": "weil"},
                "applicantEmail": "x@example.org",
            }
        )
    )
    with pytest.raises(ValidationProblem) as ei:
        await svc.patch(app.id, {"title": "T2"}, changed_by="applicant")
    assert ei.value.errors is not None
    assert any(e.field == "reason" for e in ei.value.errors)


async def _seed_type_for_search(session: AsyncSession) -> ApplicationType:
    """Seed a type for the fuzzy search against real Postgres with pg_trgm."""
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
        app_type.id, FormVersionCreate(fields=_fields(), activate=True), "tester"
    )
    flow = FlowVersion(version=1, active=True, editor_layout={})
    session.add(flow)
    await session.flush()
    draft = State(
        flow_version_id=flow.id,
        key="draft",
        label_i18n={"de": "Entwurf"},
        edit_allowed=True,
        is_initial=True,
    )
    session.add(draft)
    await session.commit()
    return app_type


async def test_list_fuzzy_search_meaningful_text(session: AsyncSession) -> None:
    """Fuzzy search runs on MEANINGFUL text (title and text answers), not ids or numbers.

    The test runs against real Postgres. `app_search_text(data)` plus trigram finds the
    application through a typo in the title. The same query also finds it through a text
    answer value (`note`). A plain number value (`cost`) does NOT match, because an
    amount gives no text match.

    The applications use an actor other than "applicant", so they are confirmed and the list
    shows them.
    """
    app_type = await _seed_type_for_search(session)
    svc = ApplicationsService(session)
    for title, note, cost in (
        ("Solaranlage Dach", "Photovoltaik für die Mensa", "1234.00"),
        ("Bücherregal", "Holz aus dem Baumarkt", "200.00"),
    ):
        payload = ApplicationCreate.model_validate(
            {
                "typeId": str(app_type.id),
                "data": {"title": title, "cost": cost, "note": note},
                "applicantEmail": "x@example.org",
            }
        )
        await svc.create(payload, actor="admin")

    by_title = await svc.list_applications(q="Solaranlge", limit=50, offset=0)
    assert by_title.total == 1
    assert by_title.items[0].title == "Solaranlage Dach"

    by_note = await svc.list_applications(q="Photovoltaik", limit=50, offset=0)
    assert {i.title for i in by_note.items} == {"Solaranlage Dach"}

    by_amount = await svc.list_applications(q="1234", limit=50, offset=0)
    assert by_amount.total == 0


async def test_anonymize_clears_pii_keeps_application(session: AsyncSession) -> None:
    """Empty the PII field, keep the application and its other fields (DSGVO Art. 17)."""
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))

    await svc.anonymize(app.id)

    out = await svc.get(app.id, include_pii=True)
    assert out is not None
    assert out.data.get("note") is None
    assert out.data["title"] == "Mein Antrag"
    assert out.applicant is not None
    assert out.applicant.email is None
    assert out.applicant.name is None
    assert out.applicant.anonymized is True


async def test_anonymize_clears_the_capture_intake(session: AsyncSession) -> None:
    """Clear the intake note, which can name a person; keep the date and the member."""
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))
    app.captured_by = "clerk"
    app.capture_intake = "per Mail von Frau Beispiel"
    app.received_on = app.created_at.date()
    await session.commit()

    await svc.anonymize(app.id)

    await session.refresh(app)
    assert app.capture_intake is None
    assert app.captured_by == "clerk"
    assert app.received_on is not None


async def test_anonymize_scrubs_version_history(session: AsyncSession) -> None:
    """Remove the PII from every stored version."""
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))
    await svc.patch(
        app.id, {"title": "T", "cost": "100.00", "note": "geheim2"}, changed_by="applicant"
    )

    await svc.anonymize(app.id)

    versions = await svc.versions(app.id)
    assert len(versions) == 2
    for v in versions:
        assert "note" not in (v.data or {})
        if v.diff is not None:
            for bucket in ("added", "removed", "changed"):
                assert "note" not in v.diff.get(bucket, {})


async def test_anonymize_scrubs_field_marked_pii_in_later_version(
    session: AsyncSession,
) -> None:
    """A field becomes PII only AFTER the submission, through a new form version.

    The application stays on its pinned version, where `title` is not PII.
    Anonymization must still union isPII over ALL versions of the type and remove the
    clear text (DSGVO Art. 17).

    The seed type has `note` as PII and `title` not. The new active version marks `title` as
    PII afterwards.
    """
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))

    later_fields = [
        FormFieldDef.model_validate(
            {
                "key": "title",
                "type": "text",
                "label": {"de": "Titel"},
                "required": True,
                "isPII": True,
            }
        ),
        FormFieldDef.model_validate(
            {
                "key": "cost",
                "type": "currency",
                "label": {"de": "Kosten"},
                "isPromoted": True,
                "promoteTarget": "amount",
            }
        ),
        FormFieldDef.model_validate(
            {"key": "note", "type": "text", "label": {"de": "Notiz"}, "isPII": True}
        ),
    ]
    await FormsService(session).create_form_version(
        app_type.id, FormVersionCreate(fields=later_fields, activate=True), "tester")

    await svc.anonymize(app.id)

    out = await svc.get(app.id, include_pii=True)
    assert out.data.get("note") is None
    assert out.data.get("title") is None


async def test_delete_writes_audit_entry_without_pii(session: AsyncSession) -> None:
    """Delete irreversibly and write exactly one audit entry with ids only, no PII."""
    from app.modules.audit.actions import AuditAction
    from app.modules.audit.models import AuditEntry

    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id), actor="admin")
    await svc.patch(
        app.id, {"title": "Neu", "cost": "100.00", "note": "geheim"}, changed_by="admin"
    )
    app_id = app.id

    await svc.delete(app_id, actor="admin")

    assert await session.get(Applicant, app_id) is None
    versions = await session.scalars(
        select(SubmissionVersion).where(SubmissionVersion.application_id == app_id)
    )
    assert versions.all() == []

    entry = (
        await session.scalars(
            select(AuditEntry).where(
                AuditEntry.action == AuditAction.APPLICATION_DELETE,
                AuditEntry.target_id == str(app_id),
            )
        )
    ).one()
    assert entry.actor == "admin"
    assert entry.target_type == "application"
    assert entry.data["typeId"] == str(app_type.id)
    assert entry.data["versionCount"] == 2
    serialized = str(entry.data)
    assert "geheim" not in serialized
    assert "Erika" not in serialized
    assert "Antrag@Example.ORG".lower() not in serialized.lower()
