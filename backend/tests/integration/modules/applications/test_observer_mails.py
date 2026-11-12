"""The mails to the observers of an application on a real Postgres.

§ F/applications/applications/000754 the observer gets one mail after the add with the
login link and the end link; each status mail of the applicant goes to every observer
with its own end link, to ``/applications/{id}`` for an active account and to
``/my-applications/{id}`` for every other address; an account that switched the status
mails off gets none.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications import observer_mails, observers_router
from app.modules.applications.models import ApplicationObserver
from app.modules.applications.observers import end_link
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth.models import EmailLoginLink
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.notifications.mail import MailMessage, compute_idempotency_key
from app.modules.notifications.models import NotificationPreference
from app.settings import Settings
from tests._support.guest_apps import GuestSeed, guest_settings, seed_guest_flow

pytestmark = pytest.mark.integration


class _Queue:
    def __init__(self) -> None:
        self.messages: list[MailMessage] = []

    async def enqueue(self, msg: MailMessage) -> None:
        self.messages.append(msg)


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return guest_settings(migrated[1])


@pytest.fixture
async def seed(maker: async_sessionmaker[AsyncSession]) -> GuestSeed:
    return await seed_guest_flow(maker)


async def _create(maker: async_sessionmaker[AsyncSession], seed: GuestSeed) -> uuid.UUID:
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(seed.type_id),
            "data": {"title": "Druckauftrag Plakate"},
            "applicantEmail": "luis@example.org",
            "applicantName": "Luis Meyer",
        }
    )
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            payload, actor="owner-sub", email_confirmed=True
        )
        return app.id


async def _observe(
    maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID, *emails: str
) -> list[uuid.UUID]:
    async with maker() as session:
        rows = [ApplicationObserver(application_id=app_id, email=e) for e in emails]
        session.add_all(rows)
        await session.commit()
        return [r.id for r in rows]


async def test_the_new_observer_gets_one_mail(
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 000754: the mail after the add has the login link and the end link."""
    app_id = await _create(maker, seed)
    (obs_id,) = await _observe(maker, app_id, "adrian.observer@example.org")
    queue = _Queue()

    async with maker() as session:
        sent = await observer_mails.notify_observer_added(
            session, queue=queue, settings=settings, application_id=app_id, observer_id=obs_id
        )
        gone = await observer_mails.notify_observer_added(
            session, queue=queue, settings=settings, application_id=app_id, observer_id=uuid.uuid4()
        )

    assert (sent, gone) == (True, False)
    (msg,) = queue.messages
    assert msg.to == ("adrian.observer@example.org",)
    assert msg.subject == "Du beobachtest einen Antrag: „Druckauftrag Plakate“"
    assert "Luis Meyer hat dich als Beobachter:in" in msg.text
    assert "/my-applications#t=" in msg.text
    assert end_link(settings.public_base_url, settings.magic_link_secret, obs_id) in msg.text
    assert msg.idempotency_key == compute_idempotency_key("application_observer_added", str(obs_id))


async def test_the_background_task_commits_and_never_raises(
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 000754: the add mail stores its login link; a failure only logs."""
    monkeypatch.setattr(observers_router, "get_sessionmaker", lambda: maker)
    app_id = await _create(maker, seed)
    (obs_id,) = await _observe(maker, app_id, "adrian.observer@example.org")

    await observers_router.get_observer_mail_sender()(settings, app_id, obs_id, None)
    async with maker() as session:
        links = await session.scalar(select(func.count()).select_from(EmailLoginLink))
    assert links == 1

    async def _boom(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("redis down")

    logged: list[object] = []
    monkeypatch.setattr(observers_router, "notify_observer_added", _boom)
    monkeypatch.setattr(observers_router.logger, "exception", lambda *a: logged.append(a))
    await observers_router.get_observer_mail_sender()(settings, app_id, obs_id, None)
    assert logged == [("observer mail failed (application=%s)", app_id)]


async def test_each_observer_gets_the_status_mail(
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 000754: one mail per observer, its link by account, no mail after an opt-out."""
    app_id = await _create(maker, seed)
    adrian, guest, quiet = await _observe(
        maker,
        app_id,
        "Adrian.Observer@Example.org",
        "guest@example.org",
        "muted-observer@example.org",
    )
    async with maker() as session:
        session.add(
            PrincipalRow(
                sub="adrian-observer-sub", email="adrian.observer@example.org", active=True
            )
        )
        muted = PrincipalRow(
            sub="muted-observer-sub", email="muted-observer@example.org", active=True
        )
        session.add(muted)
        await session.flush()
        session.add(
            NotificationPreference(principal_id=muted.id, kind="status_update", enabled=False)
        )
        await session.commit()
    queue = _Queue()
    context = {"applicationTitle": "Druckauftrag Plakate", "status": "Bewilligt"}

    async with maker() as session:
        sent = await observer_mails.send_observer_status_mails(
            session,
            queue=queue,
            settings=settings,
            application_id=app_id,
            context=context,
            idempotency_base="status-1",
        )

    assert sent == 2
    by_to = {m.to[0].lower(): m for m in queue.messages}
    assert set(by_to) == {"adrian.observer@example.org", "guest@example.org"}
    assert f"/applications/{app_id}" in by_to["adrian.observer@example.org"].text
    assert "/my-applications/" not in by_to["adrian.observer@example.org"].text
    assert f"/my-applications/{app_id}" in by_to["guest@example.org"].text
    assert "neuen Status: Bewilligt" in by_to["guest@example.org"].text
    for obs_id, addr in ((adrian, "adrian.observer@example.org"), (guest, "guest@example.org")):
        link = end_link(settings.public_base_url, settings.magic_link_secret, obs_id)
        assert link in by_to[addr].text
        assert by_to[addr].idempotency_key == compute_idempotency_key(
            "status-1", "application_observer_status", str(obs_id)
        )
    assert quiet not in (adrian, guest)

    other = await _create(maker, seed)
    async with maker() as session:
        assert (
            await observer_mails.send_observer_status_mails(
                session,
                queue=queue,
                settings=settings,
                application_id=other,
                context=context,
                idempotency_base="status-2",
            )
            == 0
        )
