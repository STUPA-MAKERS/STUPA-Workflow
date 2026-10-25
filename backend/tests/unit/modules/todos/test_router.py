"""Router tests of the to-do module with a fake service (no database).

They cover every route's wiring and status, the ETag and 304 of the board read,
the scope gate of the link picker, the mail background task and the board pings
after the route.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.todos import live as live_mod
from app.modules.todos import router as router_mod
from app.modules.todos.live import BoardPings
from app.modules.todos.router import (
    _deliver_todo_mails,
    _matches,
    board_etag,
    get_todo_mail_sender,
    get_todo_service,
    mine_boards_etag,
)
from app.modules.todos.schemas import (
    TodoAssignedBoard,
    TodoBoardOut,
    TodoBoardSummary,
    TodoCardDetail,
    TodoCardTile,
    TodoCommentOut,
    TodoLabelOut,
    TodoLinkedCard,
    TodoLinkTarget,
    TodoMember,
    TodoMine,
)
from app.modules.todos.service import TodoMail, TodoService
from app.settings import load_settings
from app.shared.paging import Page
from app.shared.people import PersonRef

NOW = datetime(2026, 10, 1, tzinfo=UTC)
BID = uuid.uuid4()
CID = uuid.uuid4()
XID = uuid.uuid4()
USER = Principal(sub="u")


def _tile() -> TodoCardTile:
    return TodoCardTile(
        id=CID, board_id=BID, column_id=XID, rank="i", title="t", created_at=NOW, updated_at=NOW
    )


def _detail() -> TodoCardDetail:
    return TodoCardDetail(
        **_tile().model_dump(by_alias=False),
        board_name="B",
        board_kind="gremium",
        created_by=PersonRef(),
    )


_COMMENT = TodoCommentOut(id=XID, author=PersonRef(), body="b", at=NOW)
_BOARD = TodoBoardOut(id=BID, name="B", kind="gremium")
_ANSWERS: dict[str, Callable[[], Any]] = {
    "list_boards": lambda: [TodoBoardSummary(id=BID, name="B", kind="gremium")],
    "board": lambda: _BOARD,
    "patch_board": lambda: _BOARD,
    "members": lambda: [TodoMember(principal_id=XID, display_name="Ada")],
    "archive": lambda: Page[TodoCardTile](items=[_tile()], total=1, limit=50, offset=0),
    "add_column": lambda: _BOARD,
    "order_columns": lambda: _BOARD,
    "patch_column": lambda: _BOARD,
    "delete_column": lambda: _BOARD,
    "add_label": lambda: TodoLabelOut(id=XID, name="L", color="red"),
    "patch_label": lambda: TodoLabelOut(id=XID, name="L", color="red"),
    "delete_label": lambda: None,
    "mine": lambda: TodoMine(),
    "mine_boards": lambda: [TodoAssignedBoard(id=BID, name="B", kind="gremium", cards=[_tile()])],
    "all_boards": lambda: [TodoAssignedBoard(id=BID, name="B", kind="personal", cards=[_tile()])],
    "linked": lambda: [
        TodoLinkedCard(
            id=CID, board_id=BID, board_name="B", title="t", column_name="c", is_done=False
        )
    ],
    "create": _detail,
    "card": _detail,
    "tile": _tile,
    "patch": _detail,
    "move": _tile,
    "transfer": _detail,
    "archive_card": lambda: None,
    "restore_card": _detail,
    "add_assignee": _detail,
    "remove_assignee": _detail,
    "add_card_label": _detail,
    "remove_card_label": _detail,
    "add_check_item": _detail,
    "patch_check_item": _detail,
    "delete_check_item": _detail,
    "add_link": _detail,
    "remove_link": _detail,
    "add_comment": lambda: _COMMENT,
    "edit_comment": lambda: _COMMENT,
    "delete_comment": lambda: None,
}


class _Links:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def search(self, q: str, kind: str, _p: Any, *, exclude_card_id: Any) -> Any:
        self.calls.append((q, kind, exclude_card_id))
        return [TodoLinkTarget(kind="ticket", target_id=XID, title="T")]


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.outbox: list[TodoMail] = []
        self.links = _Links()
        self.mail_on: set[str] = set()
        self.pings = BoardPings()
        self.ping_on: set[str] = set()

    def __getattr__(self, name: str) -> Any:
        if name not in _ANSWERS:
            raise AttributeError(name)

        async def _call(*args: Any, **kw: Any) -> Any:
            self.calls.append((name, args, kw))
            if name in self.mail_on:
                self.outbox.append(TodoMail("assigned", CID, (XID,), XID))
            if name in self.ping_on:
                self.pings.touch(BID, CID)
            return _ANSWERS[name]()

        return _call


class _Env:
    def __init__(self, app: FastAPI, service: _FakeService) -> None:
        self.app = app
        self.service = service
        self.sent: list[list[TodoMail]] = []
        self.client = TestClient(app)

    def last(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        return self.service.calls[-1]


@pytest.fixture
def env() -> _Env:
    app = create_app()
    service = _FakeService()
    state = _Env(app, service)

    def _session() -> Iterator[object]:
        yield object()

    async def _send(_settings: object, mails: list[TodoMail], _pool: object) -> None:
        state.sent.append(mails)

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_todo_service] = lambda: service
    app.dependency_overrides[get_todo_mail_sender] = lambda: _send
    app.dependency_overrides[get_current_principal] = lambda: USER
    return state


def test_every_route_needs_a_session() -> None:
    app = create_app()
    app.dependency_overrides[get_current_principal] = lambda: None
    assert TestClient(app).get("/api/todos/boards").status_code == 401


def test_board_routes(env: _Env) -> None:
    c = env.client
    assert c.get(f"/api/todos/boards?gremiumId={BID}").json()[0]["name"] == "B"
    assert env.last()[2] == {"gremium_id": BID}
    assert c.patch(f"/api/todos/boards/{BID}", json={"archiveAfterDays": None}).status_code == 200
    assert c.patch(f"/api/todos/boards/{BID}", json={"archiveAfterDays": 0}).status_code == 422
    assert c.get(f"/api/todos/boards/{BID}/members").json()[0]["displayName"] == "Ada"
    page = c.get(f"/api/todos/boards/{BID}/archive?q=x&limit=10&offset=5")
    assert page.json()["total"] == 1
    assert env.last()[2] == {"q": "x", "limit": 10, "offset": 5}
    assert c.post(f"/api/todos/boards/{BID}/columns", json={"name": "N"}).status_code == 201
    order = c.put(f"/api/todos/boards/{BID}/columns/order", json={"columnIds": [str(XID)]})
    assert order.status_code == 200
    assert env.last()[1][1] == [XID]
    assert (
        c.patch(f"/api/todos/boards/{BID}/columns/{XID}", json={"isDone": True}).status_code == 200
    )
    assert (
        c.patch(f"/api/todos/boards/{BID}/columns/{XID}", json={"isDone": False}).status_code == 422
    )
    assert c.delete(f"/api/todos/boards/{BID}/columns/{XID}?moveTo={CID}").status_code == 200
    assert env.last()[2] == {"move_to": CID}
    assert (
        c.post(f"/api/todos/boards/{BID}/labels", json={"name": "L", "color": "red"}).status_code
        == 201
    )
    assert (
        c.post(f"/api/todos/boards/{BID}/labels", json={"name": "L", "color": "pink!"}).status_code
        == 422
    )
    assert (
        c.patch(f"/api/todos/boards/{BID}/labels/{XID}", json={"color": "blue"}).status_code == 200
    )
    assert c.delete(f"/api/todos/boards/{BID}/labels/{XID}").status_code == 204


def test_the_board_read_has_an_etag_and_answers_304(env: _Env) -> None:
    first = env.client.get(f"/api/todos/boards/{BID}")
    etag = first.headers["ETag"]
    assert first.status_code == 200 and etag.startswith('W/"')
    assert first.headers["Cache-Control"] == "no-cache"
    again = env.client.get(f"/api/todos/boards/{BID}", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.headers["ETag"] == etag
    other = env.client.get(f"/api/todos/boards/{BID}", headers={"If-None-Match": 'W/"x"'})
    assert other.status_code == 200


def test_etag_matching() -> None:
    tag = board_etag(_BOARD)
    assert tag == board_etag(TodoBoardOut(id=BID, name="B", kind="gremium"))
    assert tag != board_etag(TodoBoardOut(id=BID, name="C", kind="gremium"))
    assert not _matches(None, tag)
    assert not _matches("", tag)
    assert _matches("*", tag)
    assert _matches(f'"a", {tag.removeprefix("W/")}', tag)


def test_the_assigned_boards_read_has_an_etag_and_answers_304(env: _Env) -> None:
    first = env.client.get("/api/todos/mine/boards")
    assert first.status_code == 200
    body = first.json()
    assert body[0]["name"] == "B" and body[0]["canWrite"] is True
    assert body[0]["cards"][0]["id"] == str(CID)
    etag = first.headers["ETag"]
    assert first.headers["Cache-Control"] == "no-cache"
    again = env.client.get("/api/todos/mine/boards", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.headers["ETag"] == etag
    assert env.last()[0] == "mine_boards"


def test_the_all_boards_read_has_an_etag_and_answers_304(env: _Env) -> None:
    first = env.client.get("/api/todos/all/boards")
    assert first.status_code == 200
    assert first.json()[0]["kind"] == "personal"
    etag = first.headers["ETag"]
    assert first.headers["Cache-Control"] == "no-cache"
    again = env.client.get("/api/todos/all/boards", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.headers["ETag"] == etag
    assert env.last()[0] == "all_boards"


def test_mine_boards_etag_changes_with_the_body() -> None:
    one = [TodoAssignedBoard(id=BID, name="B", kind="gremium")]
    assert mine_boards_etag(one) == mine_boards_etag(list(one))
    assert mine_boards_etag(one) != mine_boards_etag([])
    assert mine_boards_etag(one) != mine_boards_etag(
        [TodoAssignedBoard(id=BID, name="B", kind="gremium", can_write=False)]
    )


def test_cross_board_routes(env: _Env) -> None:
    c = env.client
    assert c.get("/api/todos/mine").json() == {"items": [], "dueSoonCount": 0}
    hits = c.get(f"/api/todos/link-targets?q=ab&kind=ticket&excludeCardId={CID}")
    assert hits.json()[0]["targetId"] == str(XID)
    assert env.service.links.calls == [("ab", "ticket", CID)]
    assert c.get("/api/todos/link-targets?q=a").status_code == 422
    linked = c.get(f"/api/todos/linked?kind=meeting&targetId={XID}")
    assert linked.json()[0]["boardName"] == "B"
    assert c.get(f"/api/todos/linked?kind=todo&targetId={XID}").status_code == 422
    for kind in ("vote", "gremium", "invoice", "expense"):
        assert c.get(f"/api/todos/linked?kind={kind}&targetId={XID}").status_code == 200
        assert c.get(f"/api/todos/link-targets?q=ab&kind={kind}").status_code == 200
    assert c.get("/api/todos/link-targets?q=ab&kind=budget").status_code == 422


def test_the_link_picker_without_the_scope_is_empty(env: _Env) -> None:
    env.app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="t", scope_permissions=frozenset({"vote.cast"})
    )
    assert env.client.get("/api/todos/link-targets?q=ab").json() == []
    assert env.service.links.calls == []


def test_card_routes(env: _Env) -> None:
    c = env.client
    body = {"boardId": str(BID), "title": "t"}
    assert c.post("/api/todos/cards", json=body).status_code == 201
    assert c.post("/api/todos/cards", json={**body, "extra": 1}).status_code == 422
    assert c.get(f"/api/todos/cards/{CID}").json()["boardName"] == "B"
    assert c.get(f"/api/todos/cards/{CID}/tile").json()["id"] == str(CID)
    assert c.patch(f"/api/todos/cards/{CID}", json={"version": 1}).status_code == 200
    move = c.post(f"/api/todos/cards/{CID}/move", json={"columnId": str(XID)})
    assert move.json()["rank"] == "i"
    moved = c.post(f"/api/todos/cards/{CID}/transfer", json={"boardId": str(BID)})
    assert moved.json()["boardName"] == "B"
    assert env.last()[1][1].column_id is None
    assert c.delete(f"/api/todos/cards/{CID}").status_code == 204
    assert c.post(f"/api/todos/cards/{CID}/restore").status_code == 200
    assert (
        c.post(f"/api/todos/cards/{CID}/assignees", json={"principalId": str(XID)}).status_code
        == 200
    )
    assert c.delete(f"/api/todos/cards/{CID}/assignees/{XID}").status_code == 200
    assert c.post(f"/api/todos/cards/{CID}/labels", json={"labelId": str(XID)}).status_code == 200
    assert c.delete(f"/api/todos/cards/{CID}/labels/{XID}").status_code == 200
    assert c.post(f"/api/todos/cards/{CID}/checklist", json={"text": "x"}).status_code == 200
    assert (
        c.patch(f"/api/todos/cards/{CID}/checklist/{XID}", json={"done": True}).status_code == 200
    )
    assert c.delete(f"/api/todos/cards/{CID}/checklist/{XID}").status_code == 200
    link = c.post(f"/api/todos/cards/{CID}/links", json={"kind": "ticket", "targetId": str(XID)})
    assert link.status_code == 200
    assert env.last()[1][1:3] == ("ticket", XID)
    assert c.delete(f"/api/todos/cards/{CID}/links/{XID}").status_code == 200
    comment = c.post(f"/api/todos/cards/{CID}/comments", json={"body": "b", "mentions": [str(XID)]})
    assert comment.status_code == 201
    assert c.patch(f"/api/todos/cards/{CID}/comments/{XID}", json={"body": "c"}).status_code == 200
    assert c.delete(f"/api/todos/cards/{CID}/comments/{XID}").status_code == 204
    files = {"body": "", "attachmentIds": [str(XID)], "draftToken": "tok"}
    assert c.post(f"/api/todos/cards/{CID}/comments", json=files).status_code == 201
    _, _args, kw = next(call for call in reversed(env.service.calls) if call[0] == "add_comment")
    assert (kw["attachment_ids"], kw["draft_token"]) == ([XID], "tok")
    assert kw["pepper"]
    assert c.post(f"/api/todos/cards/{CID}/comments", json={"body": " "}).status_code == 422
    assert c.patch(f"/api/todos/cards/{CID}/comments/{XID}", json={"body": ""}).status_code == 422
    assert env.sent == []


@pytest.mark.parametrize(
    ("method", "path", "body", "name"),
    [
        ("post", "/api/todos/cards", {"boardId": str(BID), "title": "t"}, "create"),
        ("post", f"/api/todos/cards/{CID}/assignees", {"principalId": str(XID)}, "add_assignee"),
        ("post", f"/api/todos/cards/{CID}/comments", {"body": "b"}, "add_comment"),
        ("patch", f"/api/todos/cards/{CID}/comments/{XID}", {"body": "b"}, "edit_comment"),
    ],
)
def test_the_writes_with_mails_send_them_after_the_commit(
    env: _Env, method: str, path: str, body: dict[str, Any], name: str
) -> None:
    env.service.mail_on.add(name)
    assert getattr(env.client, method)(path, json=body).status_code in (200, 201)
    assert env.sent == [[TodoMail("assigned", CID, (XID,), XID)]]


def test_the_default_wiring() -> None:
    assert get_todo_mail_sender() is _deliver_todo_mails
    storage = object()

    class _Request:
        class app:
            class state:
                object_storage = storage

    service = get_todo_service(object(), _Request())  # type: ignore[arg-type]
    assert isinstance(service, TodoService)
    assert service.files.storage is storage


async def test_the_mail_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def _notify(**kw: Any) -> int:
        seen.update(kw)
        return 1

    monkeypatch.setattr(router_mod, "notify_todo_mails", _notify)
    mails = [TodoMail("assigned", CID, (XID,), XID)]
    await _deliver_todo_mails(load_settings(), mails, None)
    assert seen["mails"] == mails and seen["queue"] is None


class _Broker:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[tuple[str, dict[str, object]]] = []
        self.fail = fail

    async def publish(self, channel: str, message: dict[str, object]) -> None:
        if self.fail:
            raise RuntimeError("redis down")
        self.sent.append((channel, message))


def test_a_write_pings_its_board_after_the_route(env: _Env) -> None:
    """Ping the board after the write route.

    The pings are drained, so a read after it sends nothing.
    """
    broker = _Broker()
    env.app.state.broker = broker
    env.service.ping_on.add("move")
    assert env.client.post(f"/api/todos/cards/{CID}/move", json={"columnId": str(XID)}).is_success
    ping = {"type": "card", "boardId": str(BID), "cardId": str(CID)}
    assert broker.sent == [(f"todo-board:{BID}", ping)]
    assert env.client.get(f"/api/todos/cards/{CID}").is_success
    assert len(broker.sent) == 1


def test_a_failed_route_sends_no_ping(env: _Env) -> None:
    broker = _Broker()
    env.app.state.broker = broker
    env.service.ping_on.add("move")
    assert env.client.post(f"/api/todos/cards/{CID}/move", json={}).status_code == 422
    env.service.pings.touch(BID, CID)

    async def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("after the touch")

    env.service.move = _boom  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError):
        env.client.post(f"/api/todos/cards/{CID}/move", json={"columnId": str(XID)})
    assert broker.sent == []


def test_a_broker_fault_never_fails_the_write(env: _Env) -> None:
    env.app.state.broker = _Broker(fail=True)
    env.service.ping_on.add("move")
    assert env.client.post(f"/api/todos/cards/{CID}/move", json={"columnId": str(XID)}).is_success


def test_without_a_broker_the_fallback_takes_the_pings() -> None:
    class _State:
        pass

    assert live_mod.todo_broker(_State()) is live_mod._FALLBACK_BROKER
