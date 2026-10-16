"""Fakes of the to-do unit tests: a scripted session, the board rules and the links.

``ScriptedSession`` answers ``scalar``, ``scalars`` and ``execute`` from FIFO queues
in the order of the queries of the code under test; ``get`` reads an in-memory
store. An ``execute`` answer is a list of rows or a ``Rows`` with a ``rowcount``.
``FakeAccess`` and ``FakeLinks`` stand in for ``BoardAccess`` and ``LinkResolver``,
so a service test scripts only the queries of the method itself.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from app.modules.auth.principal import Principal
from app.modules.files.schemas import MessageAttachmentOut
from app.modules.todos.access import ReadScope
from app.modules.todos.links import HIDDEN, LinkRef, Resolved
from app.modules.todos.models import (
    TodoBoard,
    TodoCard,
    TodoColumn,
    TodoComment,
    TodoEvent,
    TodoLabel,
    TodoLink,
)
from app.modules.todos.schemas import TodoLinkTarget, TodoMember

ME = uuid.UUID(int=1)
OTHER = uuid.UUID(int=2)
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
USER = Principal(sub="me-sub", permissions={"todo.write"})


class Rows:
    """The result of ``scalars`` or ``execute``."""

    def __init__(self, items: Iterable[Any] = (), rowcount: int = 0) -> None:
        self._items = list(items)
        self.rowcount = rowcount

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any:
        return self._items[0] if self._items else None


class ScriptedSession:
    """An ``AsyncSession`` double with queued answers."""

    bind = None

    def __init__(
        self,
        *,
        scalar: list[Any] | None = None,
        scalars: list[list[Any]] | None = None,
        execute: list[Any] | None = None,
    ) -> None:
        self.scalar_q = list(scalar or [])
        self.scalars_q = list(scalars or [])
        self.execute_q = list(execute or [])
        self.store: dict[Any, Any] = {}
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.statements: list[Any] = []
        self.committed = 0
        self.flushed = 0
        self.refreshed: list[Any] = []

    def put(self, *objs: Any) -> None:
        for obj in objs:
            self.store[obj.id] = obj

    def add(self, obj: Any) -> None:
        if hasattr(type(obj), "id") and getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        for attr in ("created_at", "updated_at"):
            if hasattr(type(obj), attr) and getattr(obj, attr, None) is None:
                setattr(obj, attr, NOW)
        self.added.append(obj)
        if getattr(obj, "id", None) is not None:
            self.store[obj.id] = obj

    async def get(self, model: type, ident: Any, **_kw: Any) -> Any:
        obj = self.store.get(ident)
        return obj if isinstance(obj, model) else None

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def refresh(self, obj: Any) -> None:
        self.refreshed.append(obj)

    async def scalar(self, stmt: Any, *_a: Any) -> Any:
        self.statements.append(stmt)
        return self.scalar_q.pop(0)

    async def scalars(self, stmt: Any) -> Rows:
        self.statements.append(stmt)
        return Rows(self.scalars_q.pop(0))

    async def execute(self, stmt: Any, *_a: Any) -> Rows:
        self.statements.append(stmt)
        answer = self.execute_q.pop(0) if self.execute_q else []
        return answer if isinstance(answer, Rows) else Rows(answer)


class FakeAccess:
    """``BoardAccess`` with fixed answers."""

    def __init__(
        self,
        *,
        me: uuid.UUID | None = ME,
        read: bool = True,
        configure: bool = True,
        members: Iterable[uuid.UUID] = (ME, OTHER),
        scope: ReadScope | None = None,
    ) -> None:
        self._me = me
        self.read = read
        self.configure = configure
        self.member_set = set(members)
        self._scope = scope or ReadScope(owner_id=me)

    async def me(self, _principal: Principal) -> uuid.UUID | None:
        return self._me

    async def can_read(self, _board: TodoBoard, _principal: Principal) -> bool:
        return self.read

    async def can_configure(self, _board: TodoBoard, _principal: Principal) -> bool:
        return self.configure

    async def scope(self, _principal: Principal) -> ReadScope:
        return self._scope

    async def members(self, _board: TodoBoard) -> list[TodoMember]:
        return [
            TodoMember(principal_id=pid, display_name=str(pid)[-1])
            for pid in sorted(self.member_set)
        ]

    async def member_ids(self, _board: TodoBoard) -> set[uuid.UUID]:
        return set(self.member_set)


class FakeLinks:
    """``LinkResolver`` with fixed answers."""

    def __init__(
        self,
        *,
        resolved: dict[LinkRef, Resolved] | None = None,
        readable: Iterable[LinkRef] = (),
        hits: list[TodoLinkTarget] | None = None,
    ) -> None:
        self.resolved = resolved or {}
        self.ok = set(readable)
        self.hits = hits or []
        self.searched: list[tuple[str, str, uuid.UUID | None]] = []

    async def resolve(
        self, refs: Iterable[LinkRef], _principal: Principal
    ) -> dict[LinkRef, Resolved]:
        return {ref: self.resolved.get(ref, HIDDEN) for ref in refs}

    async def readable(self, kind: str, target_id: uuid.UUID, _principal: Principal) -> bool:
        return (kind, target_id) in self.ok

    async def search(
        self,
        q: str,
        kind: str,
        _principal: Principal,
        *,
        exclude_card_id: uuid.UUID | None = None,
    ) -> list[TodoLinkTarget]:
        self.searched.append((q, kind, exclude_card_id))
        return self.hits


def board(**kw: Any) -> TodoBoard:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "name": "Board",
        "kind": "gremium",
        "gremium_id": uuid.uuid4(),
        "owner_id": None,
        "permission": None,
        "archive_after_days": 30,
        "archived_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(kw)
    return TodoBoard(**base)


def column(board_id: uuid.UUID, name: str = "Offen", position: int = 0, **kw: Any) -> TodoColumn:
    return TodoColumn(
        id=kw.pop("id", uuid.uuid4()),
        board_id=board_id,
        name=name,
        position=position,
        is_done=kw.pop("is_done", False),
    )


def card(b: TodoBoard, col: TodoColumn, **kw: Any) -> TodoCard:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "board_id": b.id,
        "column_id": col.id,
        "rank": "i",
        "title": "Karte",
        "description_md": None,
        "due_date": None,
        "due_reminded_on": None,
        "created_by": ME,
        "completed_at": None,
        "archived_at": None,
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(kw)
    return TodoCard(**base)


def label(board_id: uuid.UUID, name: str = "Wichtig", color: str = "red") -> TodoLabel:
    return TodoLabel(id=uuid.uuid4(), board_id=board_id, name=name, color=color)


def link(card_id: uuid.UUID, **target: uuid.UUID) -> TodoLink:
    return TodoLink(id=uuid.uuid4(), card_id=card_id, created_by=ME, created_at=NOW, **target)


def event(
    card_id: uuid.UUID, kind: str, payload: dict[str, Any], actor: uuid.UUID | None = ME
) -> TodoEvent:
    return TodoEvent(
        id=uuid.uuid4(), card_id=card_id, actor_id=actor, kind=kind, payload=payload, created_at=NOW
    )


def comment(card_id: uuid.UUID, author: uuid.UUID = ME, **kw: Any) -> TodoComment:
    return TodoComment(
        id=kw.pop("id", uuid.uuid4()),
        card_id=card_id,
        author_id=author,
        body=kw.pop("body", "Text"),
        mentions=kw.pop("mentions", []),
        created_at=NOW,
        edited_at=None,
        deleted_at=kw.pop("deleted_at", None),
    )


TODAY = date(2026, 10, 1)


class FakeFiles:
    """The files methods of the to-do service: the files of the comments."""

    def __init__(self, messages: dict[uuid.UUID, list[MessageAttachmentOut]] | None = None) -> None:
        self.messages = messages or {}
        self.asked: list[list[uuid.UUID]] = []
        self.removed: list[tuple[list[uuid.UUID], str]] = []
        self.dropped: list[tuple[list[uuid.UUID], str]] = []
        self.locked: list[list[uuid.UUID]] = []

    async def message_attachments(
        self, _owner: str, ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[MessageAttachmentOut]]:
        self.asked.append(list(ids))
        return {i: self.messages[i] for i in ids if i in self.messages}

    async def delete_for_messages(self, _owner: str, ids: list[uuid.UUID], *, actor: str) -> int:
        self.removed.append((list(ids), actor))
        return len(ids)

    async def lock_for_messages(self, _owner: str, ids: list[uuid.UUID]) -> None:
        self.locked.append(list(ids))

    async def drop_for_messages(
        self, _owner: str, ids: list[uuid.UUID], *, actor: str
    ) -> list[str]:
        assert self.locked, "the file rows are locked before they are dropped"
        self.dropped.append((list(ids), actor))
        return [f"key-{i}" for i in ids]
