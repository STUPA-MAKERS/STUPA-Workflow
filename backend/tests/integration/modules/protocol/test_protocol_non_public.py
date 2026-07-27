"""Integration test for non-public agenda items (#PII-Re-Add).

The test uses a real Postgres from testcontainers and checks the migrated schema.

`_assemble_from_agenda(public=False)` keeps the body of the non-public agenda item.
`_assemble_from_agenda(public=True)` replaces that body with the placeholder. It keeps
the `#` heading, so the numbering of the agenda items stays stable. Both variants have
the same number of top-level headings. `_has_non_public` finds the non-public agenda
item.

The dual render in `finalize` writes both PDFs, the internal one and the public one. The
internal Markdown carries the body of the agenda item. The public Markdown carries the
placeholder. The mail carries the public variant only.

The test builds local fakes for storage, pytex and mail. `finalize` needs a
deterministic backend that records the Markdown bytes it gets.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import (
    Gremium,
    GremiumMembership,
    GremiumRole,
    MailList,
)
from app.modules.auth.models import Principal
from app.modules.files.storage import ObjectStorage
from app.modules.livevote.models import Meeting, MeetingAgendaItem, MeetingAttendance
from app.modules.notifications.mail import MailMessage
from app.modules.pdf.pytex_client import PytexClient
from app.modules.protocol.models import Protocol
from app.modules.protocol.service import ProtocolService

pytestmark = pytest.mark.integration

_NON_PUBLIC_PLACEHOLDER = "(nicht-öffentlicher Tagesordnungspunkt)"
_SECRET_BODY = "Personalentscheidung zu Frau Müller — vertraulich."
# The title of a non-public agenda item can encode the sensitive subject (AUD-025).
# It must not appear in the public variant.
_SECRET_TITLE = "Personalangelegenheit"
_NEUTRAL_HEADING = "Nicht-öffentlicher Tagesordnungspunkt"
# The full attendance list and the minute taker of a meeting are metadata that the
# `non_public` flag protects (AUD-025). They must not reach the variant that goes to
# the mailing list.
_PRESENT_NAME = "Anna Anwesend"
_ABSENT_NAME = "Bernd Abwesend"
_PROTOKOLLANT_NAME = "Petra Protokoll"


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


class _FakeStorage:
    """Fake object storage that keeps bytes per key and records every call."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.removed: list[str] = []

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.puts.append(key)
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def remove(self, key: str) -> None:
        self.removed.append(key)
        self.blobs.pop(key, None)


class _FakePytex:
    """Fake pytex client that returns deterministic bytes and records the Markdown."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        # The `trust_level` of each render. `None` means the client default, which is
        # `trusted`. The protocol path uses that default. The sanitizer holds the RCE
        # protection.
        self.trust_levels: list[str | None] = []

    async def render_pdf(
        self,
        markdown: str,
        *,
        variant: str | None = None,
        trust_level: str | None = None,
    ) -> bytes:
        self.calls.append(markdown)
        self.trust_levels.append(trust_level)
        # The call index makes the bytes different for each render.
        return f"%PDF-{len(self.calls)}::{markdown}".encode()


class _FakeMailQueue:
    def __init__(self) -> None:
        self.sent: list[MailMessage] = []

    async def enqueue(self, msg: MailMessage) -> None:
        self.sent.append(msg)


async def _seed_meeting(
    session: AsyncSession, *, secret_body: str = _SECRET_BODY
) -> tuple[Meeting, Gremium]:
    """Create a live meeting with two agenda items.

    The second agenda item is non-public and carries a body. The function also creates a
    minute taker, one present member and one absent member. Their names must appear in
    the internal variant but not in the public one. This makes the header redaction of
    the public variant testable (AUD-025).
    """
    gremium = Gremium(name="StuPa", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    protokollant = Principal(sub=f"prot-{uuid.uuid4()}", display_name=_PROTOKOLLANT_NAME)
    present_member = Principal(sub=f"pres-{uuid.uuid4()}", display_name=_PRESENT_NAME)
    absent_member = Principal(sub=f"abs-{uuid.uuid4()}", display_name=_ABSENT_NAME)
    session.add_all([protokollant, present_member, absent_member])
    await session.flush()
    # Both members need a Gremium membership. Without it the service cannot compute
    # the quorum, which counts present members against active members. `_quorate`
    # then returns `None` and both variants lose the front matter line.
    role = GremiumRole(
        gremium_id=gremium.id,
        key=f"r-{uuid.uuid4()}",
        name_i18n={"de": "Mitglied"},
        permissions=["vote.cast"],
    )
    session.add(role)
    await session.flush()
    session.add_all(
        [
            GremiumMembership(
                principal_id=present_member.id,
                gremium_id=gremium.id,
                gremium_role_id=role.id,
            ),
            GremiumMembership(
                principal_id=absent_member.id,
                gremium_id=gremium.id,
                gremium_role_id=role.id,
            ),
        ]
    )
    meeting = Meeting(
        gremium_id=gremium.id,
        title="Sitzung",
        status="live",
        protokollant_id=protokollant.id,
    )
    session.add(meeting)
    await session.flush()
    session.add_all(
        [
            MeetingAttendance(
                meeting_id=meeting.id,
                principal_id=present_member.id,
                status="present",
            ),
            MeetingAttendance(
                meeting_id=meeting.id,
                principal_id=absent_member.id,
                status="absent",
            ),
        ]
    )
    session.add_all(
        [
            MeetingAgendaItem(
                meeting_id=meeting.id,
                title="Bericht des Vorstands",
                body="Alles bestens.",
                position=0,
                non_public=False,
            ),
            MeetingAgendaItem(
                meeting_id=meeting.id,
                title=_SECRET_TITLE,
                body=secret_body,
                position=1,
                non_public=True,
            ),
        ]
    )
    await session.commit()
    return meeting, gremium


def _count_top_headings(markdown: str) -> int:
    return sum(1 for line in markdown.splitlines() if line.startswith("# "))


async def test_assemble_redacts_non_public_keeps_numbering(session: AsyncSession) -> None:
    meeting, _ = await _seed_meeting(session)
    svc = ProtocolService(session)

    internal = await svc._assemble_from_agenda(meeting.id, public=False)
    public = await svc._assemble_from_agenda(meeting.id, public=True)

    assert _SECRET_BODY in internal
    assert _NON_PUBLIC_PLACEHOLDER not in internal
    assert _SECRET_BODY not in public
    assert _NON_PUBLIC_PLACEHOLDER in public

    # AUD-025: the non-public title stays in the internal variant. The public variant
    # goes to the mailing list and shows a neutral heading instead.
    assert _SECRET_TITLE in internal
    assert _SECRET_TITLE not in public
    assert _NEUTRAL_HEADING in public

    assert _count_top_headings(internal) == _count_top_headings(public) == 2

    assert await svc._has_non_public(meeting.id) is True


async def test_build_document_redacts_roster_and_protokollant_in_public(
    session: AsyncSession,
) -> None:
    """Redact the roster and the minute taker in the public document (AUD-025).

    `_build_document(public=True)` must not contain the names of the present or absent
    members. It must also not contain the name of the minute taker. These metadata
    otherwise go verbatim to the external mailing list. The internal document keeps them.
    """
    meeting, gremium = await _seed_meeting(session)
    protocol = Protocol(
        meeting_id=meeting.id,
        gremium_id=gremium.id,
        markdown="",
        status="draft",
    )
    session.add(protocol)
    await session.commit()

    svc = ProtocolService(session)
    internal = await svc._build_document(protocol, public=False)
    public = await svc._build_document(protocol, public=True)

    assert _PRESENT_NAME in internal
    assert _ABSENT_NAME in internal
    assert _PROTOKOLLANT_NAME in internal

    assert _PRESENT_NAME not in public
    assert _ABSENT_NAME not in public
    assert _PROTOKOLLANT_NAME not in public
    assert "Anwesend: 1" in public
    assert "Abwesend: 1" in public

    # The quorum line counts members, so it stays meaningful in both variants.
    assert "beschlussfaehigkeit" in internal
    assert "beschlussfaehigkeit" in public


async def test_has_non_public_false_without_secret_top(session: AsyncSession) -> None:
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    meeting = Meeting(gremium_id=gremium.id, title="Offen", status="live")
    session.add(meeting)
    await session.flush()
    session.add(
        MeetingAgendaItem(
            meeting_id=meeting.id, title="TOP", body="x", position=0, non_public=False
        )
    )
    await session.commit()

    svc = ProtocolService(session)
    assert await svc._has_non_public(meeting.id) is False


async def test_finalize_dual_render(session: AsyncSession) -> None:
    meeting, gremium = await _seed_meeting(session)
    # The mailing list makes the service enqueue the mail. Without it the recipient
    # list is empty.
    session.add(
        MailList(
            gremium_id=gremium.id,
            name="Verteiler",
            recipients=["verteiler@example.org"],
            active=True,
        )
    )
    protocol = Protocol(
        meeting_id=meeting.id,
        gremium_id=gremium.id,
        markdown="",
        status="draft",
    )
    session.add(protocol)
    await session.commit()

    storage = _FakeStorage()
    pytex = _FakePytex()
    mail_queue = _FakeMailQueue()
    svc = ProtocolService(
        session,
        storage=cast("ObjectStorage", storage),
        pytex=cast("PytexClient", pytex),
        mail_queue=mail_queue,  # pyright: ignore[reportArgumentType]
    )

    await svc.finalize(protocol.id, now=datetime.now(UTC))

    refreshed = await session.get(Protocol, protocol.id)
    assert refreshed is not None
    assert refreshed.status == "final"
    assert refreshed.pdf_storage_key is not None
    assert refreshed.public_pdf_storage_key is not None
    assert refreshed.pdf_storage_key != refreshed.public_pdf_storage_key

    internal_bytes = storage.blobs[refreshed.pdf_storage_key]
    public_bytes = storage.blobs[refreshed.public_pdf_storage_key]

    assert _SECRET_BODY.encode() in internal_bytes
    assert _NON_PUBLIC_PLACEHOLDER.encode() in public_bytes
    assert _SECRET_BODY.encode() not in public_bytes

    # AUD-025: the non-public title stays in the internal PDF and is absent from the
    # mailed PDF.
    assert _SECRET_TITLE.encode() in internal_bytes
    assert _SECRET_TITLE.encode() not in public_bytes

    # AUD-025 (roster vector): the attendance names and the minute taker stay in the
    # internal PDF. They are absent from the public PDF that goes to the mailing list.
    assert _PRESENT_NAME.encode() in internal_bytes
    assert _ABSENT_NAME.encode() in internal_bytes
    assert _PROTOKOLLANT_NAME.encode() in internal_bytes
    assert _PRESENT_NAME.encode() not in public_bytes
    assert _ABSENT_NAME.encode() not in public_bytes
    assert _PROTOKOLLANT_NAME.encode() not in public_bytes

    # Exactly one mail goes out. Its attachment is the public variant, never the
    # internal PDF.
    assert len(mail_queue.sent) == 1
    msg = mail_queue.sent[0]
    assert len(msg.attachments) == 1
    assert msg.attachments[0].content == public_bytes
    assert msg.attachments[0].content != internal_bytes
