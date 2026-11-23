"""The Paperless integration on a real Postgres, against a fake Paperless instance.

§ F/integrations/paperless/002511 the admin page saves the connection. § 002512 a part
whose switch is off files nothing. § 002516-002518, 002535 a final protocol, a decided
Antrag with its clean attachments and a plan in force are filed. § 002519 each document
carries its data and the link. § 002520 a file is filed once. § 002521 a replaced
document gets the tag `Ersetzt`. § 002523, 002526 a job that fails eight times shows in
the failed list and starts again. § 002524, 002525 the entry `In Paperless öffnen`.
§ 002530 the backfill. § 002531 the audit entries. § NF/security/network/002514 the
host allowlist. § 002515 no read returns the token. § 002527-002529, 002534 the insert:
the search and the copy.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import DbSession, get_current_principal
from app.modules.applications.models import Application, StatusEvent
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.budget.plan_models import BudgetPlan
from app.modules.budget.plan_schemas import PlanCreate, PlanLineSet, PlanStateSet
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_schemas import BudgetNodeCreate, FiscalYearCreate
from app.modules.files.models import Attachment
from app.modules.flow.models import State
from app.modules.gremien.models import Gremium
from app.modules.media.models import MarkdownDocument
from app.modules.media.router import get_media_service
from app.modules.media.service import MediaService
from app.modules.meetings.models import Meeting
from app.modules.meetings.protocol_models import Protocol
from app.modules.paperless.connection import ConnectionService
from app.modules.paperless.filings import MAX_TRIES, filed_for_applications
from app.modules.paperless.models import PaperlessFiling
from app.modules.paperless.schemas import ConnectionIn
from app.modules.paperless_filing.router import get_connection_service
from app.modules.site_config.models import SiteConfigVersion
from app.settings import Settings
from tests._support.guest_apps import (
    build_api,
    create_guest_application,
    guest_settings,
    seed_guest_flow,
)
from tests._support.memory_storage import MemoryStorage
from tests._support.paperless_fakes import BASE_URL, HOST, TOKEN, FakePaperless
from tests.integration.modules.documents.test_application_pdf import FakeTypst
from tests.unit.modules.media.test_media_documents import make_pdf
from worker.paperless import process_paperless_filings

pytestmark = pytest.mark.integration

_ADMIN = Principal(sub="admin-sub", roles=["admin"], email="admin@example.org")
_MEMBER = Principal(sub="member-sub", roles=["member"], email="member@example.org")
_USER = Principal(sub="user-sub", roles=["member"], permissions={"paperless.use"})

#: The moment each switch of the tests went on.
_SINCE = datetime.now(UTC) - timedelta(hours=1)
#: The moment of the events of the tests, after the switches went on.
_EVENT = _SINCE + timedelta(minutes=30)
#: The first run of the worker, a day after the import: the suite runs for a long time, and
#: a job that a test opens must be due at the first run. Each later run is one day after
#: the run before it.
_RUN = datetime.now(UTC) + timedelta(days=1)

Maker = async_sessionmaker[AsyncSession]


@pytest.fixture
async def maker(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[Maker]:
    """Return the sessionmaker. The plan versions of other tests go, so they file nothing."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE budget_plan RESTART IDENTITY CASCADE"))
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return guest_settings(migrated[1]).model_copy(update={"paperless_host_allowlist": [HOST]})


@pytest.fixture
def fake() -> FakePaperless:
    return FakePaperless()


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
def ctx(
    maker: Maker, settings: Settings, fake: FakePaperless, storage: MemoryStorage
) -> dict[str, Any]:
    return {
        "settings": settings,
        "object_storage": storage,
        "typst_client": FakeTypst(),
        "paperless_sessionmaker": maker,
        "paperless_client_factory": fake.client,
    }


async def _connect(
    maker: Maker,
    settings: Settings,
    *,
    protocols: bool = False,
    applications: bool = False,
    plans: bool = False,
    insert: bool = False,
    now: datetime = _SINCE,
) -> None:
    """Save the connection with the switches of a test."""
    async with maker() as session:
        await ConnectionService(session, settings).save(
            ConnectionIn.model_validate(
                {
                    "baseUrl": BASE_URL,
                    "token": TOKEN,
                    "fileProtocols": protocols,
                    "fileApplications": applications,
                    "filePlans": plans,
                    "insertEnabled": insert,
                }
            ),
            actor=_ADMIN.sub,
            now=now,
        )
        await session.commit()


async def _protocol(
    maker: Maker, storage: MemoryStorage, *, finalized_at: datetime = _EVENT
) -> tuple[uuid.UUID, uuid.UUID]:
    """Write a final protocol with both PDFs. Return its id and the id of its meeting."""
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        gremium = Gremium(name=f"StuPa {tag}", slug=f"pl-{tag}")
        session.add(gremium)
        await session.flush()
        meeting = Meeting(gremium_id=gremium.id, title="3. Sitzung", date=date(2026, 11, 2))
        session.add(meeting)
        await session.flush()
        protocol = Protocol(
            meeting_id=meeting.id,
            gremium_id=gremium.id,
            status="final",
            finalized_at=finalized_at,
            pdf_storage_key=f"protocols/{tag}.pdf",
            public_pdf_storage_key=f"protocols/{tag}-public.pdf",
        )
        session.add(protocol)
        await session.commit()
        storage.blobs[f"protocols/{tag}.pdf"] = b"%PDF internal"
        storage.blobs[f"protocols/{tag}-public.pdf"] = b"%PDF public"
        return protocol.id, meeting.id


async def _decided(maker: Maker) -> uuid.UUID:
    """Write a confirmed Antrag and move it to an approved state. Return its id."""
    seed = await seed_guest_flow(maker)
    app_id = await create_guest_application(maker, seed)
    async with maker() as session:
        await session.execute(
            update(State).where(State.id == seed.locked_state_id).values(is_approved=True)
        )
        session.add(
            StatusEvent(
                application_id=app_id,
                from_state_id=seed.open_state_id,
                to_state_id=seed.locked_state_id,
                actor="lead-sub",
                at=_EVENT,
            )
        )
        await session.execute(
            update(Application)
            .where(Application.id == app_id)
            .values(current_state_id=seed.locked_state_id, email_confirmed_at=_SINCE)
        )
        await session.commit()
    return app_id


async def _attachment(
    maker: Maker,
    storage: MemoryStorage,
    app_id: uuid.UUID,
    name: str,
    *,
    scanned: bool = True,
    result: str | None = "clean",
) -> uuid.UUID:
    key = f"attachments/{uuid.uuid4().hex}"
    async with maker() as session:
        row = Attachment(
            application_id=app_id,
            filename=name,
            mime="application/pdf",
            size=4,
            storage_key=key,
            scanned=scanned,
            scan_result=result,
        )
        session.add(row)
        await session.commit()
        storage.blobs[key] = b"%PDF " + name.encode()
        return row.id


async def _plan_in_force(maker: Maker) -> tuple[uuid.UUID, uuid.UUID]:
    """Write a plan with a version in force. Return the ids of the plan and the version."""
    async with maker() as session:
        svc = BudgetTreeService(session, actor="tester")
        top = await svc.create_node(
            BudgetNodeCreate(key=f"P{uuid.uuid4().hex[:8]}", name="VS-Mittel")
        )
        inc = await svc.create_node(BudgetNodeCreate(key="1", name="Beiträge", parentId=top.id))
        exp = await svc.create_node(BudgetNodeCreate(key="8", name="Zuschüsse", parentId=top.id))
        fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
        await svc.set_plan_switch(top.id, True)
        await session.commit()
        old = await session.scalar(select(BudgetPlan).where(BudgetPlan.fiscal_year_id == fy.id))
        await session.delete(old)
        await session.commit()
        plan = await svc.create_plan(top.id, fy.id, PlanCreate())
        version_id = plan.versions[-1].id
        await svc.set_line(version_id, inc.id, PlanLineSet(side="income"))
        await svc.set_line(version_id, exp.id, PlanLineSet(side="expense"))
        await svc.set_line(version_id, inc.id, PlanLineSet(amount=Decimal(100)))
        await svc.set_line(version_id, exp.id, PlanLineSet(amount=Decimal(100)))
        await svc.set_plan_state(version_id, PlanStateSet(state="in_force"))
        await session.commit()
        return plan.id, version_id


async def _filings(maker: Maker) -> list[PaperlessFiling]:
    async with maker() as session:
        return list(
            (
                await session.scalars(
                    select(PaperlessFiling).order_by(PaperlessFiling.kind, PaperlessFiling.title)
                )
            ).all()
        )


async def _run(ctx: dict[str, Any], times: int = 2, *, start: int = 0) -> int:
    """Run the worker ``times`` times, one day apart. Return the documents filed."""
    filed = 0
    for step in range(start, start + times):
        filed += await process_paperless_filings(ctx, _RUN + timedelta(days=step))
    return filed


def _client(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakePaperless,
    principal: Principal | None,
) -> TestClient:
    from app.deps import get_session

    api = build_api(migrated[1], settings, monkeypatch)

    async def _connection() -> AsyncIterator[ConnectionService]:
        async for session in api.dependency_overrides[get_session]():
            yield ConnectionService(session, settings, fake.client)

    api.dependency_overrides[get_connection_service] = _connection
    api.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(api)


_BODY = {
    "baseUrl": f"{BASE_URL}/",
    "token": TOKEN,
    "fileProtocols": True,
    "fileApplications": False,
    "filePlans": False,
    "insertEnabled": False,
}


def test_the_admin_routes_need_the_admin_permission(
    migrated: tuple[str, str],
    engine: Engine,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakePaperless,
) -> None:
    with _client(migrated, settings, monkeypatch, fake, _USER) as client:
        assert client.get("/api/admin/paperless").status_code == 403
        assert client.put("/api/admin/paperless", json=_BODY).status_code == 403
        assert client.post("/api/admin/paperless/test").status_code == 403
        assert client.get("/api/admin/paperless/failed-filings").status_code == 403
        assert client.post("/api/admin/paperless/backfill").status_code == 403
        assert (
            client.post(f"/api/admin/paperless/failed-filings/{uuid.uuid4()}/retry").status_code
            == 403
        )


def test_the_connection_saves_and_no_read_returns_the_token(
    migrated: tuple[str, str],
    engine: Engine,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakePaperless,
) -> None:
    with _client(migrated, settings, monkeypatch, fake, _ADMIN) as client:
        first = client.get("/api/admin/paperless")
        assert first.status_code == 200
        assert first.json() == {
            "baseUrl": None,
            "tokenSet": False,
            "fileProtocols": False,
            "fileApplications": False,
            "filePlans": False,
            "insertEnabled": False,
            "allowedHosts": [HOST],
        }
        assert client.post("/api/admin/paperless/test").json() == {
            "ok": False,
            "error": "not_configured",
        }

        saved = client.put("/api/admin/paperless", json=_BODY)
        assert saved.status_code == 200
        assert saved.json()["baseUrl"] == BASE_URL
        assert saved.json()["tokenSet"] is True
        assert saved.json()["fileProtocols"] is True
        assert TOKEN not in saved.text
        assert TOKEN not in client.get("/api/admin/paperless").text

        assert client.post("/api/admin/paperless/test").json() == {"ok": True, "error": None}
        assert fake.requests[-1].headers["Authorization"] == f"Token {TOKEN}"

        # A save without a token keeps the stored token.
        kept = client.put("/api/admin/paperless", json={**_BODY, "token": None})
        assert kept.json()["tokenSet"] is True
        cleared = client.put(
            "/api/admin/paperless", json={**_BODY, "token": None, "clearToken": True}
        )
        assert cleared.json()["tokenSet"] is False

    with engine.connect() as conn:
        entries = conn.execute(
            select(AuditEntry.actor, AuditEntry.data)
            .where(AuditEntry.action == "paperless_connection")
            .order_by(AuditEntry.id)
        ).all()
    assert [entry.data["tokenChanged"] for entry in entries] == [True, False, True]
    assert entries[0].actor == _ADMIN.sub
    assert entries[0].data["baseUrl"] == BASE_URL
    assert all(TOKEN not in str(entry.data) for entry in entries)


def test_a_host_outside_the_allowlist_is_refused(
    migrated: tuple[str, str],
    engine: Engine,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakePaperless,
) -> None:
    with _client(migrated, settings, monkeypatch, fake, _ADMIN) as client:
        refused = client.put(
            "/api/admin/paperless", json={**_BODY, "baseUrl": "https://other.test"}
        )
        assert refused.status_code == 422
        assert refused.json()["code"] == "paperless_host_not_allowed"
        assert client.get("/api/admin/paperless").json()["baseUrl"] is None

    closed = settings.model_copy(update={"paperless_host_allowlist": []})
    with _client(migrated, closed, monkeypatch, fake, _ADMIN) as client:
        assert client.put("/api/admin/paperless", json=_BODY).status_code == 422


async def test_without_a_connection_the_worker_does_nothing(
    maker: Maker, ctx: dict[str, Any], storage: MemoryStorage, fake: FakePaperless
) -> None:
    await _protocol(maker, storage)
    assert await _run(ctx) == 0
    assert await _filings(maker) == []
    assert fake.requests == []


async def _feature(maker: Maker, *, on: bool) -> None:
    """Set the feature switch `paperless` in the active site configuration."""
    async with maker() as session:
        await session.execute(
            update(SiteConfigVersion)
            .where(SiteConfigVersion.active.is_(True))
            .values(branding={"features": {"paperless": on}})
        )
        await session.commit()


async def test_while_the_feature_is_off_the_worker_calls_nothing(
    maker: Maker,
    settings: Settings,
    ctx: dict[str, Any],
    storage: MemoryStorage,
    fake: FakePaperless,
) -> None:
    """§F/integrations/paperless/002762: the connection stays, the files wait."""
    await _connect(maker, settings, protocols=True)
    await _protocol(maker, storage)
    await _feature(maker, on=False)
    assert await _run(ctx) == 0
    assert await _filings(maker) == []
    assert fake.requests == []

    await _feature(maker, on=True)
    assert await _run(ctx, 2) == 2


async def test_a_part_whose_switch_is_off_files_nothing(
    maker: Maker,
    settings: Settings,
    ctx: dict[str, Any],
    storage: MemoryStorage,
    fake: FakePaperless,
) -> None:
    await _connect(maker, settings, plans=True)
    await _protocol(maker, storage)
    await _decided(maker)
    assert await _run(ctx) == 0
    assert await _filings(maker) == []
    assert fake.uploads == []


async def test_a_final_protocol_is_filed_once_in_both_variants(
    maker: Maker,
    settings: Settings,
    ctx: dict[str, Any],
    storage: MemoryStorage,
    fake: FakePaperless,
    engine: Engine,
) -> None:
    await _connect(maker, settings, protocols=True)
    protocol_id, meeting_id = await _protocol(maker, storage)

    assert await _run(ctx, 1) == 0
    assert await _run(ctx, 1, start=1) == 2
    assert await _run(ctx, 2, start=2) == 0

    rows = await _filings(maker)
    assert [(row.kind, row.state, row.title) for row in rows] == [
        ("protocol", "filed", "3. Sitzung"),
        ("protocol_public", "filed", "3. Sitzung (öffentlich)"),
    ]
    assert {row.element_id for row in rows} == {protocol_id}
    assert [upload["title"] for upload in fake.uploads] == [
        "3. Sitzung",
        "3. Sitzung (öffentlich)",
    ]
    internal = fake.uploads[0]
    assert internal["created"] == _EVENT.astimezone(ZoneInfo("Europe/Berlin")).date().isoformat()
    assert internal["bytes"] == "%PDF internal"
    assert fake.name_of("document_types", internal["document_type"]) == "Protokoll"
    assert [fake.name_of("tags", tag).split()[0] for tag in internal["tags"]] == ["StuPa"]

    link = f"{settings.public_base_url.rstrip('/')}/meetings/{meeting_id}"
    field = fake.names["custom_fields"]["Plattform"]
    assert len(fake.documents) == 2
    assert all(
        document["custom_fields"] == [{"field": field, "value": link}]
        for document in fake.documents.values()
    )

    with engine.connect() as conn:
        entries = conn.execute(
            select(AuditEntry.target_type, AuditEntry.target_id, AuditEntry.data).where(
                AuditEntry.action == "paperless_filed"
            )
        ).all()
    assert {(entry.target_type, entry.target_id) for entry in entries} == {
        ("protocol", str(protocol_id))
    }
    assert {entry.data["documentId"] for entry in entries} == set(fake.documents)


async def test_a_protocol_that_is_final_again_replaces_its_documents(
    maker: Maker,
    settings: Settings,
    ctx: dict[str, Any],
    storage: MemoryStorage,
    fake: FakePaperless,
) -> None:
    await _connect(maker, settings, protocols=True)
    protocol_id, _meeting = await _protocol(maker, storage)
    assert await _run(ctx) == 2
    first = set(fake.documents)

    async with maker() as session:
        await session.execute(
            update(Protocol)
            .where(Protocol.id == protocol_id)
            .values(finalized_at=_EVENT + timedelta(minutes=10))
        )
        await session.commit()
    assert await _run(ctx, 2, start=2) == 2

    replaced = fake.names["tags"]["Ersetzt"]
    assert len(fake.documents) == 4
    assert all(replaced in fake.documents[number]["tags"] for number in first)
    assert all(
        replaced not in document["tags"]
        for number, document in fake.documents.items()
        if number not in first
    )
    assert not any(request.method == "DELETE" for request in fake.requests)
    # A later run does not tag the documents again.
    patches = [request for request in fake.requests if request.method == "PATCH"]
    await _run(ctx, 1, start=4)
    assert [request for request in fake.requests if request.method == "PATCH"] == patches


async def test_a_decided_antrag_is_filed_with_its_clean_attachments(
    maker: Maker,
    settings: Settings,
    ctx: dict[str, Any],
    storage: MemoryStorage,
    fake: FakePaperless,
) -> None:
    await _connect(maker, settings, applications=True)
    app_id = await _decided(maker)
    await _attachment(maker, storage, app_id, "angebot.pdf")
    await _attachment(maker, storage, app_id, "rechnung.pdf")
    await _attachment(maker, storage, app_id, "offen.pdf", scanned=False, result=None)
    await _attachment(maker, storage, app_id, "virus.pdf", result="infected")

    assert await _run(ctx) == 3

    rows = await _filings(maker)
    assert [(row.kind, row.state, row.title) for row in rows] == [
        ("application", "filed", "Gastantrag"),
        ("attachment", "filed", "Gastantrag – angebot.pdf"),
        ("attachment", "filed", "Gastantrag – rechnung.pdf"),
    ]
    assert {row.actor for row in rows} == {"lead-sub"}
    assert {fake.name_of("document_types", upload["document_type"]) for upload in fake.uploads} == {
        "Antrag"
    }
    assert sorted(upload["bytes"] for upload in fake.uploads)[:2] == [
        "%PDF angebot.pdf",
        "%PDF rechnung.pdf",
    ]
    link = f"{settings.public_base_url.rstrip('/')}/applications/{app_id}"
    assert all(
        document["custom_fields"][0]["value"] == link for document in fake.documents.values()
    )

    async with maker() as session:
        listed = await filed_for_applications(session, [app_id, uuid.uuid4()])
    assert list(listed) == [app_id]
    assert {entry.document_id for entry in listed[app_id]} == set(fake.documents)
    assert all((entry.url or "").startswith(f"{BASE_URL}/documents/") for entry in listed[app_id])


async def test_a_plan_in_force_is_filed(
    maker: Maker,
    settings: Settings,
    ctx: dict[str, Any],
    fake: FakePaperless,
) -> None:
    await _connect(maker, settings, plans=True)
    plan_id, version_id = await _plan_in_force(maker)

    await _run(ctx)

    rows = [row for row in await _filings(maker) if row.source_id == version_id]
    assert [(row.kind, row.state, row.element_id) for row in rows] == [("plan", "filed", plan_id)]
    upload = next(u for u in fake.uploads if u["title"] == rows[0].title)
    assert fake.name_of("document_types", upload["document_type"]) == "Haushaltsplan"
    assert upload["bytes"] == "%PDF-1.7 fake"
    assert rows[0].link is not None
    assert "/budget/plan?budget=" in rows[0].link


async def test_a_job_fails_after_eight_tries_and_starts_again(
    migrated: tuple[str, str],
    maker: Maker,
    settings: Settings,
    ctx: dict[str, Any],
    storage: MemoryStorage,
    fake: FakePaperless,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _connect(maker, settings, protocols=True)
    await _protocol(maker, storage)
    fake.down = True

    assert await _run(ctx, MAX_TRIES - 1) == 0
    assert {(row.state, row.attempts) for row in await _filings(maker)} == {
        ("pending", MAX_TRIES - 1)
    }
    assert await _run(ctx, 1, start=MAX_TRIES - 1) == 0
    rows = await _filings(maker)
    assert {(row.state, row.attempts, row.last_error) for row in rows} == {
        ("failed", MAX_TRIES, "unreachable")
    }
    # A failed job does not run again by itself.
    fake.down = False
    assert await _run(ctx, 1, start=MAX_TRIES + 30) == 0

    with _client(migrated, settings, monkeypatch, fake, _ADMIN) as client:
        failed = client.get("/api/admin/paperless/failed-filings").json()
        assert sorted(entry["kind"] for entry in failed) == ["protocol", "protocol_public"]
        assert {entry["error"] for entry in failed} == {"unreachable"}
        assert set(failed[0]) == {"id", "kind", "elementId", "title", "failedAt", "error"}
        for entry in failed:
            again = client.post(f"/api/admin/paperless/failed-filings/{entry['id']}/retry")
            assert again.status_code == 204
        assert client.get("/api/admin/paperless/failed-filings").json() == []
        unknown = client.post(f"/api/admin/paperless/failed-filings/{uuid.uuid4()}/retry")
        assert unknown.status_code == 404

    assert await _run(ctx, 2, start=MAX_TRIES + 60) == 2
    assert {row.state for row in await _filings(maker)} == {"filed"}


async def test_a_refused_file_fails_at_once_and_a_slow_one_waits(
    maker: Maker,
    settings: Settings,
    ctx: dict[str, Any],
    storage: MemoryStorage,
    fake: FakePaperless,
) -> None:
    await _connect(maker, settings, protocols=True)
    await _protocol(maker, storage)

    fake.consume = "wait"
    await process_paperless_filings(ctx, _RUN)
    await process_paperless_filings(ctx, _RUN + timedelta(minutes=1))
    assert {(row.state, row.attempts) for row in await _filings(maker)} == {("uploaded", 0)}
    assert len(fake.uploads) == 2

    fake.consume = "fail"
    await process_paperless_filings(ctx, _RUN + timedelta(minutes=2))
    assert {(row.state, row.last_error) for row in await _filings(maker)} == {
        ("failed", "rejected")
    }


async def test_the_backfill_files_the_documents_from_before(
    migrated: tuple[str, str],
    maker: Maker,
    settings: Settings,
    ctx: dict[str, Any],
    storage: MemoryStorage,
    fake: FakePaperless,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _connect(maker, settings, protocols=True)
    protocol_id, _meeting = await _protocol(
        maker, storage, finalized_at=_SINCE - timedelta(days=30)
    )
    await _decided(maker)
    assert await _run(ctx) == 0
    assert await _filings(maker) == []

    with _client(migrated, settings, monkeypatch, fake, _ADMIN) as client:
        # The Anträge part is off, so the action leaves the decided Antrag out.
        assert client.post("/api/admin/paperless/backfill").json() == {"started": 2}
        assert client.post("/api/admin/paperless/backfill").json() == {"started": 0}

    rows = await _filings(maker)
    assert {(row.kind, row.element_id, row.actor) for row in rows} == {
        ("protocol", protocol_id, _ADMIN.sub),
        ("protocol_public", protocol_id, _ADMIN.sub),
    }
    assert await _run(ctx, 2, start=2) == 2


async def test_the_entry_opens_the_document_only_with_the_permission(
    migrated: tuple[str, str],
    maker: Maker,
    settings: Settings,
    ctx: dict[str, Any],
    storage: MemoryStorage,
    fake: FakePaperless,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _connect(maker, settings, protocols=True)
    protocol_id, _meeting = await _protocol(maker, storage)
    path = f"/api/paperless/documents/protocol/{protocol_id}"

    with _client(migrated, settings, monkeypatch, fake, _MEMBER) as client:
        assert client.get(path).status_code == 403
    with _client(migrated, settings, monkeypatch, fake, _USER) as client:
        assert client.get(path).json() == {"url": None, "documentId": None}

    assert await _run(ctx) == 2
    internal = next(row.document_id for row in await _filings(maker) if row.kind == "protocol")
    with _client(migrated, settings, monkeypatch, fake, _USER) as client:
        assert client.get(path).json() == {
            "url": f"{BASE_URL}/documents/{internal}/details",
            "documentId": internal,
        }
        other = client.get(f"/api/paperless/documents/application/{protocol_id}")
        assert other.json() == {"url": None, "documentId": None}

    # With the part off the entry has no address (§ 002512).
    await _connect(maker, settings, protocols=False)
    with _client(migrated, settings, monkeypatch, fake, _USER) as client:
        assert client.get(path).json() == {"url": None, "documentId": None}


def _archive(fake: FakePaperless, document_id: int, title: str, content: bytes) -> None:
    """Put one document with its PDF version into the fake archive."""
    fake.documents[document_id] = {
        "id": document_id,
        "title": title,
        "created": "2026-10-30",
        "document_type": None,
        "tags": [],
        "custom_fields": [],
    }
    fake.files[document_id] = content


def test_the_search_needs_the_permission_and_the_switch(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakePaperless,
) -> None:
    """§ 002524 the search needs `paperless.use`; § 002512 it is off with its switch."""
    _archive(fake, 41, "Angebot Beamer", b"")
    _archive(fake, 42, "Bescheid", b"")
    body = {**_BODY, "insertEnabled": False}
    with _client(migrated, settings, monkeypatch, fake, _ADMIN) as client:
        assert client.put("/api/admin/paperless", json=body).status_code == 200
    with _client(migrated, settings, monkeypatch, fake, _MEMBER) as client:
        assert client.get("/api/paperless/insert").status_code == 403
        assert client.get("/api/paperless/search").status_code == 403
    with _client(migrated, settings, monkeypatch, fake, _USER) as client:
        assert client.get("/api/paperless/insert").json() == {"enabled": False}
        assert client.get("/api/paperless/search").status_code == 404
    assert [r for r in fake.requests if r.url.path == "/api/documents/"] == []

    with _client(migrated, settings, monkeypatch, fake, _ADMIN) as client:
        on = client.put("/api/admin/paperless", json={**body, "insertEnabled": True})
        assert on.status_code == 200
    with _client(migrated, settings, monkeypatch, fake, _USER) as client:
        assert client.get("/api/paperless/insert").json() == {"enabled": True}
        newest = client.get("/api/paperless/search")
        assert [hit["documentId"] for hit in newest.json()] == [42, 41]
        found = client.get("/api/paperless/search", params={"q": "beamer"})
        assert found.json() == [
            {
                "documentId": 41,
                "title": "Angebot Beamer",
                "documentType": None,
                "created": "2026-10-30",
            }
        ]


def test_the_search_tells_an_outage(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakePaperless,
) -> None:
    """§ 002529: a Paperless that fails answers 503 `paperless_unavailable`."""
    with _client(migrated, settings, monkeypatch, fake, _ADMIN) as client:
        assert (
            client.put("/api/admin/paperless", json={**_BODY, "insertEnabled": True}).status_code
            == 200
        )
        fake.down = True
        answer = client.get("/api/paperless/search", params={"q": "x"})
    assert answer.status_code == 503
    assert answer.json()["code"] == "paperless_unavailable"
    assert TOKEN not in answer.text


async def test_an_insert_copies_the_document_as_an_embedded_pdf(
    migrated: tuple[str, str],
    maker: Maker,
    settings: Settings,
    storage: MemoryStorage,
    fake: FakePaperless,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 002528 the copy is a stored PDF with the document number; § 002531 the audit entry."""
    _protocol_id, meeting_id = await _protocol(maker, storage)
    pdf = make_pdf(2)
    _archive(fake, 41, "Angebot Beamer", pdf)
    _archive(fake, 42, "Kein PDF", b"plain text")
    path = f"/api/meetings/{meeting_id}/documents/paperless"

    def _media(db: DbSession) -> MediaService:
        return MediaService(db, storage=storage, settings=settings)

    def _with_media(principal: Principal) -> TestClient:
        client = _client(migrated, settings, monkeypatch, fake, principal)
        api: Any = client.app
        api.dependency_overrides[get_media_service] = _media
        return client

    # With the part off there is no copy (§ 002512).
    await _connect(maker, settings, insert=False)
    with _with_media(_ADMIN) as client:
        assert client.post(path, json={"documentId": 41}).status_code == 404

    await _connect(maker, settings, insert=True)
    with _with_media(_MEMBER) as client:
        assert client.post(path, json={"documentId": 41}).status_code == 403
    with _with_media(_USER) as client:
        # `paperless.use` alone does not write the protocol of the Sitzung.
        assert client.post(path, json={"documentId": 41}).status_code == 403
    with _with_media(_ADMIN) as client:
        assert client.post(path, json={"documentId": 42}).status_code == 415
        created = client.post(path, json={"documentId": 41})
        assert created.status_code == 201
        body = created.json()
        assert body["name"] == "Angebot Beamer.pdf"
        assert body["pages"] == 2
        assert body["url"] == f"/api/media/documents/{body['id']}"
        fake.down = True
        down = client.post(path, json={"documentId": 41})
        assert down.status_code == 503
        assert down.json()["code"] == "paperless_unavailable"

    async with maker() as session:
        row = await session.get(MarkdownDocument, uuid.UUID(body["id"]))
        assert row is not None
        assert (row.meeting_id, row.paperless_document_id) == (meeting_id, 41)
        assert storage.blobs[row.storage_key] == pdf
        entries = (
            await session.scalars(
                select(AuditEntry).where(AuditEntry.action == "paperless_inserted")
            )
        ).all()
    mine = [entry for entry in entries if entry.target_id == body["id"]]
    assert len(mine) == 1
    assert mine[0].actor == _ADMIN.sub
    assert mine[0].data == {"meetingId": str(meeting_id), "documentId": 41}
