"""Shared fixtures of the unit tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meetings import present as present_mod
from app.modules.meetings.present import Present
from app.modules.notifications import brand as brand_mod
from app.modules.site_config.branding import Branding
from app.modules.webhooks import events as events_mod
from app.modules.webhooks.models import Webhook


@dataclass(slots=True)
class Presence:
    """The present count that each meeting of one test has; None reads no meeting."""

    here: Present | None = None


@pytest.fixture(autouse=True)
def presence(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Presence:
    """Stub the read of the present count, so a session fake needs no row for it.

    A test sets `presence.here` to give each meeting this count. A test of the read
    itself carries the marker `real_present` and reads through its own fake.
    """
    holder = Presence()
    if request.node.get_closest_marker("real_present") is not None:
        return holder

    async def _counts(_session: AsyncSession, meeting_ids: Sequence[UUID]) -> dict[UUID, Present]:
        return {} if holder.here is None else dict.fromkeys(meeting_ids, holder.here)

    monkeypatch.setattr(present_mod, "present_counts", _counts)
    return holder


@dataclass(slots=True)
class MailBranding:
    """The active branding that the mails of one test read."""

    active: Branding


@pytest.fixture(autouse=True)
def mail_branding(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> MailBranding:
    """Stub the branding read of the mails, so a session fake needs no row for it.

    A test sets `mail_branding.active` to give its mails this branding. A test of the read
    itself carries the marker `real_branding` and reads through its own fake.
    """
    holder = MailBranding(active=Branding())
    if request.node.get_closest_marker("real_branding") is not None:
        return holder

    async def _active(_session: AsyncSession) -> Branding:
        return holder.active

    monkeypatch.setattr(brand_mod, "active_branding", _active)
    return holder


@dataclass(slots=True)
class ActiveWebhooks:
    """The active webhooks that the event emit of one test reads."""

    hooks: list[Webhook]


@pytest.fixture(autouse=True)
def active_webhooks(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> ActiveWebhooks:
    """Stub the read of the active webhooks, so a session fake needs no row for them.

    A domain event then finds no webhook and adds no delivery. A test sets
    `active_webhooks.hooks` to let its event reach these webhooks. A test of the read itself
    carries the marker `real_webhooks`.
    """
    holder = ActiveWebhooks(hooks=[])
    if request.node.get_closest_marker("real_webhooks") is not None:
        return holder

    async def _active(_session: AsyncSession) -> list[Webhook]:
        return list(holder.hooks)

    monkeypatch.setattr(events_mod, "active_webhooks", _active)
    return holder


@pytest.fixture(autouse=True)
def paperless_links_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the switch of the Paperless links as off, so a session fake needs no row for it.

    The links to Paperless documents have their tests on a real Postgres
    (`tests/integration/modules/todos/test_paperless_links.py`).
    """

    async def _off(_session: AsyncSession) -> bool:
        return False

    monkeypatch.setattr("app.modules.todos.links.links_part_on", _off)
