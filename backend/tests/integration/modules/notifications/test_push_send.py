"""Integration: a push goes along with the mail of an event and the worker sends it.

§F/collaboration/notifications/002501: push and mail filter on their own switches.
§F/collaboration/notifications/002503: the push names the kind and shows the subject.
§F/collaboration/notifications/002506: a gone device is deleted and never retried.
§F/collaboration/notifications/002510: a forged endpoint is never called.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import httpx
import pytest
from arq import Retry
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.notifications.links import todo_link
from app.modules.notifications.mail import MailMessage
from app.modules.notifications.models import NotificationPreference
from app.modules.notifications.push_models import PushPreference, PushSubscription
from app.modules.notifications.push_service import PushButton, PushJob
from app.modules.notifications.service import NotificationService
from app.settings import Settings
from app.shared.ssrf import SsrfError
from tests.integration.modules.tickets.conftest import add_principal
from worker.push import send_push

pytestmark = pytest.mark.integration

#: A real P-256 point and auth secret (RFC 8291, appendix A), so the encryption runs.
P256DH = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
AUTH = "BTBZMqHH6r4Tts7J_aSIgg"


@dataclass
class Queue:
    """A mail queue that also takes push jobs, and keeps both."""

    mails: list[MailMessage] = field(default_factory=list)
    pushes: list[PushJob] = field(default_factory=list)

    async def enqueue(self, msg: MailMessage) -> None:
        self.mails.append(msg)

    async def enqueue_push(self, job: PushJob) -> None:
        self.pushes.append(job)


@dataclass
class Poster:
    """A push service that answers ``status`` or raises ``error``."""

    status: int = 201
    error: Exception | None = None
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    async def post(self, endpoint: str, headers: dict[str, str], body: bytes) -> int:
        self.calls.append((endpoint, headers))
        if self.error is not None:
            raise self.error
        return self.status


async def _device(
    maker: async_sessionmaker[AsyncSession],
    person: uuid.UUID,
    endpoint: str = "https://fcm.googleapis.com/fcm/send/d1",
) -> uuid.UUID:
    async with maker() as session:
        sub_id = await session.scalar(
            insert(PushSubscription)
            .values(principal_id=person, endpoint=endpoint, p256dh=P256DH, auth=AUTH, label="P")
            .returning(PushSubscription.id)
        )
        await session.commit()
        assert sub_id is not None
        return sub_id


async def _send(
    maker: async_sessionmaker[AsyncSession], settings: Settings, queue: Queue, email: str
) -> bool:
    async with maker() as session:
        sent = await NotificationService(session, queue=queue, settings=settings).send_kind_mail(
            [email],
            kind="todo_assigned",
            template_key="todo_assigned_test",
            builtin_subject={"de": "Plakat wurde dir zugewiesen", "en": "Poster assigned"},
            builtin_body={"de": "Hallo", "en": "Hello"},
            context={},
            idempotency_parts=("t", email),
            lang="de",
            link=todo_link(settings, uuid.uuid4()),
            push_buttons=(PushButton("todo_done", target_id=uuid.uuid4()),),
        )
        await session.commit()
        return sent


async def test_push_goes_along_with_the_mail(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    person = await add_principal(maker, email="pia@example.org")
    device = await _device(maker, person)
    queue = Queue()
    assert await _send(maker, settings, queue, "pia@example.org")
    assert len(queue.mails) == 1
    [job] = queue.pushes
    assert job.subscription_id == str(device) and job.urgency == "normal"
    shown = json.loads(job.payload)["notification"]
    assert shown["title"] == "To-Do zugewiesen"
    assert shown["body"] == "Plakat wurde dir zugewiesen"
    assert [a["action"] for a in shown["actions"]] == ["todo_done"]


async def test_push_and_mail_follow_their_own_switch(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    person = await add_principal(maker, email="pia@example.org")
    await _device(maker, person)
    async with maker() as session:
        session.add(
            NotificationPreference(principal_id=person, kind="todo_assigned", enabled=False)
        )
        await session.commit()
    queue = Queue()
    assert not await _send(maker, settings, queue, "pia@example.org")
    assert queue.mails == [] and len(queue.pushes) == 1
    async with maker() as session:
        session.add(PushPreference(principal_id=person, kind="todo_assigned", enabled=False))
        await session.commit()
    quiet = Queue()
    assert not await _send(maker, settings, quiet, "pia@example.org")
    assert quiet.mails == [] and quiet.pushes == []


async def test_no_push_without_device_or_for_an_inactive_account(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await add_principal(maker, email="nodevice@example.org")
    gone = await add_principal(maker, email="gone@example.org", active=False)
    await _device(maker, gone)
    queue = Queue()
    assert await _send(maker, settings, queue, "nodevice@example.org")
    assert await _send(maker, settings, queue, "gone@example.org")
    assert queue.pushes == [] and len(queue.mails) == 2


async def _job(maker: async_sessionmaker[AsyncSession], settings: Settings, email: str) -> PushJob:
    queue = Queue()
    await _send(maker, settings, queue, email)
    return queue.pushes[0]


def _ctx(
    maker: async_sessionmaker[AsyncSession], settings: Settings, poster: Poster, job_try: int = 1
) -> dict[str, object]:
    return {
        "settings": settings,
        "push_sessionmaker": maker,
        "push_poster": poster,
        "job_try": job_try,
    }


async def test_worker_sends_and_marks_the_device(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    person = await add_principal(maker, email="pia@example.org")
    device = await _device(maker, person)
    job = await _job(maker, settings, "pia@example.org")
    poster = Poster(201)
    assert await send_push(_ctx(maker, settings, poster), job.to_payload()) == "sent"
    [(endpoint, headers)] = poster.calls
    assert endpoint == "https://fcm.googleapis.com/fcm/send/d1"
    assert headers["Content-Encoding"] == "aes128gcm"
    assert headers["Authorization"].startswith("vapid t=")
    async with maker() as session:
        row = await session.get(PushSubscription, device)
        assert row is not None and row.last_success_at is not None


async def test_worker_deletes_a_gone_device(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    person = await add_principal(maker, email="pia@example.org")
    device = await _device(maker, person)
    job = await _job(maker, settings, "pia@example.org")
    assert await send_push(_ctx(maker, settings, Poster(410)), job.to_payload()) == "gone"
    async with maker() as session:
        assert await session.get(PushSubscription, device) is None
    assert await send_push(_ctx(maker, settings, Poster(201)), job.to_payload()) == "gone"


async def test_worker_retries_then_gives_up(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    person = await add_principal(maker, email="pia@example.org")
    await _device(maker, person)
    job = await _job(maker, settings, "pia@example.org")
    with pytest.raises(Retry):
        await send_push(_ctx(maker, settings, Poster(503)), job.to_payload())
    with pytest.raises(Retry):
        await send_push(
            _ctx(maker, settings, Poster(error=httpx.ConnectError("x"))), job.to_payload()
        )
    last = _ctx(maker, settings, Poster(429), job_try=settings.mail_max_tries)
    assert await send_push(last, job.to_payload()) == "dead"
    assert await send_push(_ctx(maker, settings, Poster(400)), job.to_payload()) == "refused"
    blocked = Poster(error=SsrfError("blocked"))
    assert await send_push(_ctx(maker, settings, blocked), job.to_payload()) == "refused"


async def test_worker_never_calls_a_forged_endpoint(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    person = await add_principal(maker, email="pia@example.org")
    device = await _device(maker, person, endpoint="https://intranet.example.org/x")
    job = PushJob(subscription_id=str(device), payload="{}", urgency="normal", ttl=60, job_id="")
    poster = Poster(201)
    assert await send_push(_ctx(maker, settings, poster), job.to_payload()) == "refused"
    assert poster.calls == []
    async with maker() as session:
        assert await session.get(PushSubscription, device) is None
