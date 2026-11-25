"""The status lists on a real Postgres: the read, the admin save and its revert.

§ F/administration/admin/003035 the list and its gate, § 003036 the phases, § 003038 the
delete of a status in use, § 003039 the lists that the migration creates.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.service.statuses import StatusListAdmin
from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.config_revision.revert import RevertService
from app.modules.flow.models import FlowVersion, Transition
from app.modules.orders.models import PurchaseOrder
from app.modules.statuses.schemas import StatusIn
from app.settings import Settings
from tests._support.guest_apps import GuestSeed
from tests.integration.modules.orders.test_orders import (
    _client,
    maker,  # noqa: F401
    seed,  # noqa: F401
    settings,  # noqa: F401
)

pytestmark = pytest.mark.integration

_ADMIN = Principal(
    sub="status-admin", roles=[], permissions={"admin.order_phases", "admin.event_phases"}
)
_ORDER_ADMIN = Principal(sub="order-admin", roles=[], permissions={"admin.order_phases"})
_BUYER = Principal(sub="status-buyer", roles=["member"], permissions={"order.manage"})
_MEMBER = Principal(sub="status-member", roles=["member"], permissions=set())

_ORDER_LIST = [
    ("planned", "open", True, None),
    ("ordered", "open", False, "orderedOn"),
    ("delivered", "done", False, "deliveredOn"),
    ("cancelled", "void", False, None),
]


def _shape(body: dict[str, Any]) -> list[tuple[str, str, bool, str | None]]:
    return [(s["key"], s["phase"], s["start"], s.get("setsDate")) for s in body["statuses"]]


def _body(statuses: list[dict[str, Any]], **replacements: str) -> dict[str, Any]:
    return {"statuses": statuses, "replacements": replacements}


def _plain(body: dict[str, Any]) -> list[dict[str, Any]]:
    """The statuses of a read as the admin sends them back."""
    return [{k: v for k, v in s.items() if k != "used"} for s in body["statuses"]]


async def _restore(maker: async_sessionmaker[AsyncSession], kind: str, saved: Any) -> None:  # noqa: F811
    async with maker() as session:
        await StatusListAdmin(session).restore(
            kind,
            [StatusIn.model_validate(s) for s in saved],
            "test",
            action=AuditAction.CONFIG_CHANGE,
            extra_data=None,
        )
        await session.commit()


async def test_the_migration_creates_both_lists(
    migrated: tuple[str, str],
    settings: Settings,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 003039: the four statuses of the Bestellungen and the three of the Events."""
    member = _client(migrated, settings, monkeypatch, _MEMBER)
    orders = member.get("/api/statuses/order")
    assert orders.status_code == 200, orders.text
    assert _shape(orders.json()) == _ORDER_LIST
    assert orders.json()["statuses"][3]["name"] == {"de": "Storniert", "en": "Cancelled"}
    assert _shape(member.get("/api/statuses/event").json()) == [
        ("planned", "open", True, None),
        ("settled", "done", False, None),
        ("cancelled", "void", False, None),
    ]
    assert member.get("/api/statuses/other").status_code == 422
    assert member.get("/api/admin/statuses/order").status_code == 403
    order_admin = _client(migrated, settings, monkeypatch, _ORDER_ADMIN)
    assert order_admin.get("/api/admin/statuses/order").status_code == 200
    assert order_admin.get("/api/admin/statuses/event").status_code == 403
    anonymous = _client(migrated, settings, monkeypatch, None)
    assert _shape(anonymous.get("/api/statuses/order").json()) == _ORDER_LIST


async def test_admin_saves_a_list_and_refuses_a_wrong_one(
    migrated: tuple[str, str],
    settings: Settings,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """§ 003035: a save replaces the list in its order and writes a revertable revision."""
    admin = _client(migrated, settings, monkeypatch, _ADMIN)
    saved = _plain(admin.get("/api/admin/statuses/event").json())
    try:
        changed = [
            {**saved[0], "name": {"de": "Kommt", "en": "Upcoming"}, "tone": "accent"},
            {"key": "running", "name": {"de": "Läuft"}, "phase": "open", "tone": "warn"},
            *saved[1:],
        ]
        put = admin.put("/api/admin/statuses/event", json=_body(changed))
        assert put.status_code == 200, put.text
        assert [s["key"] for s in put.json()["statuses"]] == [
            "planned",
            "running",
            "settled",
            "cancelled",
        ]
        assert put.json()["statuses"][0]["tone"] == "accent"

        no_start = [{**s, "start": False} for s in changed]
        wrong = admin.put("/api/admin/statuses/event", json=_body(no_start))
        assert (wrong.status_code, wrong.json()["code"]) == (422, "status_list_invalid")
        dated = [{**changed[0], "setsDate": "orderedOn"}, *changed[1:]]
        wrong = admin.put("/api/admin/statuses/event", json=_body(dated))
        assert (wrong.status_code, wrong.json()["code"]) == (422, "status_list_invalid")

        async with maker() as session:
            entry = (
                await session.scalars(
                    select(AuditEntry)
                    .where(AuditEntry.action == AuditAction.CONFIG_CHANGE)
                    .order_by(AuditEntry.id.desc())
                    .limit(1)
                )
            ).one()
            assert (entry.data or {}).get("revisionId")
            await RevertService(session).revert(entry.id, "status-admin", _ADMIN)
            await session.commit()
        assert _plain(admin.get("/api/admin/statuses/event").json()) == saved
    finally:
        await _restore(maker, "event", saved)


async def test_a_removed_status_in_use_needs_a_replacement(
    migrated: tuple[str, str],
    settings: Settings,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
    seed: GuestSeed,  # noqa: F811
) -> None:
    """§ 003038: 409 without a replacement; with one the Bestellungen move to it."""
    admin = _client(migrated, settings, monkeypatch, _ADMIN)
    buyer = _client(migrated, settings, monkeypatch, _BUYER)
    saved = _plain(admin.get("/api/admin/statuses/order").json())
    made = buyer.post("/api/orders", json={"title": "Zelt", "status": "cancelled"})
    assert made.status_code == 201, made.text
    assert made.json()["status"] == "cancelled"
    unknown = buyer.post("/api/orders", json={"title": "Zelt", "status": "lost"})
    assert (unknown.status_code, unknown.json()["code"]) == (422, "status_unknown")
    try:
        used = admin.get("/api/admin/statuses/order").json()["statuses"]
        assert next(s["used"] for s in used if s["key"] == "cancelled") >= 1
        gone = {"key": "gone", "name": {"de": "Verworfen"}, "phase": "void", "tone": "muted"}
        without = [*saved[:3], gone]
        refused = admin.put("/api/admin/statuses/order", json=_body(without))
        assert (refused.status_code, refused.json()["code"]) == (409, "status_in_use")
        moved = admin.put("/api/admin/statuses/order", json=_body(without, cancelled="gone"))
        assert moved.status_code == 200, moved.text
        assert buyer.get(f"/api/orders/{made.json()['id']}").json()["status"] == "gone"
        fresh = buyer.post("/api/orders", json={"title": "Bank"}).json()
        assert fresh["status"] == "planned"
        async with maker() as session:
            row = await session.get(PurchaseOrder, made.json()["id"])
            assert row is not None
            assert row.status == "gone"
    finally:
        async with maker() as session:
            back = update(PurchaseOrder).where(PurchaseOrder.status == "gone")
            await session.execute(back.values(status="cancelled"))
            await session.commit()
        await _restore(maker, "order", saved)


async def test_a_status_that_the_flow_names_stays(
    migrated: tuple[str, str],
    settings: Settings,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
    seed: GuestSeed,  # noqa: F811
) -> None:
    """§ 003038: 409 ``status_in_flow`` while a transition offers itself on the status."""
    admin = _client(migrated, settings, monkeypatch, _ADMIN)
    saved = _plain(admin.get("/api/admin/statuses/order").json())
    async with maker() as session:
        transition_id = await session.scalar(
            select(Transition.id)
            .join(FlowVersion, FlowVersion.id == Transition.flow_version_id)
            .where(FlowVersion.active)
            .limit(1)
        )
        if transition_id is None:
            pytest.skip("the seed has no active flow")
        await session.execute(
            update(Transition)
            .where(Transition.id == transition_id)
            .values(offer_on_order_status="delivered")
        )
        await session.commit()
    try:
        merged = [saved[0], saved[1], {**saved[3]}, {**saved[2], "key": "arrived"}]
        refused = admin.put("/api/admin/statuses/order", json=_body(merged))
        assert (refused.status_code, refused.json()["code"]) == (409, "status_in_flow")
    finally:
        async with maker() as session:
            await session.execute(
                update(Transition)
                .where(Transition.id == transition_id)
                .values(offer_on_order_status=None)
            )
            await session.commit()
        await _restore(maker, "order", saved)
