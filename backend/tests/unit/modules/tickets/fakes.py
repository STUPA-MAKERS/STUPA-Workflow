"""Fakes of the ticket unit tests: a scripted session and a files double.

``ScriptedSession`` answers ``scalar``, ``scalars`` and ``execute`` from FIFO queues
that the test fills in the order of the queries of the code under test. An empty
``scalar`` queue answers None (no row), so a trailing lookup such as the sender
block of a detail needs no entry. ``get``
reads an in-memory store that ``add`` fills and keeps its keyword arguments (a lock
shows as ``with_for_update``). Every statement is kept, so a test can
look at the SQL of a query.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.modules.files.schemas import AttachmentOut, MessageAttachmentOut


class Result:
    """The result of ``scalars`` or ``execute``."""

    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any:
        return self._items[0] if self._items else None


class ScriptedSession:
    """An ``AsyncSession`` double with queued answers."""

    def __init__(
        self,
        *,
        scalar: list[Any] | None = None,
        scalars: list[list[Any]] | None = None,
        execute: list[list[Any]] | None = None,
    ) -> None:
        self.scalar_q = list(scalar or [])
        self.scalars_q = list(scalars or [])
        self.execute_q = list(execute or [])
        self.store: dict[uuid.UUID, Any] = {}
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.statements: list[Any] = []
        self.committed = 0
        self.flushed = 0
        self.get_kw: list[dict[str, Any]] = []

    def put(self, *objs: Any) -> None:
        for obj in objs:
            self.store[obj.id] = obj

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        for attr in ("created_at", "updated_at"):
            if hasattr(type(obj), attr) and getattr(obj, attr, None) is None:
                setattr(obj, attr, now)
        self.added.append(obj)
        self.store[obj.id] = obj

    async def get(self, model: type, ident: Any, **kw: Any) -> Any:
        self.get_kw.append(kw)
        obj = self.store.get(ident)
        return obj if isinstance(obj, model) else None

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def refresh(self, _obj: Any) -> None:
        return None

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def scalar(self, stmt: Any) -> Any:
        self.statements.append(stmt)
        return self.scalar_q.pop(0) if self.scalar_q else None

    async def scalars(self, stmt: Any) -> Result:
        self.statements.append(stmt)
        return Result(self.scalars_q.pop(0))

    async def execute(self, stmt: Any) -> Result:
        self.statements.append(stmt)
        return Result(self.execute_q.pop(0) if self.execute_q else [])


class FakeFiles:
    """The files methods that the ticket service calls."""

    def __init__(
        self,
        attachments: list[AttachmentOut] | None = None,
        messages: dict[uuid.UUID, list[MessageAttachmentOut]] | None = None,
    ) -> None:
        self.attachments = attachments or []
        self.messages = messages or {}
        self.deleted: list[tuple[uuid.UUID, str]] = []
        self.asked: list[tuple[str, list[uuid.UUID]]] = []
        self.removed: list[tuple[str, list[uuid.UUID], str]] = []

    async def message_attachments(
        self, owner: str, ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[MessageAttachmentOut]]:
        self.asked.append((owner, list(ids)))
        return {i: self.messages[i] for i in ids if i in self.messages}

    async def delete_for_messages(self, owner: str, ids: list[uuid.UUID], *, actor: str) -> int:
        self.removed.append((owner, list(ids), actor))
        return len(ids)

    async def drop_for_messages(self, owner: str, ids: list[uuid.UUID], *, actor: str) -> list[str]:
        self.removed.append((owner, list(ids), actor))
        return []

    async def list_for_ticket(self, _ticket_id: uuid.UUID) -> list[AttachmentOut]:
        return self.attachments

    async def delete_for_ticket(self, ticket_id: uuid.UUID, *, actor: str) -> int:
        self.deleted.append((ticket_id, actor))
        return 1
