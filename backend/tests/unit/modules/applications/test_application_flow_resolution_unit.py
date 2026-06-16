"""Unit (ohne DB): Flow-Auswahl beim Anlegen eines Antrags (#28).

Es gibt nur den globalen Flow (Typ-Flows entfernt); fehlt er → 404.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.modules.admin.models import ApplicationType
from app.modules.applications.service import ApplicationsService
from app.shared.errors import NotFoundError
from tests._support.auth_fakes import fake_session, result


def _app_type() -> ApplicationType:
    t = ApplicationType(key="grossantrag", name_i18n={}, has_budget=False)
    t.id = uuid4()
    return t


async def test_uses_global_flow() -> None:
    global_id = uuid4()
    svc = ApplicationsService(fake_session(result(global_id)))
    out = await svc._resolve_flow_version_id(_app_type())
    assert out == global_id


async def test_raises_when_no_flow_at_all() -> None:
    svc = ApplicationsService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc._resolve_flow_version_id(_app_type())
