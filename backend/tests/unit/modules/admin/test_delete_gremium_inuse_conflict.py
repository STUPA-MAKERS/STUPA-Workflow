"""AUD-030: ``delete_gremium`` muss 409 (ConflictError) liefern, wenn eine
Antragsart des Gremiums noch Anträge hat.

``application_type.gremium_id`` kaskadiert, ``application.type_id`` ist aber
RESTRICT — ohne Vorab-Prüfung würde das Löschen die FK verletzen und einen 500
(IntegrityError) statt eines sauberen 409 erzeugen, plus ein Audit-Row für ein
zum Scheitern verurteiltes Löschen schreiben.

DB-loser Test mit einem ``AsyncSession``-Fake (kein Docker/Postgres).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.admin.service import ConfigService
from app.shared.errors import ConflictError


class _FakeSession:
    """Minimaler ``AsyncSession``-Stub für ``delete_gremium``.

    * ``get`` liefert das (vorhandene) Gremium beim ersten Aufruf.
    * ``scalar`` liefert den ``in_use``-Treffer (oder ``None``).
    * ``execute``/``commit``/``delete`` zählen mit, um zu prüfen, dass im
      Conflict-Fall *kein* Audit-Row und *kein* Commit passieren.
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

    # Kein Audit-Schreibvorgang, kein delete, kein commit für ein doomed delete.
    assert session.execute_calls == 0
    assert session.deleted == []
    assert session.committed == 0
