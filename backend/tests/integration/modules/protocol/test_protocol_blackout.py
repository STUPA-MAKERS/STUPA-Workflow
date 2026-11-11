"""Integration tests of the blackout marks in a protocol (specs 000686, 000687, 000691).

A TOP body and the free text mark a name as `%%Name%%`. The internal document keeps
the mark, so the render service prints the name as plain text. The public document,
the public snapshot and the mailed PDF hold the empty marker `%%%%` only. A mark makes
the finalize render the public PDF and mail it, as a non-public TOP does. An open
marker stops the finalize with `blackout_unclosed`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.files.storage import ObjectStorage
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.meetings.protocol_models import Protocol
from app.modules.notifications.mail import MailMessage
from app.modules.pdf.typst_client import TypstClient
from app.modules.protocol.public import PublicSnapshot
from app.modules.protocol.service import ProtocolService
from app.shared.errors import ValidationProblem

pytestmark = pytest.mark.integration

_NAME = "Lena Hoffmann"
_FREE_NAME = "Jonas Weber"


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


class _FakeStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def remove(self, key: str) -> None:
        self.blobs.pop(key, None)


class _FakeTypst:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def render_pdf(
        self,
        markdown: str,
        *,
        variant: str | None = None,
        config: Mapping[str, object] | None = None,
        assets: Mapping[str, bytes] | None = None,
    ) -> bytes:
        self.calls.append(markdown)
        return f"%PDF-{len(self.calls)}::{markdown}".encode()


class _FakeMailQueue:
    def __init__(self) -> None:
        self.sent: list[MailMessage] = []

    async def enqueue(self, msg: MailMessage) -> None:
        self.sent.append(msg)


async def _seed(
    session: AsyncSession,
    *,
    body: str = f"Die Antragstellerin %%{_NAME}%% stellt den Antrag vor.",
    status: str = "live",
    agenda: bool = True,
    free_text: str = "",
) -> Protocol:
    """Create a gremium that does not publish, a meeting with one public TOP, and its protocol."""
    gremium = Gremium(name="StuPa", slug=f"g-{uuid.uuid4()}")
    gremium.protocol_recipients = ["verteiler@example.org"]
    session.add(gremium)
    await session.flush()
    meeting = Meeting(gremium_id=gremium.id, title="Sitzung", status=status)
    session.add(meeting)
    await session.flush()
    if agenda:
        session.add(
            MeetingAgendaItem(
                meeting_id=meeting.id, title="Antrag", body=body, position=0, non_public=False
            )
        )
    protocol = Protocol(
        meeting_id=meeting.id, gremium_id=gremium.id, markdown=free_text, status="draft"
    )
    session.add(protocol)
    await session.commit()
    return protocol


async def test_public_document_and_snapshot_black_out_the_name(session: AsyncSession) -> None:
    """§000687: the internal document keeps the mark, the public variants hold the bar."""
    protocol = await _seed(session)
    svc = ProtocolService(session)

    internal = await svc._build_document(protocol, public=False)
    snapshot = PublicSnapshot()
    public = await svc._build_document(protocol, public=True, snapshot=snapshot)

    assert f"%%{_NAME}%%" in internal
    assert _NAME not in public
    assert "%%%% stellt den Antrag vor." in public
    assert _NAME not in snapshot.search_text()
    assert snapshot.tops[0].markdown == "Die Antragstellerin %%%% stellt den Antrag vor."


async def test_public_free_text_blacks_out_the_name(session: AsyncSession) -> None:
    """§000687: a protocol without TOPs blacks out its free text too."""
    protocol = await _seed(session, agenda=False, free_text=f"Protokoll: %%{_FREE_NAME}%%.")
    snapshot = PublicSnapshot()
    public = await ProtocolService(session)._build_document(
        protocol, public=True, snapshot=snapshot
    )
    assert _FREE_NAME not in public
    assert snapshot.markdown == "Protokoll: %%%%."


async def test_finalize_with_a_mark_mails_the_public_pdf(session: AsyncSession) -> None:
    """§000691: a mark renders both PDFs and mails only the public one."""
    protocol = await _seed(session)
    storage = _FakeStorage()
    mail_queue = _FakeMailQueue()
    svc = ProtocolService(
        session,
        storage=cast("ObjectStorage", storage),
        typst=cast("TypstClient", _FakeTypst()),
        mail_queue=mail_queue,
    )

    await svc.finalize(protocol.id, now=datetime.now(UTC))

    refreshed = await session.get(Protocol, protocol.id)
    assert refreshed is not None and refreshed.public_pdf_storage_key is not None
    assert refreshed.pdf_storage_key is not None
    assert _NAME.encode() in storage.blobs[refreshed.pdf_storage_key]
    assert _NAME.encode() not in storage.blobs[refreshed.public_pdf_storage_key]
    assert len(mail_queue.sent) == 1
    attachments = mail_queue.sent[0].attachments or []
    assert attachments
    assert all(_NAME.encode() not in a.content for a in attachments)


async def test_finalize_without_a_mark_mails_the_internal_pdf(session: AsyncSession) -> None:
    """§000691: without a mark and without a public gremium only the internal PDF exists."""
    protocol = await _seed(session, body="Ein Text ohne Namen.")
    storage = _FakeStorage()
    svc = ProtocolService(
        session,
        storage=cast("ObjectStorage", storage),
        typst=cast("TypstClient", _FakeTypst()),
        mail_queue=_FakeMailQueue(),
    )
    await svc.finalize(protocol.id, now=datetime.now(UTC))
    refreshed = await session.get(Protocol, protocol.id)
    assert refreshed is not None and refreshed.public_pdf_storage_key is None


async def test_start_finalize_refuses_an_open_marker(session: AsyncSession) -> None:
    """§000686: an open marker stops the finalize and names the TOP."""
    protocol = await _seed(session, body="%%Lena Hoffmann stellt vor.", status="closed")
    with pytest.raises(ValidationProblem) as caught:
        await ProtocolService(session).start_finalize(protocol.id, actor="test")
    assert caught.value.code == "blackout_unclosed"
    assert caught.value.detail is not None and "TOP 1" in caught.value.detail
    refreshed = await session.get(Protocol, protocol.id)
    assert refreshed is not None
    await session.refresh(refreshed)
    assert refreshed.status == "draft"


async def test_start_finalize_refuses_an_open_marker_in_the_free_text(
    session: AsyncSession,
) -> None:
    """§000686: the free text is checked as well."""
    protocol = await _seed(session, agenda=False, free_text="%%offen", status="closed")
    with pytest.raises(ValidationProblem) as caught:
        await ProtocolService(session).start_finalize(protocol.id, actor="test")
    assert caught.value.errors is not None and caught.value.errors[0].field == "text"
