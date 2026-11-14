"""The routes of the export logo (spec 000891): permission, upload, and the download."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.admin.router import get_export_logo_service
from app.modules.admin.schemas import ExportLogoOut
from tests._support.audit_fakes import FakeSession

SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>'


class _FakeExportLogos:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.session = FakeSession()
        self.logo: ExportLogoOut | None = None

    async def get(self) -> ExportLogoOut | None:
        return self.logo

    async def upload(
        self, data: bytes, *, filename: str | None, actor: str
    ) -> tuple[ExportLogoOut, str | None]:
        self.calls.append(("upload", (data, filename, actor)))
        self.logo = ExportLogoOut(file_name=filename or "", mime="image/svg+xml", size=len(data))
        return self.logo, "export-logo/old"

    async def delete(self, actor: str) -> str:
        self.calls.append(("delete", actor))
        self.logo = None
        return "export-logo/new"

    async def remove_object(self, object_key: str | None) -> None:
        self.calls.append(("remove", object_key))

    async def file_bytes(self) -> tuple[bytes, str]:
        return SVG, "logo.svg"


def _client(fake: _FakeExportLogos, *permissions: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_export_logo_service] = lambda: fake
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions=set(permissions)
    )
    return TestClient(app)


def test_the_export_logo_routes() -> None:
    """Rule: §F/administration/admin/000891. Upload, read and remove on the branding page."""
    fake = _FakeExportLogos()
    client = _client(fake, "admin.site")
    assert client.get("/api/admin/export-logo").json() is None
    resp = client.put("/api/admin/export-logo", files={"file": ("logo.svg", SVG, "image/svg+xml")})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"fileName": "logo.svg", "mime": "image/svg+xml", "size": len(SVG)}
    assert fake.calls == [("upload", (SVG, "logo.svg", "admin")), ("remove", "export-logo/old")]
    assert fake.session.committed == 1
    assert client.get("/api/admin/export-logo").json()["fileName"] == "logo.svg"
    assert client.delete("/api/admin/export-logo").status_code == 204
    assert fake.calls[-2:] == [("delete", "admin"), ("remove", "export-logo/new")]
    assert fake.session.committed == 2


def test_the_export_logo_downloads_only_as_an_attachment() -> None:
    """A stored SVG never comes back inline: octet-stream and an attachment."""
    resp = _client(_FakeExportLogos(), "admin.site").get("/api/admin/export-logo/file")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/octet-stream"
    assert resp.headers["content-disposition"].startswith("attachment")


def test_the_export_logo_needs_the_site_permission() -> None:
    fake = _FakeExportLogos()
    client = _client(fake)
    assert client.get("/api/admin/export-logo").status_code == 403
    put = client.put("/api/admin/export-logo", files={"file": ("a.svg", SVG, "image/svg+xml")})
    assert put.status_code == 403
    assert client.delete("/api/admin/export-logo").status_code == 403
    assert client.get("/api/admin/export-logo/file").status_code == 403
    assert fake.calls == []
