"""Integration (echte Postgres, testcontainers): nicht-öffentliche TOPs (#PII-Re-Add).

Beweist gegen das migrierte Schema:
* ``_assemble_from_agenda(public=False)`` enthält den Body des nicht-öffentlichen TOP;
* ``_assemble_from_agenda(public=True)`` ersetzt ihn durch den Platzhalter, behält aber
  die ``#``-Überschrift (TOP-Nummerierung bleibt stabil — beide Varianten haben gleich
  viele Top-Level-Überschriften);
* ``_has_non_public`` erkennt den nicht-öffentlichen TOP;
* der Dual-Render in ``finalize`` legt **beide** PDFs an (intern + öffentlich), das
  interne Markdown trägt den TOP-Body, das öffentliche den Platzhalter, und per Mail geht
  ausschließlich die öffentliche Variante.

Fakes (Storage/pytex/Mail) werden lokal gebaut: ``finalize`` braucht ein vorhandenes,
deterministisches Backend, das die übergebenen Markdown-Bytes mitschreibt.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import Gremium, MailList
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
# Der nicht-öffentliche TOP-Titel kann den sensiblen Gegenstand kodieren (AUD-025) und
# darf nicht in der öffentlichen Variante auftauchen.
_SECRET_TITLE = "Personalangelegenheit"
_NEUTRAL_HEADING = "Nicht-öffentlicher Tagesordnungspunkt"
# Die vollständige Anwesenheits-Liste + der Protokollant einer (potenziell
# nicht-öffentlichen) Sitzung sind Metadaten, die der ``non_public``-Flag schützen soll
# (AUD-025) — sie dürfen nicht in die an die Verteilerliste gemailte Variante.
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
    """Object-Storage-Fake: protokolliert put/get/remove, hält die Bytes je Key."""

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
    """pytex-Fake: deterministische Bytes je Render + mitgeschriebenes Markdown."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        # Pro Render mitgeschriebener ``trust_level``; ``None`` = Default (= ``trusted``
        # im Client). Der Protokoll-Pfad nutzt den Default (RCE-Schutz im Sanitizer).
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
        # deterministisch + je Render unterscheidbar (Index in der Call-Liste).
        return f"%PDF-{len(self.calls)}::{markdown}".encode()


class _FakeMailQueue:
    def __init__(self) -> None:
        self.sent: list[MailMessage] = []

    async def enqueue(self, msg: MailMessage) -> None:
        self.sent.append(msg)


async def _seed_meeting(
    session: AsyncSession, *, secret_body: str = _SECRET_BODY
) -> tuple[Meeting, Gremium]:
    """Sitzung (live) mit zwei TOPs — der zweite nicht-öffentlich mit Body.

    Zusätzlich werden ein Protokollant sowie je ein anwesendes/abwesendes Mitglied
    angelegt, damit die Header-Redaktion der öffentlichen Variante (AUD-025) prüfbar
    ist: deren Namen dürfen intern, aber nicht öffentlich erscheinen."""
    gremium = Gremium(name="StuPa", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    protokollant = Principal(sub=f"prot-{uuid.uuid4()}", display_name=_PROTOKOLLANT_NAME)
    present_member = Principal(sub=f"pres-{uuid.uuid4()}", display_name=_PRESENT_NAME)
    absent_member = Principal(sub=f"abs-{uuid.uuid4()}", display_name=_ABSENT_NAME)
    session.add_all([protokollant, present_member, absent_member])
    await session.flush()
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


# --------------------------------------------------------------------------- #
# 7a — Redaktions-Logik (_assemble_from_agenda / _has_non_public)
# --------------------------------------------------------------------------- #
async def test_assemble_redacts_non_public_keeps_numbering(session: AsyncSession) -> None:
    meeting, _ = await _seed_meeting(session)
    svc = ProtocolService(session)

    internal = await svc._assemble_from_agenda(meeting.id, public=False)
    public = await svc._assemble_from_agenda(meeting.id, public=True)

    # intern: der vertrauliche Body steht drin; öffentlich: ersetzt durch Platzhalter.
    assert _SECRET_BODY in internal
    assert _NON_PUBLIC_PLACEHOLDER not in internal
    assert _SECRET_BODY not in public
    assert _NON_PUBLIC_PLACEHOLDER in public

    # AUD-025: der nicht-öffentliche TOP-Titel bleibt intern, fehlt aber in der
    # öffentlichen (an den Verteiler gemailten) Variante; dort steht eine neutrale
    # Überschrift.
    assert _SECRET_TITLE in internal
    assert _SECRET_TITLE not in public
    assert _NEUTRAL_HEADING in public

    # Nummerierung stabil: gleich viele Top-Level-Überschriften in beiden Varianten.
    assert _count_top_headings(internal) == _count_top_headings(public) == 2

    assert await svc._has_non_public(meeting.id) is True


async def test_build_document_redacts_roster_and_protokollant_in_public(
    session: AsyncSession,
) -> None:
    """AUD-025 (roster vector): _build_document(public=True) darf weder die
    Anwesenheits-/Abwesenheits-Namen noch den Protokollanten-Namen enthalten — diese
    Metadaten gehen sonst verbatim an die externe Verteilerliste. Intern bleiben sie."""
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

    # intern: Namen + Protokollant stehen im Header.
    assert _PRESENT_NAME in internal
    assert _ABSENT_NAME in internal
    assert _PROTOKOLLANT_NAME in internal

    # öffentlich: keine Namen, kein Protokollant — nur die Zähler bleiben.
    assert _PRESENT_NAME not in public
    assert _ABSENT_NAME not in public
    assert _PROTOKOLLANT_NAME not in public
    assert "Anwesend: 1" in public
    assert "Abwesend: 1" in public

    # Beschlussfähigkeit (zähler-basiert) bleibt in beiden Varianten aussagekräftig.
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


# --------------------------------------------------------------------------- #
# 7b — Dual-Render finalize
# --------------------------------------------------------------------------- #
async def test_finalize_dual_render(session: AsyncSession) -> None:
    meeting, gremium = await _seed_meeting(session)
    # Verteiler, damit die Mail tatsächlich enqueued wird (sonst leere Empfängerliste).
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
    # beide PDFs angelegt.
    assert refreshed.pdf_storage_key is not None
    assert refreshed.public_pdf_storage_key is not None
    assert refreshed.pdf_storage_key != refreshed.public_pdf_storage_key

    internal_bytes = storage.blobs[refreshed.pdf_storage_key]
    public_bytes = storage.blobs[refreshed.public_pdf_storage_key]

    # internes PDF enthält den vertraulichen Body, öffentliches den Platzhalter.
    assert _SECRET_BODY.encode() in internal_bytes
    assert _NON_PUBLIC_PLACEHOLDER.encode() in public_bytes
    assert _SECRET_BODY.encode() not in public_bytes

    # AUD-025: der nicht-öffentliche Titel steht intern, fehlt im gemailten PDF.
    assert _SECRET_TITLE.encode() in internal_bytes
    assert _SECRET_TITLE.encode() not in public_bytes

    # AUD-025 (roster vector): Anwesenheits-/Abwesenheits-Namen + Protokollant stehen
    # intern, fehlen aber im an die Verteilerliste gemailten öffentlichen PDF.
    assert _PRESENT_NAME.encode() in internal_bytes
    assert _ABSENT_NAME.encode() in internal_bytes
    assert _PROTOKOLLANT_NAME.encode() in internal_bytes
    assert _PRESENT_NAME.encode() not in public_bytes
    assert _ABSENT_NAME.encode() not in public_bytes
    assert _PROTOKOLLANT_NAME.encode() not in public_bytes

    # genau eine Mail, und ihr Anhang == öffentliche Variante (nie das interne PDF).
    assert len(mail_queue.sent) == 1
    msg = mail_queue.sent[0]
    assert len(msg.attachments) == 1
    assert msg.attachments[0].content == public_bytes
    assert msg.attachments[0].content != internal_bytes
