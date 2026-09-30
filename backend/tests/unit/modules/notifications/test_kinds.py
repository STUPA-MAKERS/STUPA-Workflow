"""F10: the notification catalogue holds only the kinds that some code sends.

No code sends a mail of the kind `vote` or `role_change`. The settings page must not
offer them, and a save of them gives 422 on the API.
"""

from __future__ import annotations

from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.notifications.kinds import NOTIFICATION_KINDS
from app.modules.notifications.layout import _REASONS
from app.modules.notifications.router import get_notification_service
from app.modules.notifications.service import NotificationService

_DEAD = ("vote", "role_change")


@pytest.mark.parametrize("kind", _DEAD)
def test_dead_kind_not_in_catalogue(kind: str) -> None:
    assert kind not in NOTIFICATION_KINDS
    assert kind not in _REASONS


@pytest.mark.parametrize("kind", _DEAD)
def test_save_of_dead_kind_gives_422(kind: str) -> None:
    app = create_app()
    app.dependency_overrides[get_notification_service] = lambda: NotificationService(
        cast(AsyncSession, object())
    )
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="u-1")
    resp = TestClient(app).put(
        "/api/notifications/preferences",
        json={"preferences": [{"kind": kind, "enabled": False}]},
    )
    assert resp.status_code == 422
    assert resp.headers["content-type"] == "application/problem+json"
