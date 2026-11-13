"""The Antrag of a TOP as an Anlage of the protocol, on a real Postgres.

§ F/meetings/protocols/000884 a TOP of an Antrag prints the reference below its heading,
and the render gets the Antrag PDF as the asset of that reference. § 000885 the Anlage
holds the version from the vote opening, else from the close of the TOP; a later edit
does not change it. § 000886 the public Anlage prints the ``isPII`` answers and the
applicant as a black bar, and a non-public TOP has no Anlage there.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import Engine, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.service.forms import FormVersionWriter
from app.modules.applications.models import Application, SubmissionVersion
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.documents.application_markdown import BAR, field_row
from app.modules.documents.service import ApplicationPdfService, anlage_id
from app.modules.files.storage import ObjectStorage
from app.modules.forms.schemas import FormVersionCreate
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.meetings.protocol_models import Protocol
from app.modules.pdf.typst_client import TypstClient, TypstError
from app.modules.protocol.service import ProtocolService
from app.modules.voting.models import Vote
from app.settings import get_settings
from app.shared.config_schemas import FormFieldDef
from tests._support.guest_apps import GuestSeed, seed_guest_flow

pytestmark = pytest.mark.integration

_IBAN = "DE02120300000000202051"


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
async def seed(maker: async_sessionmaker[AsyncSession]) -> GuestSeed:
    seed = await seed_guest_flow(maker)
    async with maker() as session:
        await FormVersionWriter(session).create_form_version(
            seed.type_id,
            FormVersionCreate(
                fields=[
                    FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
                    FormFieldDef(key="zweck", type="text", label={"de": "Zweck"}),
                    FormFieldDef.model_validate(
                        {"key": "iban", "type": "text", "label": {"de": "IBAN"}, "isPII": True}
                    ),
                ],
                activate=True,
            ),
            "tester",
        )
    return seed


class _Storage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def remove(self, key: str) -> None:
        self.blobs.pop(key, None)


@dataclass
class _Typst:
    """Record each render; an Antrag render answers its Markdown as the PDF bytes."""

    calls: list[tuple[str, Mapping[str, bytes]]] = field(
        default_factory=list[tuple[str, Mapping[str, bytes]]]
    )
    fail_antrag: bool = False

    async def render_pdf(
        self,
        markdown: str,
        *,
        variant: str | None = None,
        config: Mapping[str, object] | None = None,
        assets: Mapping[str, bytes] | None = None,
    ) -> bytes:
        if self.fail_antrag and "typ: antrag" in markdown:
            raise TypstError("down", retryable=True)
        self.calls.append((markdown, dict(assets or {})))
        return markdown.encode()


async def _application(session: AsyncSession, seed: GuestSeed, *, zweck: str) -> uuid.UUID:
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(seed.type_id),
            "data": {"title": "Druckauftrag Plakate", "zweck": zweck, "iban": _IBAN},
            "applicantEmail": "luis@example.org",
            "applicantName": "Luis Meyer",
        }
    )
    app, _ = await ApplicationsService(session).create(
        payload, actor="owner-sub", email_confirmed=True
    )
    return app.id


async def _edit(session: AsyncSession, app_id: uuid.UUID, zweck: str, at: datetime) -> None:
    """Write version 2 of the Antrag at `at`, the way an edit does."""
    app = await session.get(Application, app_id)
    assert app is not None
    data = {**app.data, "zweck": zweck}
    session.add(SubmissionVersion(application_id=app_id, version=2, data=data, at=at))
    await session.execute(update(Application).where(Application.id == app_id).values(data=data))
    await session.commit()


async def _versions_at(session: AsyncSession, app_id: uuid.UUID, at: datetime) -> None:
    await session.execute(
        update(SubmissionVersion).where(SubmissionVersion.application_id == app_id).values(at=at)
    )
    await session.commit()


async def _meeting(
    session: AsyncSession, seed: GuestSeed, items: list[tuple[uuid.UUID, bool, datetime | None]]
) -> tuple[Protocol, list[MeetingAgendaItem]]:
    meeting = Meeting(gremium_id=seed.gremium_id, title="Sitzung", status="live")
    session.add(meeting)
    await session.flush()
    rows = [
        MeetingAgendaItem(
            meeting_id=meeting.id,
            application_id=app_id,
            position=n,
            non_public=non_public,
            done_at=done_at,
        )
        for n, (app_id, non_public, done_at) in enumerate(items)
    ]
    session.add_all(rows)
    protocol = Protocol(
        meeting_id=meeting.id, gremium_id=seed.gremium_id, markdown="", status="draft"
    )
    session.add(protocol)
    await session.commit()
    return protocol, rows


def _antrag_calls(typst: _Typst) -> list[str]:
    return [md for md, _ in typst.calls if "typ: antrag" in md]


def _protocol_calls(typst: _Typst) -> list[tuple[str, Mapping[str, bytes]]]:
    return [(md, a) for md, a in typst.calls if "typ: antrag" not in md]


async def test_the_protocol_appends_the_antrag_as_it_was_at_the_close_of_the_top(
    maker: async_sessionmaker[AsyncSession], seed: GuestSeed
) -> None:
    """§ 000884 + § 000885 + § 000886: reference, asset, frozen version, public black bar."""
    start = datetime.now(UTC) - timedelta(hours=2)
    async with maker() as session:
        open_id = await _application(session, seed, zweck="alte Fassung")
        secret_id = await _application(session, seed, zweck="geheim")
        await _versions_at(session, open_id, start)
        tops = [
            (open_id, False, start + timedelta(minutes=30)),
            (secret_id, True, None),
        ]
        protocol, (open_item, secret_item) = await _meeting(session, seed, tops)
        await _edit(session, open_id, "neue Fassung", start + timedelta(hours=1))

        typst = _Typst()
        svc = ProtocolService(
            session,
            storage=cast("ObjectStorage", _Storage()),
            typst=cast("TypstClient", typst),
        )
        await svc.finalize(protocol.id, now=datetime.now(UTC))

    (internal_md, internal_assets), (public_md, public_assets) = _protocol_calls(typst)
    internal_ref = f"/api/media/documents/{anlage_id(open_item.id, public=False)}"
    public_ref = f"/api/media/documents/{anlage_id(open_item.id, public=True)}"
    assert f"[Antrag Druckauftrag Plakate]({internal_ref})" in internal_md
    assert f"[Antrag Druckauftrag Plakate]({public_ref})" in public_md
    secret_internal = anlage_id(secret_item.id, public=False)
    secret_public = anlage_id(secret_item.id, public=True)
    assert f"doc-{secret_internal}.pdf" in internal_assets
    assert f"doc-{secret_public}.pdf" not in public_assets
    assert str(secret_public) not in public_md

    internal_antrag = internal_assets[f"doc-{anlage_id(open_item.id, public=False)}.pdf"].decode()
    public_antrag = public_assets[f"doc-{anlage_id(open_item.id, public=True)}.pdf"].decode()
    assert "alte Fassung" in internal_antrag and "neue Fassung" not in internal_antrag
    assert "\n".join(field_row("Version", ["`1`"])) in internal_antrag
    assert _IBAN in internal_antrag and "Luis Meyer" in internal_antrag
    assert "[!feld] Status" not in internal_antrag and "# Beschluss" not in internal_antrag
    assert _IBAN not in public_antrag and "Luis Meyer" not in public_antrag
    assert "\n".join(field_row("IBAN", [BAR])) in public_antrag
    assert "\n".join(field_row("Antragsteller", [BAR])) in public_antrag


async def test_the_vote_opening_fixes_the_version(
    maker: async_sessionmaker[AsyncSession], seed: GuestSeed
) -> None:
    """§ 000885: the last vote that opened decides, a cancelled one does not count."""
    start = datetime.now(UTC) - timedelta(hours=3)
    async with maker() as session:
        app_id = await _application(session, seed, zweck="v1")
        await _versions_at(session, app_id, start)
        _, (item,) = await _meeting(session, seed, [(app_id, False, None)])
        pdfs = ApplicationPdfService(session, storage=None, typst=None, settings=get_settings())
        assert await pdfs.frozen_version(item) is None

        await _edit(session, app_id, "v2", start + timedelta(hours=2))
        common = {
            "application_id": app_id,
            "agenda_item_id": item.id,
            "eligible_group": "gremium",
            "config": {},
        }
        session.add_all(
            [
                Vote(**common, status="closed", opens_at=start + timedelta(hours=1)),
                Vote(**common, status="cancelled", opens_at=start + timedelta(hours=2, minutes=5)),
            ]
        )
        await session.commit()
        assert await pdfs.frozen_version(item) == 1

        no_app = MeetingAgendaItem(meeting_id=item.meeting_id, title="Frei", position=9)
        assert await pdfs.frozen_version(no_app) is None


async def test_an_antrag_that_does_not_render_leaves_the_protocol_whole(
    maker: async_sessionmaker[AsyncSession], seed: GuestSeed
) -> None:
    """§ 000868: the Anlage is left out, the protocol still renders with its reference."""
    async with maker() as session:
        app_id = await _application(session, seed, zweck="x")
        protocol, (item,) = await _meeting(session, seed, [(app_id, False, None)])
        typst = _Typst(fail_antrag=True)
        svc = ProtocolService(
            session,
            storage=cast("ObjectStorage", _Storage()),
            typst=cast("TypstClient", typst),
        )
        await svc.finalize(protocol.id, now=datetime.now(UTC))

    ((internal_md, internal_assets),) = _protocol_calls(typst)
    assert str(anlage_id(item.id, public=False)) in internal_md
    assert not any(name.startswith("doc-") for name in internal_assets)
    assert _antrag_calls(typst) == []
