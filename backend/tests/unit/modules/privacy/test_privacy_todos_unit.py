"""The to-do part of the privacy module: the erasure and the Art. 15 export."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from io import BytesIO
from typing import Any

import pytest
from openpyxl import load_workbook

from app.modules.auth.models import Principal
from app.modules.privacy import service as privacy_service
from app.modules.privacy.models import ErasureRequest
from app.modules.privacy.service import (
    AuskunftService,
    ErasureRequestService,
    PrincipalService,
    build_auskunft_workbook,
)
from tests._support.privacy_fakes import fake_session, result

_AT = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(*_a: object, **_k: object) -> list[object]:
        return []

    async def _synced(*_a: object, **_k: object) -> bool:
        return True

    monkeypatch.setattr(privacy_service, "erase_candidacies", _none)
    monkeypatch.setattr(privacy_service, "erase_candidate_names", _none)
    monkeypatch.setattr(privacy_service, "sync_principal_memberships", _synced)


async def test_the_erasure_removes_the_todo_data(monkeypatch: pytest.MonkeyPatch) -> None:
    erased: list[uuid.UUID] = []

    async def _erase(_s: Any, principal_id: uuid.UUID, **kw: Any) -> list[str]:
        erased.append(principal_id)
        assert kw == {"files": None, "actor": "admin"}
        return ["k1"]

    monkeypatch.setattr(privacy_service, "erase_todos", _erase)
    principal = Principal(id=uuid.uuid4(), sub="kc", email="u@x.org", active=True)
    service = PrincipalService(fake_session(gets=[principal]))
    await service.erase(principal.id, actor="admin", commit=False)
    assert erased == [principal.id]
    # Without a commit the keys wait for the caller.
    assert service.storage_keys == ["k1"]


class _Files:
    """Records the committed count of the session at each object removal."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.removed: list[tuple[list[str], int]] = []

    async def remove_objects(self, keys: list[str]) -> None:
        self.removed.append((list(keys), self.session.committed))


def _keys(monkeypatch: pytest.MonkeyPatch, keys: list[str]) -> None:
    async def _erase(*_a: object, **_k: object) -> list[str]:
        return keys

    async def _tickets(*_a: object, **_k: object) -> int:
        return 0

    monkeypatch.setattr(privacy_service, "erase_todos", _erase)
    monkeypatch.setattr(privacy_service, "anonymize_reported_tickets", _tickets)


async def test_the_erasure_removes_the_comment_objects_after_its_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _keys(monkeypatch, ["k1", "k2"])
    principal = Principal(id=uuid.uuid4(), sub="kc", email="u@x.org", active=True)
    db = fake_session(gets=[principal])
    files = _Files(db)
    service = PrincipalService(db)
    await service.erase(principal.id, actor="admin", files=files)  # type: ignore[arg-type]
    assert files.removed == [(["k1", "k2"], 1)]
    assert service.storage_keys == []


async def test_the_erasure_without_files_removes_no_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _keys(monkeypatch, ["k1"])
    principal = Principal(id=uuid.uuid4(), sub="kc", email="u@x.org", active=True)
    db = fake_session(gets=[principal])
    await PrincipalService(db).erase(principal.id, actor="admin")
    assert db.committed == 1


async def test_the_request_removes_the_comment_objects_after_its_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _keys(monkeypatch, ["k1"])
    principal = Principal(id=uuid.uuid4(), sub="kc", email="u@x.org", active=True)
    request = ErasureRequest(
        id=uuid.uuid4(),
        subject_type="principal",
        principal_id=principal.id,
        email="u@x.org",
        status="open",
    )
    db = fake_session(gets=[request, principal])
    files = _Files(db)
    await ErasureRequestService(db).execute(request.id, actor="dpo", files=files)  # type: ignore[arg-type]
    # The erasure itself does not commit; the request commits once, then the objects go.
    assert files.removed == [(["k1"], 1)]
    assert db.committed == 1


async def test_the_export_asks_for_the_todos_of_the_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[list[uuid.UUID]] = []

    async def _export(_s: Any, ids: list[uuid.UUID]) -> dict[str, Any]:
        asked.append(ids)
        return {"cards": [{"title": "A"}], "comments": [{"body": "B"}]}

    monkeypatch.setattr(privacy_service, "todo_export", _export)
    principal = Principal(id=uuid.uuid4(), sub="kc", email="x@example.org", active=True)
    db = fake_session(scalars=[result(), result()], scalar=[principal])
    data = await AuskunftService(db).collect("x@example.org")
    assert asked == [[principal.id]]
    assert data["todos"] == [{"title": "A"}] and data["todo_comments"] == [{"body": "B"}]
    anonymous = fake_session(scalars=[result(), result()], scalar=[None])
    await AuskunftService(anonymous).collect("y@example.org")
    assert asked[-1] == []


def test_the_workbook_has_the_todo_sheets() -> None:
    raw = build_auskunft_workbook(
        email="x@example.org",
        applications=[],
        versions=[],
        principal=None,
        todos=[
            {
                "board": "StuPa",
                "title": "=1+1",
                "column": "Offen",
                "dueDate": date(2026, 11, 1),
                "createdAt": _AT,
                "description": "Raum buchen",
            },
            {"board": None, "title": None, "column": None, "dueDate": None, "createdAt": None},
        ],
        todo_comments=[
            {
                "card": "A",
                "body": "Hi",
                "createdAt": _AT,
                "deletedAt": _AT,
                "attachments": ["a.pdf", "b.png"],
            },
            {"card": None, "body": None, "createdAt": None, "deletedAt": None},
        ],
    )
    book = load_workbook(BytesIO(raw))
    cards = [[c.value for c in row] for row in book["To-Dos"].iter_rows()]
    assert cards[0] == ["Board", "Titel", "Spalte", "Fällig", "Erstellt", "Beschreibung"]
    assert cards[1][0] == "StuPa" and cards[1][3] == "2026-11-01"
    assert cards[1][5] == "Raum buchen"
    assert not str(cards[1][1]).startswith("=")
    assert cards[2] == [None] * 6
    comments = [[c.value for c in row] for row in book["To-Do-Kommentare"].iter_rows()]
    assert comments[0] == ["To-Do", "Zeitpunkt", "Gelöscht", "Text", "Anhänge"]
    assert comments[1] == ["A", "2026-06-16 12:00", "2026-06-16 12:00", "Hi", "a.pdf; b.png"]
