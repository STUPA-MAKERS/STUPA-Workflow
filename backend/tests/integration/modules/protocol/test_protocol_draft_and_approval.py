"""The draft mail and the approval mark of a protocol through the real stack.

* ``POST /protocols/{id}/draft-mail`` sends the PDF with the watermark "Entwurf" to the
  members and leaves the protocol a draft (§F/meetings/protocols/000925).
* ``PUT`` and ``DELETE /protocols/{id}/approval`` mark a final protocol as approved by
  another meeting of the same Gremium; a draft answers 409
  (§F/meetings/protocols/000924).
* The meeting list of the Gremium page carries the mark.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from datetime import date as _date
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.files.storage import ObjectStorage
from app.modules.gremien.models import GremiumMembership, GremiumRole
from app.modules.meetings.models import Meeting
from app.modules.meetings.protocol_models import Protocol
from app.modules.notifications.mail import MailMessage
from app.modules.notifications.models import NotificationPreference
from app.modules.pdf.typst_client import TypstClient
from app.modules.protocol.draft_mail import WATERMARK, DraftMailer
from app.modules.protocol.service import ProtocolService
from app.shared.errors import ConflictError, ServiceUnavailableError
from tests.integration.modules.livevote.conftest import ADMIN_SUB, audit_actions, seed

pytestmark = pytest.mark.integration


class _Storage:
    async def put(self, key: str, data: bytes, content_type: str) -> None:
        raise AssertionError("a draft mail stores nothing")

    async def get(self, key: str) -> bytes:
        raise KeyError(key)

    async def remove(self, key: str) -> None:
        return None


class _Typst:
    def __init__(self) -> None:
        self.configs: list[Mapping[str, object]] = []

    async def render_pdf(
        self,
        markdown: str,
        *,
        variant: str | None = None,
        config: Mapping[str, object] | None = None,
        assets: Mapping[str, bytes] | None = None,
    ) -> bytes:
        self.configs.append(dict(config or {}))
        return b"%PDF-draft"


class _Queue:
    def __init__(self) -> None:
        self.sent: list[MailMessage] = []

    async def enqueue(self, msg: MailMessage) -> None:
        self.sent.append(msg)


async def _members(
    maker: async_sessionmaker[AsyncSession], gremium_id: uuid.UUID, names: tuple[str, ...]
) -> dict[str, PrincipalRow]:
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        role = GremiumRole(
            gremium_id=gremium_id, key=f"m-{tag}", name_i18n={"de": "Mitglied"}, permissions=[]
        )
        rows = {
            name: PrincipalRow(sub=f"{name}-{tag}", display_name=name, email=f"{name}-{tag}@x.de")
            for name in names
        }
        session.add_all([role, *rows.values()])
        await session.flush()
        session.add_all(
            [
                GremiumMembership(
                    principal_id=row.id, gremium_id=gremium_id, gremium_role_id=role.id
                )
                for row in rows.values()
            ]
        )
        await session.commit()
        return rows


async def test_draft_mail_goes_to_the_members_and_keeps_the_draft(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    s = await seed(maker, status="closed", items=1, protocol="draft")
    assert s.protocol_id is not None
    people = await _members(maker, s.gremium_id, ("anna", "ben"))
    async with maker() as session:
        session.add(
            NotificationPreference(
                principal_id=people["ben"].id, kind="protocol", enabled=False
            )
        )
        await session.commit()
    typst, queue = _Typst(), _Queue()
    now = datetime.now(UTC)
    async with maker() as session:
        service = ProtocolService(
            session,
            storage=cast("ObjectStorage", _Storage()),
            typst=cast("TypstClient", typst),
            mail_queue=queue,
        )
        sent = await DraftMailer(service).send(s.protocol_id, now=now, actor=ADMIN_SUB)
        await session.commit()
    assert sent == 1
    assert typst.configs[-1]["watermark"] == WATERMARK
    assert len(queue.sent) == 1
    message = queue.sent[0]
    assert message.to == (people["anna"].email,)
    assert message.subject.startswith("Protokollentwurf G")
    assert "20.06.2026" in message.subject
    assert [a.filename.startswith("Entwurf ") for a in message.attachments] == [True]
    assert message.attachments[0].content == b"%PDF-draft"
    async with maker() as session:
        protocol = await session.get(Protocol, s.protocol_id)
        assert protocol is not None
        assert protocol.status == "draft"
        assert (protocol.pdf_storage_key, protocol.sent_at) == (None, None)
    entries = [
        e
        for e in await audit_actions(maker, target_id=s.protocol_id)
        if e.action == "protocol_draft_mail"
    ]
    assert [e.data["recipients"] for e in entries] == [1]


async def test_draft_mail_without_a_reader_sends_nothing_and_needs_a_draft(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    s = await seed(maker, status="closed", items=0, protocol="draft")
    final = await seed(maker, status="closed", items=0, protocol="final")
    assert s.protocol_id is not None and final.protocol_id is not None
    typst, queue = _Typst(), _Queue()
    now = datetime.now(UTC)
    async with maker() as session:
        service = ProtocolService(
            session,
            storage=cast("ObjectStorage", _Storage()),
            typst=cast("TypstClient", typst),
            mail_queue=queue,
        )
        mailer = DraftMailer(service)
        assert await mailer.send(s.protocol_id, now=now, actor=ADMIN_SUB) == 0
        with pytest.raises(ConflictError):
            await mailer.send(final.protocol_id, now=now, actor=ADMIN_SUB)
        with pytest.raises(ServiceUnavailableError):
            await DraftMailer(
                ProtocolService(
                    session,
                    storage=cast("ObjectStorage", _Storage()),
                    typst=cast("TypstClient", typst),
                )
            ).send(s.protocol_id, now=now, actor=ADMIN_SUB)
    assert queue.sent == []


async def test_draft_mail_route_answers_503_without_a_render_service(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="closed", items=0, protocol="draft")
    final = await seed(maker, status="closed", items=0, protocol="final")
    with TestClient(api) as client:
        resp = client.post(f"/api/protocols/{s.protocol_id}/draft-mail")
        not_draft = client.post(f"/api/protocols/{final.protocol_id}/draft-mail")
        missing = client.post(f"/api/protocols/{uuid.uuid4()}/draft-mail")
        state = client.get(f"/api/meetings/{s.meeting_id}/protocol")
    assert resp.status_code == 503, resp.text
    assert not_draft.status_code == 409, not_draft.text
    assert not_draft.json()["code"] == "protocol_not_draft"
    assert missing.status_code == 404, missing.text
    assert state.json()["status"] == "draft"


async def test_approval_needs_a_final_protocol_and_another_meeting_of_the_gremium(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    draft = await seed(maker, status="closed", items=0, protocol="draft")
    s = await seed(maker, status="closed", items=0, protocol="final")
    foreign = await seed(maker, status="closed", items=0)
    async with maker() as session:
        nxt = Meeting(
            gremium_id=s.gremium_id, title="Folgesitzung", date=_date(2026, 7, 4), status="closed"
        )
        session.add(nxt)
        await session.commit()
    url = f"/api/protocols/{s.protocol_id}/approval"
    with TestClient(api) as client:
        on_draft = client.put(
            f"/api/protocols/{draft.protocol_id}/approval", json={"meetingId": str(nxt.id)}
        )
        own = client.put(url, json={"meetingId": str(s.meeting_id)})
        other_gremium = client.put(url, json={"meetingId": str(foreign.meeting_id)})
        unknown = client.put(url, json={"meetingId": str(uuid.uuid4())})
        no_mark = client.delete(url)
        marked = client.put(url, json={"meetingId": str(nxt.id)})
        read = client.get(f"/api/meetings/{s.meeting_id}/protocol")
        listed = client.get(f"/api/committees/{s.gremium_id}/meetings")
        removed = client.delete(url)
    assert on_draft.status_code == 409, on_draft.text
    assert on_draft.json()["code"] == "protocol_not_final"
    for refused in (own, other_gremium, unknown):
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "invalid_approval_meeting"
    assert no_mark.status_code == 200, no_mark.text
    assert no_mark.json()["approvedAt"] is None
    assert marked.status_code == 200, marked.text
    body = marked.json()
    assert body["approvedAt"] is not None
    assert body["approvedMeetingId"] == str(nxt.id)
    assert (body["approvedMeetingTitle"], body["approvedMeetingDate"]) == (
        "Folgesitzung",
        "2026-07-04",
    )
    assert read.json()["approvedMeetingId"] == str(nxt.id)
    rows = {m["id"]: m for m in listed.json()}
    assert rows[str(s.meeting_id)]["protocolApproved"] is True
    assert rows[str(nxt.id)]["protocolApproved"] is False
    assert removed.status_code == 200, removed.text
    assert removed.json()["approvedMeetingId"] is None
    marks = [
        e.data["approvedMeetingId"]
        for e in await audit_actions(maker, target_id=s.protocol_id)
        if e.action == "protocol_approval"
    ]
    assert marks == [str(nxt.id), None]
