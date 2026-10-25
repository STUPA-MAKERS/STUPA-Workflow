"""Uploaded images in protocols: sanitizer, render assets and the public image ids."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from datetime import date as _date
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.protocol import service as protocol_service_mod
from app.modules.protocol.markdown import sanitize_user_markdown
from app.modules.protocol.models import Protocol
from app.modules.protocol.public import PublicProtocolService, PublicSnapshot, PublicTop
from app.modules.protocol.service import ProtocolService
from app.settings import get_settings
from app.shared.errors import NotFoundError
from tests._support.media_fakes import MediaSession, MediaStorage, add_image
from tests._support.pdf_fakes import FakeTypst

A = uuid.UUID("0b7c6f0e-3a51-4c3e-9b8e-6f1d2a3b4c5d")
B = uuid.UUID("1b7c6f0e-3a51-4c3e-9b8e-6f1d2a3b4c5d")
C = uuid.UUID("2b7c6f0e-3a51-4c3e-9b8e-6f1d2a3b4c5d")


# -- sanitizer --------------------------------------------------------------


def test_sanitizer_keeps_the_canonical_image_path() -> None:
    body = f"![Foto](/api/media/images/{A})"
    assert sanitize_user_markdown(body) == body


def test_sanitizer_still_neutralizes_other_absolute_paths() -> None:
    out = sanitize_user_markdown(f"![x](/api/media/images/{A}/../../etc/passwd) ![y](/etc/passwd)")
    assert "/etc/passwd" not in out
    assert out.count("(Bild entfernt)") == 2


# -- render assets ----------------------------------------------------------


class _RenderSession(MediaSession):
    """The media session plus `scalar` for the CD lookup (no variant)."""

    async def scalar(self, _stmt: object) -> None:
        return None


def _protocol(cd_variant: str | None = None) -> Protocol:
    proto = Protocol(meeting_id=uuid.uuid4(), gremium_id=uuid.uuid4(), markdown="", status="draft")
    proto.id = uuid.uuid4()
    proto.cd_variant = cd_variant
    return proto


def _service(session: _RenderSession, storage: MediaStorage, typst: FakeTypst) -> ProtocolService:
    return ProtocolService(
        session,  # pyright: ignore[reportArgumentType]
        storage=storage,
        typst=typst,  # pyright: ignore[reportArgumentType]
        settings=get_settings(),
    )


async def test_render_sends_the_images_as_assets() -> None:
    session, storage, typst = _RenderSession(), MediaStorage(), FakeTypst()
    a = add_image(session, storage, b"A" * 3, "image/png")
    b = add_image(session, storage, b"B" * 3, "image/jpeg")
    markdown = f"# TOP\n\n![b](/api/media/images/{b})\n\n![a](/api/media/images/{a})\n"
    pdf = await _service(session, storage, typst)._render_pdf(_protocol(), markdown)
    assert pdf == typst.pdf
    assert typst.assets[-1] == {f"img-{b}.jpg": b"BBB", f"img-{a}.png": b"AAA"}


async def test_render_merges_the_images_with_the_logos(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _cd(*_args: object) -> Any:
        return SimpleNamespace(assets={"a1-logo.png": b"LOGO"})

    monkeypatch.setattr(protocol_service_mod, "resolve_cd_variant_by_key", _cd)
    monkeypatch.setattr(protocol_service_mod, "cd_render_config", lambda _cd: {"logos": ["x"]})
    session, storage, typst = _RenderSession(), MediaStorage(), FakeTypst()
    a = add_image(session, storage, b"A", "image/webp")
    await _service(session, storage, typst)._render_pdf(
        _protocol("custom"), f"![a](/api/media/images/{a})"
    )
    assert typst.assets[-1] == {"a1-logo.png": b"LOGO", f"img-{a}.webp": b"A"}
    assert typst.configs[-1] == {"logos": ["x"]}


async def test_render_without_images_and_logos_sends_no_assets() -> None:
    session, storage, typst = _RenderSession(), MediaStorage(), FakeTypst()
    await _service(session, storage, typst)._render_pdf(_protocol(), "# TOP\n\nText\n")
    assert typst.assets[-1] is None


async def test_render_never_fails_for_a_missing_image() -> None:
    session, storage, typst = _RenderSession(), MediaStorage(), FakeTypst()
    gone = add_image(session, storage, b"G")
    storage.objects.clear()
    markdown = f"![weg](/api/media/images/{gone}) ![nie](/api/media/images/{uuid.uuid4()})"
    pdf = await _service(session, storage, typst)._render_pdf(_protocol(), markdown)
    assert pdf == typst.pdf
    assert typst.assets[-1] is None


# -- public image ids -------------------------------------------------------


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row

    def first(self) -> Any:
        return self._row


class _PublicSession:
    def __init__(self, row: Any) -> None:
        self.row = row

    async def execute(self, _stmt: object) -> _Result:
        return _Result(self.row)


def _visibleadd_image(snapshot: PublicSnapshot) -> tuple[Any, Any, Any]:
    protocol = SimpleNamespace(
        id=uuid.uuid4(),
        sent_at=datetime(2026, 10, 2, tzinfo=UTC),
        public_content=snapshot.model_dump(mode="json", by_alias=True),
    )
    meeting = SimpleNamespace(title="Sitzung", date=_date(2026, 9, 29))
    gremium = SimpleNamespace(id=uuid.uuid4(), name="StuPa", slug="stupa")
    return protocol, meeting, gremium


async def test_public_image_ids_come_from_the_public_markdown_only() -> None:
    snapshot = PublicSnapshot(
        tops=[
            PublicTop(number=1, title="Offen", markdown=f"![a](/api/media/images/{A})"),
            PublicTop(
                number=2,
                title="Geheim",
                nonPublic=True,
                markdown=f"![b](/api/media/images/{B})",
            ),
        ],
        markdown=f"![c](/api/media/images/{C})",
    )
    svc = PublicProtocolService(_PublicSession(_visibleadd_image(snapshot)))  # pyright: ignore[reportArgumentType]
    assert await svc.public_image_ids(uuid.uuid4()) == {A, C}


async def test_public_image_ids_of_a_hidden_protocol_is_404() -> None:
    svc = PublicProtocolService(_PublicSession(None))  # pyright: ignore[reportArgumentType]
    with pytest.raises(NotFoundError):
        await svc.public_image_ids(uuid.uuid4())
