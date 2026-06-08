"""Unit (ohne DB): Flow-Auswahl beim Anlegen eines Antrags (#28).

Globaler Flow hat Vorrang vor dem per-Typ-Flow; fehlt beides → 404.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.modules.admin.models import ApplicationType
from app.modules.applications.service import ApplicationsService
from app.shared.errors import NotFoundError
from tests.auth_fakes import fake_session, result


def _app_type(active_flow_version_id=None) -> ApplicationType:
    t = ApplicationType(key="grossantrag", name_i18n={}, has_budget=False)
    t.id = uuid4()
    t.active_flow_version_id = active_flow_version_id
    return t


async def test_prefers_global_flow() -> None:
    global_id = uuid4()
    svc = ApplicationsService(fake_session(result(global_id)))
    out = await svc._resolve_flow_version_id(_app_type(active_flow_version_id=uuid4()))
    assert out == global_id


async def test_falls_back_to_per_type_flow() -> None:
    per_type = uuid4()
    svc = ApplicationsService(fake_session(result()))  # no global flow
    out = await svc._resolve_flow_version_id(_app_type(active_flow_version_id=per_type))
    assert out == per_type


async def test_raises_when_no_flow_at_all() -> None:
    svc = ApplicationsService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc._resolve_flow_version_id(_app_type(active_flow_version_id=None))
