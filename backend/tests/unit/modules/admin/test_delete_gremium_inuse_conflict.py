"""AUD-030: ``delete_gremium`` must return 409 (ConflictError), not 500.

The conflict applies when an application type of the Gremium still holds applications.
``application_type.gremium_id`` cascades, but ``application.type_id`` is RESTRICT.
Without the check up front the delete breaks the foreign key. The caller then gets a 500
(IntegrityError) instead of a clean 409, and the service writes an audit row for a delete
that cannot succeed.

The test needs no DB. An ``AsyncSession`` fake replaces Docker and Postgres.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.admin.service import ConfigService
from app.shared.errors import ConflictError


class _FakeSession:
    """Minimal ``AsyncSession`` stub for ``delete_gremium``.

    ``get`` returns the existing Gremium on the first call. ``scalar`` returns the
    ``in_use`` hit or ``None``. ``execute``, ``commit`` and ``delete`` count their calls.
    The test proves that a conflict writes *no* audit row and runs *no* commit.
    """

    def __init__(self, *, gremium: Any, in_use: Any) -> None:
        self._gremium = gremium
        self._in_use = in_use
        self.deleted: list[Any] = []
        self.execute_calls = 0
        self.committed = 0

    async def get(self, _model: Any, _ident: Any) -> Any:
        return self._gremium

    async def scalar(self, _stmt: Any) -> Any:
        return self._in_use

    async def execute(self, _stmt: Any) -> Any:  # pragma: no cover - guarded path
        self.execute_calls += 1
        raise AssertionError("audit/execute must not run on a doomed delete")

    async def delete(self, obj: Any) -> None:  # pragma: no cover - guarded path
        self.deleted.append(obj)

    async def commit(self) -> None:  # pragma: no cover - guarded path
        self.committed += 1


class _Row:
    def __init__(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


@pytest.mark.asyncio
async def test_delete_gremium_with_in_use_type_raises_conflict() -> None:
    gid = uuid.uuid4()
    gremium = _Row(id=gid)
    session = _FakeSession(gremium=gremium, in_use=uuid.uuid4())
    svc = ConfigService(session)  # type: ignore[arg-type]

    with pytest.raises(ConflictError):
        await svc.delete_gremium(gid, "admin")

    # A doomed delete writes no audit row, deletes nothing and commits nothing.
    assert session.execute_calls == 0
    assert session.deleted == []
    assert session.committed == 0
