"""Integration: a card gives read access to its links (spec 000487).

A board reader without ``budget.read`` and without application rights reads the linked
Buchung and the linked Antrag through the card, read only and without the PII fields.
The access does not continue to the links of a linked card, and the person links only
what the person can read by the rule of the kind.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from app.modules.forms.models import FormField
from tests.integration.modules.todos.conftest import Api, add_gremium, add_member, add_person
from tests.integration.modules.todos.test_todos_events import _money

pytestmark = pytest.mark.integration


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


async def _form_answers(maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID) -> None:
    """Give the Antrag a plain answer, a PII answer and an IBAN without the PII flag."""
    async with maker() as session:
        app = await session.get(Application, app_id)
        assert app is not None
        session.add_all(
            [
                FormField(
                    form_version_id=app.form_version_id,
                    key="zweck",
                    type="text",
                    label_i18n={"de": "Zweck"},
                    order=1,
                ),
                FormField(
                    form_version_id=app.form_version_id,
                    key="name",
                    type="text",
                    label_i18n={"de": "Name"},
                    order=2,
                    is_pii=True,
                ),
                FormField(
                    form_version_id=app.form_version_id,
                    key="konto",
                    type="iban",
                    label_i18n={"de": "IBAN"},
                    order=3,
                ),
            ]
        )
        app.data = {**app.data, "zweck": "Party", "name": "Ada Lovelace", "konto": "DE00"}
        await session.commit()


async def test_board_reader_reads_linked_booking_without_budget_read(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Spec 000487: the grant, its limits and the link check."""
    ids = await _money(maker)
    await _form_answers(maker, ids["app"])
    gid, board = await add_gremium(maker, "Kultur")
    _hid, hidden_board = await add_gremium(maker, "AStA")
    admin, _aid = await add_person(maker, "Admin")
    reader, rid = await add_person(maker, "Ada")
    await add_member(maker, gid, rid, "todo.write")

    api.login(Principal(sub=admin.sub, roles=["admin"], permissions=set()))
    with TestClient(api.app) as client:
        secret = _ok(
            client.post(
                "/api/todos/cards",
                json={
                    "boardId": str(hidden_board),
                    "title": "Intern",
                    "links": [{"kind": "expense", "targetId": str(ids["income"])}],
                },
            ),
            201,
        )
        party = _ok(
            client.post(
                "/api/todos/cards",
                json={
                    "boardId": str(board),
                    "title": "Erstiparty",
                    "links": [
                        {"kind": "expense", "targetId": str(ids["parent"])},
                        {"kind": "application", "targetId": str(ids["app"])},
                        {"kind": "todo", "targetId": secret["id"]},
                    ],
                },
            ),
            201,
        )

    api.login(reader)
    with TestClient(api.app) as client:
        card = _ok(client.get(f"/api/todos/cards/{party['id']}"))
        links = {link["kind"]: link for link in card["links"]}
        booking = links["expense"]
        assert booking["accessible"] and booking["granted"]
        assert booking["url"] is None
        assert booking["title"] == "Buchung 300.00"
        assert links["application"]["granted"] and links["todo"]["granted"]

        view = _ok(client.get(f"/api/todos/cards/{party['id']}/links/{booking['id']}/view"))
        facts = {f["key"]: f["value"] for f in view["facts"]}
        assert view["kind"] == "expense" and facts["amount"] == "300.00"

        app_view = _ok(
            client.get(
                f"/api/todos/cards/{party['id']}/links/{links['application']['id']}/view"
            )
        )
        answers = {f["key"]: f["value"] for f in app_view["facts"]}
        assert answers["zweck"] == "Party" and answers["amount"] == "800.00"
        assert "name" not in answers and "konto" not in answers

        card_view = _ok(
            client.get(f"/api/todos/cards/{party['id']}/links/{links['todo']['id']}/view")
        )
        assert card_view["title"] == "Intern"
        assert "links" not in card_view

        assert client.get(f"/api/todos/cards/{secret['id']}").status_code == 404
        assert client.get("/api/expenses").status_code == 403
        other = _ok(
            client.post("/api/todos/cards", json={"boardId": str(board), "title": "Plakate"}),
            201,
        )
        refused = client.post(
            f"/api/todos/cards/{other['id']}/links",
            json={"kind": "expense", "targetId": str(ids["parent"])},
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "link_target_not_found"
        stranger = client.get(
            f"/api/todos/cards/{other['id']}/links/{booking['id']}/view"
        )
        assert stranger.status_code == 404
