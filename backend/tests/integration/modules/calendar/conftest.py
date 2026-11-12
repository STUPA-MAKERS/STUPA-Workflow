"""Fixtures of the Kalender integration tests (real Postgres).

The accounts, the Gremien and the boards come from the helpers of the to-do tests. The
`api` fixture collects the Termin mails of a write instead of sending them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.deps import get_current_principal
from app.modules.auth.principal import Principal
from app.modules.calendar.appointments import AppointmentMail
from app.modules.calendar.router import get_appointment_mail_sender
from app.settings import Settings
from tests._support.guest_apps import build_api
from tests.integration.modules.todos.conftest import clean, maker, settings

__all__ = ["CalendarApi", "api", "clean", "maker", "settings"]


@dataclass
class CalendarApi:
    """The app with a login switch and the collected Termin mails."""

    app: FastAPI
    mails: list[AppointmentMail] = field(default_factory=list)

    def login(self, principal: Principal | None) -> None:
        self.app.dependency_overrides[get_current_principal] = lambda: principal


@pytest.fixture
def api(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> CalendarApi:
    app = build_api(migrated[1], settings, monkeypatch)
    state = CalendarApi(app=app)

    async def _send(_settings: Settings, mails: list[AppointmentMail], _pool: object) -> None:
        state.mails.extend(mails)

    app.dependency_overrides[get_appointment_mail_sender] = lambda: _send
    app.dependency_overrides[get_current_principal] = lambda: None
    return state
