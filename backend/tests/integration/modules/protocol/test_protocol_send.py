"""Finalize and send are two actions (§F/meetings/protocols/003019).

* ``finalize`` renders and stores the PDF and makes the protocol final, without a mail.
* ``send`` mails the stored PDF to the members and the extra addresses, sets ``sent_at``
  and writes ``protocol_send``; a repeat sends again.
* ``POST /protocols/{id}/send`` refuses a draft (409 ``protocol_not_final``).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.files.storage import ObjectStorage
from app.modules.gremien.models import Gremium
from app.modules.meetings.protocol_models import Protocol
from app.modules.notifications.mail import MailMessage
from app.modules.pdf.typst_client import TypstClient
from app.modules.protocol.service import ProtocolService
from app.shared.errors import ConflictError
from tests.integration.modules.livevote.conftest import ADMIN_SUB, audit_actions, seed

pytestmark = pytest.mark.integration


class _Storage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def remove(self, key: str) -> None:
        self.blobs.pop(key, None)


class _Typst:
    async def render_pdf(
        self,
        markdown: str,
        *,
        variant: str | None = None,
        config: Mapping[str, object] | None = None,
        assets: Mapping[str, bytes] | None = None,
    ) -> bytes:
        return b"%PDF-final"


class _Queue:
    def __init__(self) -> None:
        self.sent: list[MailMessage] = []

    async def enqueue(self, msg: MailMessage) -> None:
        self.sent.append(msg)


def _service(session: AsyncSession, storage: _Storage, queue: _Queue) -> ProtocolService:
    return ProtocolService(
        session,
        storage=cast("ObjectStorage", storage),
        typst=cast("TypstClient", _Typst()),
        mail_queue=queue,
    )


async def _with_list(maker: async_sessionmaker[AsyncSession], gremium_id: uuid.UUID) -> None:
    async with maker() as session:
        gremium = await session.get(Gremium, gremium_id)
        assert gremium is not None
        gremium.protocol_recipients = ["verteiler@example.org"]
        await session.commit()


async def test_finalize_sends_no_mail(maker: async_sessionmaker[AsyncSession]) -> None:
    """The finalization stores the PDF and makes the protocol final, without a mail."""
    s = await seed(maker, status="closed", items=1, protocol="draft")
    assert s.protocol_id is not None
    await _with_list(maker, s.gremium_id)
    storage, queue = _Storage(), _Queue()
    async with maker() as session:
        out = await _service(session, storage, queue).finalize(s.protocol_id, now=datetime.now(UTC))
    assert out.status == "final"
    assert (out.sent_at, out.is_sent) == (None, False)
    assert storage.blobs
    assert queue.sent == []


async def test_send_mails_the_final_pdf(maker: async_sessionmaker[AsyncSession]) -> None:
    """The send mails the stored PDF, marks the protocol sent and audits; a repeat sends."""
    s = await seed(maker, status="closed", items=1, protocol="draft")
    assert s.protocol_id is not None
    await _with_list(maker, s.gremium_id)
    storage, queue = _Storage(), _Queue()
    now = datetime.now(UTC)
    async with maker() as session:
        await _service(session, storage, queue).finalize(s.protocol_id, now=now)
    async with maker() as session:
        count, out = await _service(session, storage, queue).send(
            s.protocol_id, now=now + timedelta(minutes=5), actor=ADMIN_SUB
        )
        await session.commit()
    assert count >= 1 and out.is_sent is True
    assert len(queue.sent) == 1
    assert "verteiler@example.org" in queue.sent[0].to
    assert [a.content for a in queue.sent[0].attachments] == [b"%PDF-final"]
    async with maker() as session:
        protocol = await session.get(Protocol, s.protocol_id)
        assert protocol is not None and protocol.sent_at == now + timedelta(minutes=5)
        await _service(session, storage, queue).send(
            s.protocol_id, now=now + timedelta(days=1), actor=ADMIN_SUB
        )
        await session.commit()
    assert len(queue.sent) == 2
    assert queue.sent[0].idempotency_key != queue.sent[1].idempotency_key
    entries = [
        e
        for e in await audit_actions(maker, target_id=s.protocol_id)
        if e.action == "protocol_send"
    ]
    assert [e.data["recipients"] for e in entries] == [count, count]


async def test_send_without_a_recipient_is_refused(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """A Gremium without a recipient answers 409 ``protocol_no_recipients``."""
    s = await seed(maker, status="closed", items=0, protocol="final")
    assert s.protocol_id is not None
    queue = _Queue()
    async with maker() as session:
        with pytest.raises(ConflictError) as caught:
            await _service(session, _Storage(), queue).send(
                s.protocol_id, now=datetime.now(UTC), actor=ADMIN_SUB
            )
    assert caught.value.code == "protocol_no_recipients"
    assert queue.sent == []


async def test_send_of_a_draft_is_refused(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """The route refuses a draft (409) and an unknown protocol (404)."""
    s = await seed(maker, status="closed", items=0, protocol="draft")
    with TestClient(api) as client:
        draft = client.post(f"/api/protocols/{s.protocol_id}/send")
        missing = client.post(f"/api/protocols/{uuid.uuid4()}/send")
    assert draft.status_code == 409, draft.text
    assert draft.json()["code"] == "protocol_not_final"
    assert missing.status_code == 404, missing.text
