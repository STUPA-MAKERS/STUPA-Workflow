"""Unit tests of the ticket part of the privacy module (no database).

The erasure of an account anonymizes the tickets that it reported. The Art. 15
export lists the tickets that an address reported, as an account or as a bare
e-mail, in its own sheet.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import pytest
from openpyxl import load_workbook

from app.modules.auth.models import Principal
from app.modules.privacy import service as privacy_service
from app.modules.privacy.service import (
    AuskunftService,
    PrincipalService,
    build_auskunft_workbook,
)
from app.modules.tickets.models import Ticket
from tests._support.privacy_fakes import fake_session, result
from tests.unit.modules.tickets.fakes import FakeFiles

_AT = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


def _ticket(**kw: Any) -> Ticket:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "number": 3,
        "kind": "bug",
        "title": "Kaputt",
        "body": "b",
        "status": "done",
        "reporter_principal_id": None,
        "reporter_email": None,
        "context": {"url": "u"},
        "anonymized_at": None,
        "created_at": _AT,
    }
    base.update(kw)
    return Ticket(**base)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(*_a: object, **_k: object) -> list[object]:
        return []

    async def _synced(*_a: object, **_k: object) -> bool:
        return True

    monkeypatch.setattr(privacy_service, "erase_candidacies", _none)
    monkeypatch.setattr(privacy_service, "erase_candidate_names", _none)
    monkeypatch.setattr(privacy_service, "sync_principal_memberships", _synced)


async def test_the_erasure_anonymizes_the_reported_tickets() -> None:
    principal = Principal(id=uuid.uuid4(), sub="kc", email="u@x.org", active=True)
    ticket = _ticket(reporter_principal_id=principal.id)
    db = fake_session(gets=[principal], scalars=[result(ticket)])
    files = FakeFiles()
    await PrincipalService(db).erase(
        principal.id,
        actor="admin",
        commit=False,
        files=files,  # type: ignore[arg-type]
    )
    assert ticket.reporter_principal_id is None
    assert ticket.context == {}
    assert ticket.anonymized_at is not None
    assert files.deleted == [(ticket.id, "admin")]


async def test_the_erasure_without_tickets_builds_its_own_files_service() -> None:
    principal = Principal(id=uuid.uuid4(), sub="kc", email="u@x.org", active=True)
    db = fake_session(gets=[principal])
    out = await PrincipalService(db).erase(principal.id, actor="admin", commit=False)
    assert out.active is False


async def test_the_export_lists_the_tickets_of_the_address() -> None:
    mine = _ticket(reporter_email="x@example.org")
    db = fake_session(scalars=[result(), result(mine)], scalar=[None])
    data = await AuskunftService(db).collect("x@example.org")
    assert data["tickets"] == [
        {"number": "T-0003", "title": "Kaputt", "status": "done", "createdAt": _AT}
    ]


async def test_the_export_lists_the_tickets_of_the_account() -> None:
    principal = Principal(id=uuid.uuid4(), sub="kc", email="x@example.org", active=True)
    ticket = _ticket(reporter_principal_id=principal.id, number=12)
    db = fake_session(scalars=[result(), result(ticket)], scalar=[principal])
    data = await AuskunftService(db).collect("x@example.org")
    assert [t["number"] for t in data["tickets"]] == ["T-0012"]


def test_the_workbook_has_a_ticket_sheet() -> None:
    raw = build_auskunft_workbook(
        email="x@example.org",
        applications=[],
        versions=[],
        principal=None,
        tickets=[
            {"number": "T-0001", "title": "=HYPERLINK()", "status": "new", "createdAt": _AT},
            {"number": None, "title": None, "status": None, "createdAt": None},
        ],
    )
    sheet = load_workbook(BytesIO(raw))["Tickets"]
    rows = [[c.value for c in row] for row in sheet.iter_rows()]
    assert rows[0] == ["Nummer", "Titel", "Status", "Gemeldet"]
    assert rows[1][0] == "T-0001"
    assert not str(rows[1][1]).startswith("=")
    assert rows[2][:3] == [None, None, None]


def test_the_erase_route_passes_the_object_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """The direct erasure removes the ticket attachment objects too."""
    from collections.abc import Iterator

    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.deps import get_current_principal
    from app.main import create_app
    from app.modules.auth.principal import Principal as SessionPrincipal

    seen: dict[str, Any] = {}

    async def _erase(_self: object, principal_id: uuid.UUID, **kw: Any) -> None:
        seen.update(kw, principal_id=principal_id)

    monkeypatch.setattr(PrincipalService, "erase", _erase)
    app = create_app()
    storage = object()
    app.state.object_storage = storage

    def _session() -> Iterator[object]:
        yield object()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_principal] = lambda: SessionPrincipal(
        sub="admin", permissions={"privacy.manage"}
    )
    target = uuid.uuid4()
    with TestClient(app) as client:
        app.state.object_storage = storage
        resp = client.post(f"/api/admin/privacy/principals/{target}/erase")
    assert resp.status_code == 204
    assert seen["principal_id"] == target
    assert seen["actor"] == "admin"
    assert seen["files"].storage is storage
