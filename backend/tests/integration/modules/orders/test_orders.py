"""Bestellungen of an Antrag on a real Postgres.

§ F/finance/orders/002850 a Bestellung belongs to one Antrag and goes with it. § 002858 the
create needs an approved Antrag of a type with money. § 002853 each status from each other
status, with the dates. § 002860 a position belongs to at most one Bestellung that is not
cancelled. § 002862 only ``order.manage`` writes. § 002863 the read follows the Antrag.
§ 002864 the applicant view. § 002865 the audit entries and the revert. § 002866 the
timeline. § 002867 the version. § 002868 the sum. § 002930 no migration creates a Bestellung.
§ 002873 at most one invoice, § 002874 the real price from the invoice, § 002877 the
Bestellungen of an invoice. § 002878 a booking names a Bestellung, § 002880 the marks,
§ 002881 the cancel keeps the bookings.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import DbSession, SettingsDep, get_current_applicant, get_current_principal
from app.modules.admin.principal_merge import PrincipalMergeService
from app.modules.application_types.models import ApplicationType
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Applicant, Principal
from app.modules.budget.tree_models import Budget, BudgetExpense, FiscalYear, Invoice
from app.modules.config_revision.revert import RevertService
from app.modules.files.models import Attachment
from app.modules.files.service import FilesService
from app.modules.flow.models import State
from app.modules.orders.models import PurchaseOrder
from app.modules.orders.privacy import clear_buyer_names
from app.modules.orders.router import get_order_files
from app.modules.privacy.service import AuskunftService, PrincipalService
from app.settings import Settings
from app.shared.errors import ConflictError
from tests._support.guest_apps import GuestSeed, build_api, guest_settings, seed_guest_flow
from tests._support.memory_storage import MemoryStorage, wire_storage

pytestmark = pytest.mark.integration

_READ = {"application.read"}
_MANAGER = Principal(sub="orders-sub", roles=["member"], permissions={*_READ, "order.manage"})
_READER = Principal(sub="reader-sub", roles=["member"], permissions=_READ)
_BOOKER = Principal(
    sub="booker-sub",
    roles=["member"],
    permissions={*_READ, "application.manage", "budget.book"},
)
_FINANCE = Principal(
    sub="finance-sub",
    roles=["member"],
    permissions={*_READ, "order.manage", "budget.book"},
)
_LEDGER = Principal(sub="ledger-sub", roles=["member"], permissions={"budget.view"})
_BLIND = Principal(sub="blind-sub", roles=["member"], permissions={"order.manage"})
_POSITIONS = [
    {"id": "p1", "label": "Regal", "offers": [{"label": "A", "value": 60}]},
    {"id": "p2", "label": "Drucker", "offers": [{"label": "B", "value": 500}]},
]
_PDF = b"%PDF-1.4\n%invoice\n"


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return guest_settings(migrated[1])


@pytest.fixture
async def seed(maker: async_sessionmaker[AsyncSession]) -> GuestSeed:
    return await seed_guest_flow(maker)


def _client(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    principal: Principal | None,
    applicant: Applicant | None = None,
    storage: MemoryStorage | None = None,
) -> TestClient:
    """Build a client of one caller; with ``storage`` the file routes use it."""
    api = build_api(migrated[1], settings, monkeypatch)
    api.dependency_overrides[get_current_principal] = lambda: principal
    api.dependency_overrides[get_current_applicant] = lambda: applicant

    def _files(session: DbSession, request_settings: SettingsDep) -> FilesService:
        return FilesService(session, storage=storage, settings=request_settings)

    if storage is not None:
        api.dependency_overrides[get_order_files] = _files
        wire_storage(api, storage)
    return TestClient(api)


async def _antrag(
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
    *,
    money: bool = True,
    approved: bool = True,
) -> uuid.UUID:
    """Create an Antrag with two positions, approved for 500 euro by default."""
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(seed.type_id),
            "data": {"title": "Büroausstattung"},
            "applicantEmail": "luis@example.org",
            "applicantName": "Luis Meyer",
        }
    )
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            payload, actor="owner-sub", email_confirmed=True
        )
        await session.execute(
            update(ApplicationType)
            .where(ApplicationType.id == seed.type_id)
            .values(has_budget=money)
        )
        await session.execute(
            update(State).where(State.id == seed.open_state_id).values(is_approved=approved)
        )
        await session.execute(
            update(Application)
            .where(Application.id == app.id)
            .values(
                approved_amount=Decimal("500.00"),
                data={"title": "Büroausstattung", "kosten": _POSITIONS},
            )
        )
        await session.commit()
        return app.id


async def _count(maker: async_sessionmaker[AsyncSession]) -> int:
    async with maker() as session:
        return int(await session.scalar(select(func.count()).select_from(PurchaseOrder)) or 0)


async def _audit(maker: async_sessionmaker[AsyncSession], action: str) -> list[AuditEntry]:
    async with maker() as session:
        return list(
            await session.scalars(
                select(AuditEntry).where(AuditEntry.action == action).order_by(AuditEntry.id)
            )
        )


async def test_no_bestellung_exists_before_a_person_creates_one(
    maker: async_sessionmaker[AsyncSession], seed: GuestSeed
) -> None:
    """§ 002930: the migrations and the create of an Antrag create no Bestellung."""
    await _antrag(maker, seed)
    assert await _count(maker) == 0


async def test_create_needs_an_approved_antrag_of_a_type_with_money(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 002858 + § 002862 + § 002856 + § 002852: the gates of the create."""
    api = _client(migrated, settings, monkeypatch, _MANAGER)
    app_id = await _antrag(maker, seed, approved=False)
    base = f"/api/applications/{app_id}/orders"
    refused = api.post(base, json={"title": "Regal"})
    assert (refused.status_code, refused.json()["code"]) == (409, "application_not_approved")
    assert api.get(base).json()["canCreate"] is False

    await _antrag(maker, seed, money=False)
    no_money = api.post(base, json={"title": "Regal"})
    assert (no_money.status_code, no_money.json()["code"]) == (
        422,
        "application_type_without_budget",
    )

    await _antrag(maker, seed)
    for principal in (_READER, _BOOKER):
        other = _client(migrated, settings, monkeypatch, principal)
        assert other.post(base, json={"title": "Regal"}).status_code == 403
    blind = _client(migrated, settings, monkeypatch, _BLIND)
    assert blind.post(base, json={"title": "Regal"}).status_code == 403
    anonymous = _client(migrated, settings, monkeypatch, None)
    assert anonymous.post(base, json={"title": "Regal"}).status_code == 401

    bad_link = api.post(base, json={"title": "Regal", "url": "javascript:alert(1)"})
    assert (bad_link.status_code, bad_link.json()["code"]) == (422, "order_url_invalid")
    no_buyer = api.post(base, json={"title": "Stifte", "kind": "outlay"})
    assert (no_buyer.status_code, no_buyer.json()["code"]) == (422, "order_buyer_required")
    ghost = api.post(base, json={"title": "Stifte", "buyerId": str(uuid.uuid4())})
    assert (ghost.status_code, ghost.json()["code"]) == (422, "order_buyer_unknown")
    assert await _count(maker) == 0

    created = api.post(
        base,
        json={
            "title": "Regal",
            "supplier": "OTTO Office",
            "url": "https://shop.example/regal",
            "plannedAmount": "60.94",
            "kind": "outlay",
            "buyerName": "Anna",
            "status": "ordered",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["number"].startswith("B-")
    assert len(body["number"]) == 10
    assert (body["status"], body["version"], body["buyerName"]) == ("ordered", 1, "Anna")
    assert body["orderedOn"] is not None
    assert body["deliveredOn"] is None
    listed = api.get(base).json()
    assert listed["canManage"] is True
    assert listed["canCreate"] is True
    assert [item["id"] for item in listed["items"]] == [body["id"]]


async def test_status_version_and_change(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 002853 + § 002867 + § 002852 + § 002858: status, version, kind and the left state."""
    api = _client(migrated, settings, monkeypatch, _MANAGER)
    app_id = await _antrag(maker, seed)
    order = api.post(f"/api/applications/{app_id}/orders", json={"title": "Regal"}).json()
    url = f"/api/orders/{order['id']}"

    delivered = api.post(f"{url}/status", json={"status": "delivered", "version": 1})
    assert delivered.status_code == 200, delivered.text
    assert (delivered.json()["status"], delivered.json()["version"]) == ("delivered", 2)
    assert delivered.json()["deliveredOn"] is not None
    assert delivered.json()["orderedOn"] is None
    old = api.post(f"{url}/status", json={"status": "planned", "version": 1})
    assert (old.status_code, old.json()["code"]) == (409, "order_version_conflict")
    for step, status in enumerate(("planned", "cancelled", "ordered", "delivered"), start=2):
        answer = api.post(f"{url}/status", json={"status": status, "version": step})
        assert answer.status_code == 200, answer.text
    assert api.post(f"{url}/status", json={"status": "paid", "version": 6}).status_code == 422

    typed = api.patch(url, json={"version": 6, "deliveredOn": "2026-11-02", "note": "Raum 12"})
    assert typed.status_code == 200, typed.text
    assert (typed.json()["deliveredOn"], typed.json()["note"]) == ("2026-11-02", "Raum 12")
    again = api.post(f"{url}/status", json={"status": "delivered", "version": 7})
    assert again.json()["deliveredOn"] == "2026-11-02"

    stale = api.patch(url, json={"version": 1, "title": "Tisch"})
    assert (stale.status_code, stale.json()["code"]) == (409, "order_version_conflict")
    outlay = api.patch(url, json={"version": 8, "kind": "outlay"})
    assert (outlay.status_code, outlay.json()["code"]) == (422, "order_buyer_required")
    with_buyer = api.patch(url, json={"version": 8, "kind": "outlay", "buyerName": "Anna"})
    assert with_buyer.json()["kind"] == "outlay"
    no_title = api.patch(url, json={"version": 9, "title": None})
    assert (no_title.status_code, no_title.json()["code"]) == (422, "order_title_required")
    no_kind = api.patch(url, json={"version": 9, "kind": None})
    assert (no_kind.status_code, no_kind.json()["code"]) == (422, "order_kind_required")
    bad_link = api.patch(url, json={"version": 9, "url": "ftp://x"})
    assert (bad_link.status_code, bad_link.json()["code"]) == (422, "order_url_invalid")
    cleared = api.patch(url, json={"version": 9, "note": "", "url": "https://shop.example/a"})
    assert (cleared.json()["note"], cleared.json()["url"]) == (None, "https://shop.example/a")

    async with maker() as session:
        await session.execute(
            update(State).where(State.id == seed.open_state_id).values(is_approved=False)
        )
        await session.commit()
    after = api.patch(url, json={"version": 10, "supplier": "Böttcher"})
    assert after.json()["supplier"] == "Böttcher"
    assert api.post(f"/api/applications/{app_id}/orders", json={"title": "x"}).status_code == 409

    assert api.get(f"/api/orders/{uuid.uuid4()}").status_code == 404
    assert _client(migrated, settings, monkeypatch, _BLIND).get(url).status_code == 404
    assert (
        _client(migrated, settings, monkeypatch, _BLIND)
        .patch(url, json={"version": 11, "title": "Tisch"})
        .status_code
        == 404
    )


async def test_positions_belong_to_one_bestellung(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 002860: unknown id, taken position, free again after the cancel."""
    api = _client(migrated, settings, monkeypatch, _MANAGER)
    app_id = await _antrag(maker, seed)
    base = f"/api/applications/{app_id}/orders"
    unknown = api.post(base, json={"title": "Regal", "positionIds": ["p9"]})
    assert (unknown.status_code, unknown.json()["code"]) == (422, "order_position_unknown")
    first = api.post(base, json={"title": "Regal", "positionIds": ["p1", "p1"]}).json()
    assert first["positionIds"] == ["p1"]
    taken = api.post(base, json={"title": "Regal 2", "positionIds": ["p1", "p2"]})
    assert (taken.status_code, taken.json()["code"]) == (409, "order_position_taken")
    second = api.post(base, json={"title": "Drucker", "positionIds": ["p2"]}).json()
    moved = api.patch(f"/api/orders/{second['id']}", json={"version": 1, "positionIds": ["p1"]})
    assert (moved.status_code, moved.json()["code"]) == (409, "order_position_taken")

    cancelled = api.post(
        f"/api/orders/{first['id']}/status", json={"status": "cancelled", "version": 1}
    )
    assert cancelled.status_code == 200
    both = api.patch(
        f"/api/orders/{second['id']}", json={"version": 1, "positionIds": ["p1", "p2"]}
    )
    assert both.json()["positionIds"] == ["p1", "p2"]
    back = api.post(f"/api/orders/{first['id']}/status", json={"status": "planned", "version": 2})
    assert (back.status_code, back.json()["code"]) == (409, "order_position_taken")
    freed = api.patch(f"/api/orders/{second['id']}", json={"version": 2, "positionIds": []})
    assert freed.json()["positionIds"] == []
    assert (
        api.post(
            f"/api/orders/{first['id']}/status", json={"status": "planned", "version": 2}
        ).status_code
        == 200
    )


async def test_sum_applicant_view_timeline_and_delete(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 002868 + § 002864 + § 002866 + § 002850: sum, short view, timeline, delete."""
    api = _client(migrated, settings, monkeypatch, _MANAGER)
    app_id = await _antrag(maker, seed)
    base = f"/api/applications/{app_id}/orders"
    regal = api.post(base, json={"title": "Regal", "plannedAmount": "60.00"}).json()
    api.post(base, json={"title": "Drucker", "actualAmount": "539.09", "note": "intern"})
    gone = api.post(base, json={"title": "Stuhl", "plannedAmount": "900.00"}).json()
    api.post(f"/api/orders/{gone['id']}/status", json={"status": "cancelled", "version": 1})

    listed = api.get(base).json()
    assert (listed["total"], listed["approvedAmount"], listed["overBy"]) == (
        "599.09",
        "500.00",
        "99.09",
    )
    reader = _client(migrated, settings, monkeypatch, _READER)
    assert reader.get(base).json()["canManage"] is False
    assert reader.get(f"/api/orders/{regal['id']}").json()["plannedAmount"] == "60.00"

    applicant = _client(
        migrated, settings, monkeypatch, None, Applicant(application_id=str(app_id))
    )
    short = applicant.get(base).json()
    assert short["total"] is None
    assert set(short["items"][0]) == {
        "id",
        "number",
        "title",
        "kind",
        "status",
        "orderedOn",
        "deliveredOn",
    }
    assert set(applicant.get(f"/api/orders/{regal['id']}").json()) == set(short["items"][0])
    assert applicant.post(base, json={"title": "x"}).status_code in (401, 403)

    api.post(f"/api/orders/{regal['id']}/status", json={"status": "delivered", "version": 1})
    assert api.delete(f"/api/orders/{gone['id']}").status_code == 204
    assert api.delete(f"/api/orders/{gone['id']}").status_code == 404
    timeline = [
        event["order"]
        for event in api.get(f"/api/applications/{app_id}/timeline").json()
        if event["kind"] == "order"
    ]
    assert [(e["title"], e["change"], e["toStatus"]) for e in timeline] == [
        ("Regal", "created", None),
        ("Drucker", "created", None),
        ("Stuhl", "created", None),
        ("Stuhl", "status", "cancelled"),
        ("Regal", "status", "delivered"),
        ("Stuhl", "deleted", None),
    ]
    assert len(await _audit(maker, "order_create")) == 3
    assert len(await _audit(maker, "order_delete")) == 1

    async with maker() as session:
        await ApplicationsService(session).delete(app_id, actor="orders-sub")
    assert await _count(maker) == 0


async def test_audit_revert_sets_the_old_values(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 002865: the revert of a change and of a status change; no revert of a delete."""
    api = _client(migrated, settings, monkeypatch, _MANAGER)
    app_id = await _antrag(maker, seed)
    async with maker() as session:
        buyer = PrincipalRow(sub="anna-sub", display_name="Anna")
        session.add(buyer)
        await session.commit()
    order = api.post(
        f"/api/applications/{app_id}/orders",
        json={"title": "Regal", "plannedAmount": "60.00", "positionIds": ["p1"]},
    ).json()
    url = f"/api/orders/{order['id']}"
    api.patch(
        url,
        json={
            "version": 1,
            "plannedAmount": "75.00",
            "orderedOn": "2026-11-02",
            "buyerId": str(buyer.id),
            "positionIds": ["p2"],
        },
    )
    api.post(f"{url}/status", json={"status": "delivered", "version": 2})
    change = (await _audit(maker, "order_update"))[0]
    assert change.data["before"] == {
        "plannedAmount": "60.00",
        "orderedOn": None,
        "buyerId": None,
        "positionIds": ["p1"],
    }
    status = (await _audit(maker, "order_status"))[0]
    assert status.data["before"]["status"] == "planned"

    async with maker() as session:
        await RevertService(session).revert(status.id, "revert-sub", _MANAGER)
        await RevertService(session).revert(change.id, "revert-sub", _MANAGER)
        await session.commit()
    reverted = api.get(url).json()
    assert (
        reverted["status"],
        reverted["plannedAmount"],
        reverted["orderedOn"],
        reverted["buyerId"],
        reverted["positionIds"],
        reverted["version"],
    ) == ("planned", "60.00", None, None, ["p1"], 5)

    async with maker() as session:
        with pytest.raises(ConflictError) as stale:
            await RevertService(session).revert(change.id, "revert-sub", _MANAGER)
        assert stale.value.code == "stale_revert"
        created = (await _audit(maker, "order_create"))[0]
        with pytest.raises(ConflictError):
            await RevertService(session).revert(created.id, "revert-sub", _MANAGER)
    api.delete(url)
    async with maker() as session:
        with pytest.raises(ConflictError) as gone:
            await RevertService(session).revert(status.id, "revert-sub", _MANAGER)
        assert gone.value.code == "order_gone"


async def test_a_bestellung_has_files_of_its_own(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 002871: upload, list, download and delete; the Antrag does not show the files."""
    storage = MemoryStorage()
    api = _client(migrated, settings, monkeypatch, _MANAGER, storage=storage)
    app_id = await _antrag(maker, seed)
    order = api.post(f"/api/applications/{app_id}/orders", json={"title": "Regal"}).json()
    files = f"/api/orders/{order['id']}/attachments"

    up = api.post(files, files={"file": ("Rechnung.pdf", _PDF, "application/pdf")})
    assert up.status_code == 201, up.text
    first = up.json()
    assert (first["filename"], first["scanned"]) == ("Rechnung.pdf", False)
    second = api.post(files, files={"file": ("Beleg.pdf", _PDF, "application/pdf")}).json()
    assert api.post(files, files={"file": ("leer.pdf", b"", "application/pdf")}).status_code == 415
    assert [a["id"] for a in api.get(files).json()] == [first["id"], second["id"]]
    assert api.get(f"/api/applications/{app_id}/attachments").json() == []
    assert api.get(f"/api/attachments/{first['id']}").status_code == 409
    assert api.delete(f"/api/attachments/{first['id']}").status_code == 404
    assert len(storage.blobs) == 2

    async with maker() as session:
        await session.execute(update(Attachment).values(scanned=True, scan_result="clean"))
        await session.commit()
    down = api.get(f"/api/attachments/{first['id']}/download")
    assert (down.status_code, down.content) == (200, _PDF)

    reader = _client(migrated, settings, monkeypatch, _READER, storage=storage)
    assert len(reader.get(files).json()) == 2
    assert reader.get(f"/api/attachments/{first['id']}").status_code == 200
    assert reader.post(files, files={"file": ("x.pdf", _PDF)}).status_code == 403
    assert reader.delete(f"{files}/{first['id']}").status_code == 403
    for stranger in (
        _client(migrated, settings, monkeypatch, _BLIND, storage=storage),
        _client(
            migrated,
            settings,
            monkeypatch,
            None,
            Applicant(application_id=str(app_id)),
            storage=storage,
        ),
    ):
        assert stranger.get(files).status_code in (401, 404)
        assert stranger.get(f"/api/attachments/{first['id']}").status_code == 404
        assert stranger.get(f"/api/attachments/{first['id']}/download").status_code == 404

    assert api.delete(f"{files}/{first['id']}").status_code == 204
    assert api.delete(f"{files}/{first['id']}").status_code == 404
    assert [a["id"] for a in api.get(files).json()] == [second["id"]]
    assert len(storage.blobs) == 1
    assert api.delete(f"/api/orders/{order['id']}").status_code == 204
    assert storage.blobs == {}
    assert api.get(f"/api/attachments/{second['id']}").status_code == 404
    async with maker() as session:
        assert await session.scalar(select(func.count()).select_from(Attachment)) == 0
    assert len(await _audit(maker, "attachment_upload")) == 2
    assert len(await _audit(maker, "attachment_delete")) == 2


async def test_the_buyer_follows_the_privacy_rules(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 002892: export, merge and erasure of the buyer; the anonymized Antrag keeps its rows."""
    api = _client(migrated, settings, monkeypatch, _MANAGER)
    app_id = await _antrag(maker, seed)
    async with maker() as session:
        old = PrincipalRow(sub="anna-old", display_name="Anna", email="anna@example.org")
        new = PrincipalRow(sub="anna-new", display_name="Anna B.", email="anna.b@example.org")
        session.add_all([old, new, PrincipalRow(sub="merge-admin", display_name="Admin")])
        await session.commit()
    base = f"/api/applications/{app_id}/orders"
    bought = api.post(
        base, json={"title": "Regal", "kind": "outlay", "buyerId": str(old.id)}
    ).json()
    typed = api.post(
        base, json={"title": "Drucker", "kind": "outlay", "buyerName": "Ben Typed"}
    ).json()

    async with maker() as session:
        assert (await AuskunftService(session).collect("nobody@example.org"))["orders"] == []
        exported = (await AuskunftService(session).collect("anna@example.org"))["orders"]
    assert [(o["number"], o["title"], o["kind"]) for o in exported] == [
        (bought["number"], "Regal", "outlay")
    ]

    async with maker() as session:
        await PrincipalMergeService(session).merge(old.id, new.id, actor="merge-admin")
    moved = api.get(f"/api/orders/{bought['id']}").json()
    assert (moved["buyerId"], moved["buyerLabel"]) == (str(new.id), "Anna B.")
    assert typed["buyerLabel"] == "Ben Typed"
    async with maker() as session:
        assert len((await AuskunftService(session).collect("anna.b@example.org"))["orders"]) == 1

    async with maker() as session:
        await PrincipalService(session).erase(new.id, actor="merge-admin")
    assert api.get(f"/api/orders/{bought['id']}").json()["buyerId"] is None

    async with maker() as session:
        await ApplicationsService(session).anonymize(app_id, commit=False)
        await clear_buyer_names(session, app_id)
        await session.commit()
    listed = api.get(base).json()["items"]
    assert [(o["title"], o["buyerId"], o["buyerName"]) for o in listed] == [
        ("Regal", None, None),
        ("Drucker", None, None),
    ]
    assert typed["buyerName"] == "Ben Typed"


async def _invoice(maker: async_sessionmaker[AsyncSession], gross: str) -> uuid.UUID:
    """Create an open invoice with the gross amount."""
    async with maker() as session:
        row = Invoice(number="R-2026-17", supplier="Möbelhaus", gross_amount=Decimal(gross))
        session.add(row)
        await session.commit()
        return row.id


async def _cost_centre(maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID) -> uuid.UUID:
    """Give the Antrag a Kostenstelle and an open Haushaltsjahr; return the Kostenstelle."""
    key = f"KS{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        budget = Budget(key=key, path_key=key, name="Ausstattung")
        session.add(budget)
        await session.flush()
        year = FiscalYear(
            budget_id=budget.id,
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        session.add(year)
        await session.flush()
        await session.execute(
            update(Application)
            .where(Application.id == app_id)
            .values(budget_id=budget.id, fiscal_year_id=year.id)
        )
        await session.commit()
        return budget.id


async def test_the_invoice_of_a_bestellung(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 002873 + § 002874 + § 002877: set, real price, list, revert, delete of the invoice."""
    api = _client(migrated, settings, monkeypatch, _FINANCE)
    app_id = await _antrag(maker, seed)
    base = f"/api/applications/{app_id}/orders"
    regal = api.post(base, json={"title": "Regal", "plannedAmount": "60.00"}).json()
    stuhl = api.post(base, json={"title": "Stuhl", "plannedAmount": "20.00"}).json()
    assert (regal["invoiceId"], regal["invoiceStatus"], regal["bookedAmount"]) == (None, None, "0")
    assert regal["applicationTitle"] == "Büroausstattung"
    invoice_id = str(await _invoice(maker, "72.50"))
    put = f"/api/orders/{regal['id']}/invoice"

    no_read = _client(migrated, settings, monkeypatch, _MANAGER)
    assert no_read.put(put, json={"invoiceId": invoice_id, "version": 1}).status_code == 403
    unknown = api.put(put, json={"invoiceId": str(uuid.uuid4()), "version": 1})
    assert unknown.status_code == 404
    old = api.put(put, json={"invoiceId": invoice_id, "version": 7})
    assert (old.status_code, old.json()["code"]) == (409, "order_version_conflict")

    first = api.put(put, json={"invoiceId": invoice_id, "version": 1}).json()
    assert (
        first["invoiceId"],
        first["invoiceNumber"],
        first["invoiceStatus"],
        first["actualAmount"],
        first["version"],
    ) == (invoice_id, "R-2026-17", "open", "72.50", 2)
    linked = (await _audit(maker, "order_update"))[-1]
    assert linked.data["before"] == {"invoiceId": None, "actualAmount": None}
    async with maker() as session:
        await RevertService(session).revert(linked.id, "revert-sub", _FINANCE)
        await session.commit()
    undone = api.get(f"/api/orders/{regal['id']}").json()
    assert (undone["invoiceId"], undone["actualAmount"], undone["version"]) == (None, None, 3)

    api.put(put, json={"invoiceId": invoice_id, "version": 3})
    second = api.put(
        f"/api/orders/{stuhl['id']}/invoice", json={"invoiceId": invoice_id, "version": 1}
    ).json()
    assert (second["invoiceId"], second["actualAmount"]) == (invoice_id, None)

    of_invoice = api.get(f"/api/invoices/{invoice_id}/orders").json()
    assert of_invoice["total"] == "72.50"
    assert [
        (item["accessible"], item["number"], item["title"], item["actualAmount"])
        for item in of_invoice["items"]
    ] == [(True, regal["number"], "Regal", "72.50"), (True, stuhl["number"], "Stuhl", None)]
    assert of_invoice["items"][0]["applicationTitle"] == "Büroausstattung"
    ledger = _client(migrated, settings, monkeypatch, _LEDGER)
    hidden = ledger.get(f"/api/invoices/{invoice_id}/orders").json()
    assert hidden == {
        "items": [
            {
                "accessible": False,
                "id": None,
                "number": None,
                "title": None,
                "applicationId": None,
                "applicationTitle": None,
                "actualAmount": None,
            }
        ]
        * 2,
        "total": "72.50",
    }
    assert no_read.get(f"/api/invoices/{invoice_id}/orders").status_code == 403
    assert api.get(f"/api/invoices/{uuid.uuid4()}/orders").status_code == 404

    removed = api.put(put, json={"invoiceId": None, "version": 4}).json()
    assert (removed["invoiceId"], removed["invoiceStatus"], removed["actualAmount"]) == (
        None,
        None,
        "72.50",
    )
    removal = (await _audit(maker, "order_update"))[-1]
    again = api.put(put, json={"invoiceId": invoice_id, "version": 5}).json()
    assert (again["invoiceId"], again["actualAmount"]) == (invoice_id, "72.50")
    assert api.delete(f"/api/invoices/{invoice_id}").status_code == 204
    assert [item["invoiceId"] for item in api.get(base).json()["items"]] == [None, None]
    async with maker() as session:
        with pytest.raises(ConflictError) as gone:
            await RevertService(session).revert(removal.id, "revert-sub", _FINANCE)
        assert gone.value.code == "not_revertable"


async def test_a_booking_names_a_bestellung(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 002878 + § 002880 + § 002881: bookings, the marks, the refused delete, the cancel."""
    api = _client(migrated, settings, monkeypatch, _FINANCE)
    app_id = await _antrag(maker, seed)
    other_id = await _antrag(maker, seed)
    budget_id = await _cost_centre(maker, app_id)
    await _cost_centre(maker, other_id)
    regal = api.post(
        f"/api/applications/{app_id}/orders", json={"title": "Regal", "plannedAmount": "60.00"}
    ).json()
    url = f"/api/orders/{regal['id']}"
    invoice_id = str(await _invoice(maker, "60.00"))
    api.put(f"{url}/invoice", json={"invoiceId": invoice_id, "version": 1})

    def book(amount: str, **extra: object) -> Any:
        body = {"amount": amount, "description": "Regal", "orderId": regal["id"], **extra}
        return api.post("/api/expenses", json=body)

    deposit = book("20.00", applicationId=str(app_id))
    assert (deposit.status_code, deposit.json()["orderId"]) == (201, regal["id"])
    rest = book("40.00", applicationId=str(app_id), invoiceId=invoice_id)
    assert rest.status_code == 201
    marked = api.get(url).json()
    assert (marked["bookedAmount"], marked["invoiceStatus"]) == ("60.00", "paid")

    for refused in (
        book("5.00", applicationId=str(other_id)),
        book("5.00", budgetId=str(budget_id)),
    ):
        assert (refused.status_code, refused.json()["code"]) == (
            422,
            "order_application_mismatch",
        )
    assert book("5.00", kind="income", budgetId=str(budget_id)).status_code == 422
    missing = api.post(
        "/api/expenses",
        json={
            "amount": "5.00",
            "description": "x",
            "applicationId": str(app_id),
            "orderId": str(uuid.uuid4()),
        },
    )
    assert missing.status_code == 404

    kept = api.delete(url)
    assert (kept.status_code, kept.json()["code"]) == (409, "order_has_bookings")
    cancelled = api.post(f"{url}/status", json={"status": "cancelled", "version": 2}).json()
    assert (cancelled["status"], cancelled["bookedAmount"]) == ("cancelled", "60.00")

    booked = (await _audit(maker, "budget_expense_create"))[-2]
    assert booked.data["orderId"] == regal["id"]
    async with maker() as session:
        await RevertService(session).revert(booked.id, "revert-sub", _FINANCE)
        await session.commit()
    assert api.get(url).json()["bookedAmount"] == "40.00"
    assert api.delete(f"/api/budget-expenses/{rest.json()['id']}").status_code == 204
    assert Decimal(api.get(url).json()["bookedAmount"]) == 0
    assert api.delete(url).status_code == 204

    again = api.post(
        f"/api/applications/{app_id}/orders", json={"title": "Drucker", "plannedAmount": "9.00"}
    ).json()
    paid = api.post(
        "/api/expenses",
        json={
            "amount": "9.00",
            "description": "Drucker",
            "applicationId": str(app_id),
            "orderId": again["id"],
        },
    ).json()
    async with maker() as session:
        await ApplicationsService(session).delete(app_id, actor="finance-sub")
    async with maker() as session:
        left = await session.get(BudgetExpense, uuid.UUID(paid["id"]))
        assert left is not None
        assert (left.order_id, left.application_id) == (None, None)
