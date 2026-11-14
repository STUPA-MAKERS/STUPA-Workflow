"""The export logo of the branding against the database (spec 000891).

The admin service stores one logo (PNG, JPEG, WebP, SVG or PDF) and the exports read it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.service.export_logo import ExportLogoService
from app.modules.audit.models import AuditEntry
from app.modules.files.export_logo import ExportLogo, active_export_logo
from app.modules.site_config.models import ExportLogo as ExportLogoRow
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


def _service(session: AsyncSession, storage: FakeStorage | None) -> ExportLogoService:
    return ExportLogoService(session, storage=storage, settings=load_settings())


async def test_the_export_logo_is_uploaded_replaced_and_removed(session: AsyncSession) -> None:
    """Rule: §F/administration/admin/000891. One logo, SVG and PDF allowed, audited."""
    storage = FakeStorage()
    svc = _service(session, storage)
    assert await svc.get() is None
    assert await active_export_logo(session, storage) is None

    out, replaced = await svc.upload(SVG, filename="logo.svg", actor="admin")
    assert replaced is None
    assert (out.file_name, out.mime, out.size) == ("logo.svg", "image/svg+xml", len(SVG))
    assert await active_export_logo(session, storage) == ExportLogo("export-logo.svg", SVG)
    first_key = next(iter(storage.objects))

    _, replaced = await svc.upload(PDF, filename="logo.pdf", actor="admin")
    assert replaced == first_key
    assert storage.removed == []
    await svc.remove_object(replaced)
    assert len((await session.scalars(select(ExportLogoRow))).all()) == 1
    assert storage.removed == [first_key]
    assert await active_export_logo(session, storage) == ExportLogo("export-logo.pdf", PDF)
    assert await svc.file_bytes() == (PDF, "logo.pdf")

    await svc.remove_object(await svc.delete("admin"))
    assert await svc.get() is None
    assert await active_export_logo(session, storage) is None
    audits = (
        await session.scalars(select(AuditEntry).where(AuditEntry.target_type == "export_logo"))
    ).all()
    assert len(audits) == 3


async def test_the_export_logo_refuses_other_types_and_a_missing_storage(
    session: AsyncSession,
) -> None:
    """An ICO is refused; without a storage the upload and the read answer 503."""
    with pytest.raises(UnsupportedMediaTypeError):
        await _service(session, FakeStorage()).upload(ICO, filename="a.ico", actor="admin")
    with pytest.raises(UnsupportedMediaTypeError):
        await _service(session, FakeStorage()).upload(b"", filename="a.png", actor="admin")
    with pytest.raises(ServiceUnavailableError):
        await _service(session, None).upload(SVG, filename="a.svg", actor="admin")
    with pytest.raises(ServiceUnavailableError):
        await _service(session, FailingStorage()).upload(SVG, filename="a.svg", actor="admin")
    with pytest.raises(NotFoundError):
        await _service(session, None).delete("admin")
    with pytest.raises(NotFoundError):
        await _service(session, None).file_bytes()

    await _service(session, FakeStorage()).upload(SVG, filename="a.svg", actor="admin")
    with pytest.raises(ServiceUnavailableError):
        await active_export_logo(session, None)
    with pytest.raises(ServiceUnavailableError):
        await active_export_logo(session, FailingStorage())
    with pytest.raises(ServiceUnavailableError):
        await _service(session, FailingStorage()).file_bytes()
    with pytest.raises(ServiceUnavailableError):
        await _service(session, None).file_bytes()
