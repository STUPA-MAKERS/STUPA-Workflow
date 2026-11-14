"""The PDF branding against the database (specs 000891, 000892).

The admin service stores the export logo and the footer graphic (PNG, JPEG, WebP, SVG
or PDF), resets them to the built-in graphics or empties them, and the PDFs read them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.service.pdf_branding import PdfBrandingService
from app.modules.audit.models import AuditEntry
from app.modules.files.pdf_branding import PdfBranding, RenderGraphic, active_pdf_branding
from app.modules.site_config.models import PdfAsset
from app.settings import load_settings
from app.shared.errors import NotFoundError, ServiceUnavailableError, UnsupportedMediaTypeError
from tests._support.files_fakes import FailingStorage, FakeStorage

pytestmark = pytest.mark.integration

SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
PDF = b"%PDF-1.7\n1 0 obj\n"
ICO = b"\x00\x00\x01\x00" + b"\x00" * 32


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    async with async_sessionmaker(eng, expire_on_commit=False)() as s:
        yield s
    await eng.dispose()


def _service(session: AsyncSession, storage: FakeStorage | None) -> PdfBrandingService:
    return PdfBrandingService(session, storage=storage, settings=load_settings())


async def test_the_export_logo_is_uploaded_replaced_reset_and_removed(
    session: AsyncSession,
) -> None:
    """Rule: §F/administration/admin/000891. One logo per slot, SVG and PDF allowed, audited."""
    storage = FakeStorage()
    svc = _service(session, storage)
    assert await svc.get("logo") is None
    assert await active_pdf_branding(session, storage) == PdfBranding()

    out, replaced = await svc.upload("logo", SVG, filename="logo.svg", actor="admin")
    assert replaced is None
    assert (out.builtin, out.file_name, out.mime, out.size) == (
        False,
        "logo.svg",
        "image/svg+xml",
        len(SVG),
    )
    branding = await active_pdf_branding(session, storage)
    assert branding.logo == RenderGraphic("export-logo.svg", SVG)
    first_key = next(iter(storage.objects))

    _, replaced = await svc.upload("logo", PDF, filename="logo.pdf", actor="admin")
    assert replaced == first_key
    assert storage.removed == []
    await svc.remove_object(replaced)
    assert len((await session.scalars(select(PdfAsset))).all()) == 1
    assert storage.removed == [first_key]
    assert (await active_pdf_branding(session, storage)).logo == RenderGraphic(
        "export-logo.pdf", PDF
    )
    assert await svc.file_bytes("logo") == (PDF, "logo.pdf")

    out, replaced = await svc.reset("logo", "admin")
    assert out.builtin is True
    assert replaced is not None
    assert (await active_pdf_branding(session, None)).logo == RenderGraphic("STUPA")
    with pytest.raises(NotFoundError):
        await svc.file_bytes("logo")

    assert await svc.delete("logo", "admin") is None
    assert await svc.get("logo") is None
    audits = (
        await session.scalars(select(AuditEntry).where(AuditEntry.target_type == "pdf_asset"))
    ).all()
    assert len(audits) == 4


async def test_the_footer_graphic_has_its_own_slot(session: AsyncSession) -> None:
    """Rule: §F/administration/admin/000892. The footer graphic is the Skyline by default."""
    storage = FakeStorage()
    svc = _service(session, storage)
    await svc.reset("footer", "admin")
    assert await active_pdf_branding(session, storage) == PdfBranding(
        footer=RenderGraphic("Skyline")
    )
    await svc.upload("footer", SVG, filename="skyline.svg", actor="admin")
    branding = await active_pdf_branding(session, storage)
    assert branding.footer == RenderGraphic("footer-graphic.svg", SVG)
    assert branding.logo is None


async def test_the_pdf_branding_refuses_other_types_and_a_missing_storage(
    session: AsyncSession,
) -> None:
    """An ICO is refused; without a storage the upload and the read answer 503."""
    with pytest.raises(UnsupportedMediaTypeError):
        await _service(session, FakeStorage()).upload("logo", ICO, filename="a.ico", actor="a")
    with pytest.raises(UnsupportedMediaTypeError):
        await _service(session, FakeStorage()).upload("logo", b"", filename="a.png", actor="a")
    with pytest.raises(ServiceUnavailableError):
        await _service(session, None).upload("logo", SVG, filename="a.svg", actor="a")
    with pytest.raises(ServiceUnavailableError):
        await _service(session, FailingStorage()).upload("logo", SVG, filename="a.svg", actor="a")
    with pytest.raises(NotFoundError):
        await _service(session, None).delete("logo", "a")
    with pytest.raises(NotFoundError):
        await _service(session, None).file_bytes("logo")

    await _service(session, FakeStorage()).upload("logo", SVG, filename="a.svg", actor="a")
    with pytest.raises(ServiceUnavailableError):
        await active_pdf_branding(session, None)
    with pytest.raises(ServiceUnavailableError):
        await active_pdf_branding(session, FailingStorage())
    with pytest.raises(ServiceUnavailableError):
        await _service(session, FailingStorage()).file_bytes("logo")
    with pytest.raises(ServiceUnavailableError):
        await _service(session, None).file_bytes("logo")
