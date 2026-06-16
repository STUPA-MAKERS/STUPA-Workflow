"""Integration (echte Postgres, testcontainers): ApplicationsService-Lebenszyklus.

Beweist gegen ein echtes Schema (data-model §1/§2, flows §1/§2):
Create→PII-Trennung+v1+Initial-State, PATCH→neue Version+Diff+amount-Sync,
Edit-Lock (409), Timeline, Versionshistorie, Liste/Filter, Kommentar-Sichtbarkeit
und Anonymisierung (PII geleert, Antrag bleibt).
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
from app.shared.errors import ConflictError, ValidationProblem

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
    """Typ mit aktiver Form-Version + Flow (Initial-State + gesperrter State)."""
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
        app_type.id, FormVersionCreate(fields=fields or _fields(), activate=True)
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


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #
async def test_create_separates_pii_and_writes_v1(session: AsyncSession) -> None:
    app_type, draft, _ = await _seed_type(session)
    svc = ApplicationsService(session)

    app, email = await svc.create(_create_payload(app_type.id))
    assert email == "Antrag@example.org"  # EmailStr normalisiert die Domain klein
    assert app.current_state_id == draft.id
    assert app.amount == Decimal("100.00")
    assert app.currency == "EUR"
    assert app.gremium_id == app_type.gremium_id

    applicant = (
        await session.execute(select(Applicant).where(Applicant.application_id == app.id))
    ).scalar_one()
    assert applicant.email == "Antrag@example.org"
    assert applicant.name == "Erika"
    # citext: case-insensitiver Treffer trotz gemischter Schreibweise.
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
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(app_type.id),
            "data": {"cost": "5.00"},  # title (required) fehlt
            "applicantEmail": "x@example.org",
        }
    )
    with pytest.raises(ValidationProblem) as ei:
        await svc.create(payload)
    assert ei.value.status == 422
    assert ei.value.errors is not None
    assert any(e.field == "title" for e in ei.value.errors)


# --------------------------------------------------------------------------- #
# patch + versioning + edit-lock
# --------------------------------------------------------------------------- #
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
    """Issue #1: ein Antragstyp OHNE eigenes `title`-Feld nutzt das zur Laufzeit
    vorangestellte System-Titelfeld. `patch()` whitelistet gegen die gepinnten Felder
    (ohne `title`) — ohne das System-Feld ginge `data.title` bei jedem Update verloren."""
    # Form ohne explizites `title`-Feld (wie auf der Live-Instanz).
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
    app, _ = await svc.create(_create_payload(app_type.id))  # title="Mein Antrag"
    assert (await svc.get(app.id, include_pii=False)).data["title"] == "Mein Antrag"

    out = await svc.patch(
        app.id,
        {"title": "Mein Antrag", "cost": "120.00", "note": "x"},
        changed_by="applicant",
    )
    assert out.data["title"] == "Mein Antrag"  # darf NICHT gedroppt werden

    refreshed = await svc.get(app.id, include_pii=False)
    assert refreshed.data["title"] == "Mein Antrag"


async def test_patch_invalid_data_422_no_new_version(session: AsyncSession) -> None:
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))
    with pytest.raises(ValidationProblem):
        await svc.patch(app.id, {"cost": "1.00"}, changed_by="applicant")  # title fehlt
    versions = await svc.versions(app.id)
    assert [v.version for v in versions] == [1]  # keine v2 geschrieben


async def test_patch_locked_state_409(session: AsyncSession) -> None:
    app_type, _, locked = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))

    app.current_state_id = locked.id
    await session.commit()

    with pytest.raises(ConflictError):
        await svc.patch(app.id, {"title": "X", "cost": "1.00", "note": "g"}, changed_by="applicant")


# --------------------------------------------------------------------------- #
# list + filters
# --------------------------------------------------------------------------- #
async def test_list_filters_and_paging(session: AsyncSession) -> None:
    app_type, draft, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    # actor != "applicant" ⇒ sofort ``email_confirmed_at`` (sonst sind die unbestätigten
    # Gast-Einreichungen in der Liste unsichtbar; vgl. ``test_list_fuzzy_search_…``).
    a1, _ = await svc.create(_create_payload(app_type.id), actor="admin")
    p2 = _create_payload(app_type.id)
    p2.data = {"title": "Solarpanel", "cost": "5.00", "note": "g"}
    await svc.create(p2, actor="admin")

    page = await svc.list_applications(type_id=app_type.id, limit=50, offset=0)
    assert page.total == 2

    by_state = await svc.list_applications(state_id=draft.id, limit=50, offset=0)
    assert by_state.total == 2

    by_q = await svc.list_applications(q="solarpanel", limit=50, offset=0)
    assert by_q.total == 1
    assert by_q.items[0].id != a1.id

    empty = await svc.list_applications(q="nichtvorhanden", limit=50, offset=0)
    assert empty.total == 0


# --------------------------------------------------------------------------- #
# comments
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# HIGH #1 — unbekannte Keys werden verworfen (nicht persistiert)
# --------------------------------------------------------------------------- #
async def test_create_drops_unknown_keys(session: AsyncSession) -> None:
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
    # auch nicht in v1
    v1 = (await svc.versions(app.id))[0]
    assert "junk" not in v1.data


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
    assert "evil" not in v2.data
    assert "evil" not in (v2.diff or {}).get("added", {})


# --------------------------------------------------------------------------- #
# MED — has_budget-Kontext: patch nutzt Typ (nicht budget_pot_id)
# --------------------------------------------------------------------------- #
async def test_patch_has_budget_context_from_type(session: AsyncSession) -> None:
    # has_budget-Typ OHNE Topf: ein bei has_budget=true sichtbares Pflichtfeld muss auch
    # beim Edit Pflicht bleiben (sonst straflos entfernbar).
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
    # `reason` weglassen → muss 422 sein (Feld sichtbar+Pflicht via Typ-has_budget).
    with pytest.raises(ValidationProblem) as ei:
        await svc.patch(app.id, {"title": "T2"}, changed_by="applicant")
    assert ei.value.errors is not None
    assert any(e.field == "reason" for e in ei.value.errors)


# --------------------------------------------------------------------------- #
# fuzzy search (#3/#4) — echtes Postgres / pg_trgm
# --------------------------------------------------------------------------- #
async def _seed_type_for_search(session: AsyncSession) -> ApplicationType:
    """Wie :func:`_seed_type`, aber ohne das (entfernte) ``FlowVersion``-Type-Feld.

    ``_seed_type`` übergibt ``FlowVersion(application_type_id=…)`` — diese Spalte gibt
    es seit Migration 0019 nicht mehr (Type-Flows entfernt); der Helfer ist auf main
    bereits gebrochen. Hier ein minimaler, korrekter Seed für die Suche.
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
    await forms.create_form_version(app_type.id, FormVersionCreate(fields=_fields(), activate=True))
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
    """Fuzzy-Suche auf SINNVOLLEM Text (Titel + Text-Antworten), nicht ids/Zahlen.

    Beweist gegen echtes Postgres: ``app_search_text(data)`` + Trigram findet den
    Antrag per Tippfehler im Titel UND per Text-Antwortwert (``note``), während ein
    reiner Zahlenwert (``cost``) NICHT trifft (kein Text-Match auf Beträgen).
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
        # actor != "applicant" ⇒ sofort ``email_confirmed_at`` (sichtbar in der Liste).
        await svc.create(payload, actor="admin")

    # Tippfehler im Titel »Solaranlge« ⇒ Trigram-Treffer.
    by_title = await svc.list_applications(q="Solaranlge", limit=50, offset=0)
    assert by_title.total == 1
    assert by_title.items[0].title == "Solaranlage Dach"

    # Treffer über den Text-Antwortwert (``note``), nicht nur den Titel.
    by_note = await svc.list_applications(q="Photovoltaik", limit=50, offset=0)
    assert {i.title for i in by_note.items} == {"Solaranlage Dach"}

    # Der reine Betrag (``cost`` = 1234.00) ist KEIN Text-Antwortwert ⇒ kein Treffer.
    by_amount = await svc.list_applications(q="1234", limit=50, offset=0)
    assert by_amount.total == 0


# --------------------------------------------------------------------------- #
# anonymize (DSGVO Art. 17)
# --------------------------------------------------------------------------- #
async def test_anonymize_clears_pii_keeps_application(session: AsyncSession) -> None:
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))

    await svc.anonymize(app.id)

    out = await svc.get(app.id, include_pii=True)
    assert out is not None  # Antrag bleibt
    assert out.data.get("note") is None  # PII-Feld geleert
    assert out.data["title"] == "Mein Antrag"  # Nicht-PII bleibt
    assert out.applicant is not None
    assert out.applicant.email is None
    assert out.applicant.name is None
    assert out.applicant.anonymized is True


async def test_anonymize_scrubs_version_history(session: AsyncSession) -> None:
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))  # note="geheim" in v1
    await svc.patch(
        app.id, {"title": "T", "cost": "100.00", "note": "geheim2"}, changed_by="applicant"
    )

    await svc.anonymize(app.id)

    versions = await svc.versions(app.id)
    assert len(versions) == 2
    for v in versions:
        assert "note" not in v.data  # PII aus jedem Snapshot
        if v.diff is not None:
            for bucket in ("added", "removed", "changed"):
                assert "note" not in v.diff.get(bucket, {})


async def test_anonymize_scrubs_field_marked_pii_in_later_version(
    session: AsyncSession,
) -> None:
    """Ein Feld wird ERST NACH der Einreichung als PII markiert (neue Form-Version).

    Der Antrag bleibt auf seine gepinnte Version (``title`` dort nicht PII) — die
    Anonymisierung muss isPII trotzdem über ALLE Versionen des Typs vereinen und den
    Klartext entfernen (DSGVO Art. 17)."""
    app_type, _, _ = await _seed_type(session)  # title NICHT PII, note PII
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))  # title="Mein Antrag"

    # `title` nachträglich als PII markieren → neue, aktive Form-Version.
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
        app_type.id, FormVersionCreate(fields=later_fields, activate=True)
    )

    await svc.anonymize(app.id)

    out = await svc.get(app.id, include_pii=True)
    assert out.data.get("note") is None  # gepinnt-PII
    assert out.data.get("title") is None  # erst später als PII markiert → trotzdem gescrubbt
