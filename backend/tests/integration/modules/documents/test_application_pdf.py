"""The PDF export of an Antrag on a real Postgres.

§ F/applications/applications/000880 a reader of the Antrag downloads it, a stranger gets
the gate of the detail page. § 000882 the PDF of an observer has no ``isPII`` answer and
no applicant e-mail. § 000883 the download name is ``Antrag_<Titel>_<Datum>.pdf``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_applicant, get_current_principal, get_session
from app.modules.admin.service.forms import FormVersionWriter
from app.modules.applications.models import ApplicationDecision
from app.modules.applications.router import get_comment_mail_sender, get_magic_link_sender
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth.principal import Applicant, Principal
from app.modules.documents.application_markdown import field_row
from app.modules.documents.router import get_pdf_service
from app.modules.documents.service import ApplicationPdfService
from app.modules.forms.schemas import FormVersionCreate
from app.modules.pdf.typst_client import TypstError
from app.modules.voting.models import Vote
from app.settings import Settings
from app.shared.config_schemas import FormFieldDef
from tests._support.guest_apps import GuestSeed, build_api, guest_settings, seed_guest_flow

pytestmark = pytest.mark.integration

_OWNER = Principal(sub="owner-sub", roles=["member"], email="luis@example.org", display_name="Luis")
_STRANGER = Principal(sub="other-sub", roles=["member"], email="other@example.org")
_READER = Principal(
    sub="reader-sub", roles=["member"], permissions={"application.read"}, email="r@example.org"
)
_ADRIAN = "adrian@example.org"


@dataclass
class FakeTypst:
    """Record the Markdown and answer a minimal PDF, or fail like the render service."""

    sources: list[str] = field(default_factory=list[str])
    error: TypstError | None = None

    async def render_pdf(
        self,
        markdown: str,
        *,
        variant: str | None = None,
        config: Mapping[str, object] | None = None,
        assets: Mapping[str, bytes] | None = None,
    ) -> bytes:
        if self.error is not None:
            raise self.error
        self.sources.append(markdown)
        return b"%PDF-1.7 fake"


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


async def _create(maker: async_sessionmaker[AsyncSession], seed: GuestSeed) -> uuid.UUID:
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(seed.type_id),
            "data": {
                "title": "Druckauftrag: Plakate",
                "zweck": "Werbung",
                "iban": "DE02120300000000202051",
            },
            "applicantEmail": _OWNER.email,
            "applicantName": "Luis Meyer",
        }
    )
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            payload, actor=_OWNER.sub, email_confirmed=True
        )
        return app.id


def _client(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    typst: FakeTypst,
    principal: Principal | None,
    applicant: Applicant | None = None,
) -> TestClient:
    async def _no_mail(*_args: object) -> None:
        return None

    api = build_api(migrated[1], settings, monkeypatch)

    async def _pdf_service() -> AsyncIterator[ApplicationPdfService]:
        async for session in api.dependency_overrides[get_session]():
            yield ApplicationPdfService(session, storage=None, typst=typst, settings=settings)  # type: ignore[arg-type]

    api.dependency_overrides[get_current_principal] = lambda: principal
    api.dependency_overrides[get_current_applicant] = lambda: applicant
    api.dependency_overrides[get_magic_link_sender] = lambda: _no_mail
    api.dependency_overrides[get_comment_mail_sender] = lambda: _no_mail
    api.dependency_overrides[get_pdf_service] = _pdf_service
    return TestClient(api)


async def test_a_reader_downloads_the_antrag_with_every_field(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 000880 + § 000883: the PDF streams with its name; the reader sees the PII field."""
    app_id = await _create(maker, seed)
    typst = FakeTypst()
    reader = _client(migrated, settings, monkeypatch, typst, _READER)
    response = reader.get(f"/api/applications/{app_id}/pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "Antrag_Druckauftrag_Plakate_" in disposition
    source = typst.sources[0]
    assert "typ: antrag" in source
    assert "\n".join(field_row("Zweck", ["Werbung"])) in source
    assert "DE02120300000000202051" in source
    mail = "[`luis@example.org`](mailto:luis@example.org)"
    assert "\n".join(field_row("Antragsteller", ["Luis Meyer\\", mail])) in source


async def test_the_decision_names_only_the_gremium_of_its_vote(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 000881: no Gremium in the head; the Beschluss names the Gremium of its vote."""
    app_id = await _create(maker, seed)
    typst = FakeTypst()
    reader = _client(migrated, settings, monkeypatch, typst, _READER)
    gremium = "\n".join(field_row("Gremium", ["G"]))

    async with maker() as session:
        manual = ApplicationDecision(application_id=app_id, decided_by="someone")
        session.add(manual)
        await session.commit()
    assert reader.get(f"/api/applications/{app_id}/pdf").status_code == 200
    assert "# Beschluss" in typst.sources[-1]
    assert "[!feld] Gremium" not in typst.sources[-1]

    async with maker() as session:
        vote = Vote(
            application_id=app_id, eligible_group=str(seed.gremium_id), config={}, status="closed"
        )
        session.add(vote)
        await session.flush()
        old = await session.get(ApplicationDecision, manual.id)
        assert old is not None
        old.superseded_at = datetime.now(UTC)
        await session.flush()
        session.add(ApplicationDecision(application_id=app_id, vote_id=vote.id))
        await session.commit()
    assert reader.get(f"/api/applications/{app_id}/pdf").status_code == 200
    source = typst.sources[-1]
    assert source.count("[!feld] Gremium") == 1
    assert source.index("# Beschluss") < source.index(gremium)


async def test_a_stranger_gets_the_gate_of_the_detail_page(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 000880: without read access there is no PDF and no render."""
    app_id = await _create(maker, seed)
    typst = FakeTypst()
    stranger = _client(migrated, settings, monkeypatch, typst, _STRANGER)
    assert stranger.get(f"/api/applications/{app_id}/pdf").status_code == 403
    missing = stranger.get(f"/api/applications/{uuid.uuid4()}/pdf")
    assert missing.status_code in {403, 404}
    assert typst.sources == []


async def test_an_observer_gets_no_pii_and_no_applicant_mail(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 000882: the observer PDF follows the observer view."""
    app_id = await _create(maker, seed)
    typst = FakeTypst()
    owner = _client(migrated, settings, monkeypatch, typst, _OWNER)
    assert owner.post(f"/api/applications/{app_id}/observers", json={"email": _ADRIAN}).is_success
    observer = _client(migrated, settings, monkeypatch, typst, None, Applicant(email=_ADRIAN))
    response = observer.get(f"/api/applications/{app_id}/pdf")
    assert response.status_code == 200, response.text
    source = typst.sources[-1]
    assert "DE02120300000000202051" not in source
    assert "\n".join(field_row("IBAN", ["(nicht sichtbar)"])) in source
    assert "luis@example.org" not in source
    assert "\n".join(field_row("Antragsteller", ["Luis Meyer"])) in source


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (TypstError("bad", status=400, retryable=False), 400),
        (TypstError("down", retryable=True), 503),
    ],
)
async def test_a_render_error_is_a_problem(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
    error: TypstError,
    status: int,
) -> None:
    """A refused render is 400, a short outage is 503, both as problem+json."""
    app_id = await _create(maker, seed)
    reader = _client(migrated, settings, monkeypatch, FakeTypst(error=error), _READER)
    response = reader.get(f"/api/applications/{app_id}/pdf")
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
