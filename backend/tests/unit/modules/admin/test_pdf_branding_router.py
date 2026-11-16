"""The routes of the PDF branding (specs 000891, 000892): permission, upload, download."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.admin.router import get_pdf_branding_service
from app.modules.admin.schemas import PdfAssetOut
from tests._support.audit_fakes import FakeSession

SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>'


class _FakePdfBranding:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.session = FakeSession()
        self.assets: dict[str, PdfAssetOut] = {}

    async def get(self, slot: str) -> PdfAssetOut | None:
        return self.assets.get(slot)

    async def upload(
        self, slot: str, data: bytes, *, filename: str | None, actor: str
    ) -> tuple[PdfAssetOut, str | None]:
        self.calls.append(("upload", (slot, data, filename, actor)))
        self.assets[slot] = PdfAssetOut(
            builtin=False, file_name=filename, mime="image/svg+xml", size=len(data)
        )
        return self.assets[slot], "pdf-asset/old"

    async def reset(self, slot: str, actor: str) -> tuple[PdfAssetOut, str | None]:
        self.calls.append(("reset", (slot, actor)))
        self.assets[slot] = PdfAssetOut(builtin=True)
        return self.assets[slot], None

    async def delete(self, slot: str, actor: str) -> str | None:
        self.calls.append(("delete", (slot, actor)))
        self.assets.pop(slot, None)
        return "pdf-asset/new"

    async def file_bytes(self, slot: str) -> tuple[bytes, str]:
        return SVG, "logo.svg"

    async def remove_object(self, object_key: str | None) -> None:
        self.calls.append(("remove", object_key))


def _client(fake: _FakePdfBranding, *permissions: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_pdf_branding_service] = lambda: fake
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions=set(permissions)
    )
    return TestClient(app)


def test_the_pdf_branding_routes() -> None:
    """Rule: §F/administration/admin/000891. Upload, reset and remove on the branding page."""
    fake = _FakePdfBranding()
    client = _client(fake, "admin.site")
    assert client.get("/api/admin/pdf-assets/logo").json() is None
    resp = client.put(
        "/api/admin/pdf-assets/footer", files={"file": ("logo.svg", SVG, "image/svg+xml")}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "builtin": False,
        "fileName": "logo.svg",
        "mime": "image/svg+xml",
        "size": len(SVG),
    }
    assert fake.calls == [
        ("upload", ("footer", SVG, "logo.svg", "admin")),
        ("remove", "pdf-asset/old"),
    ]
    assert fake.session.committed == 1
    reset = client.post("/api/admin/pdf-assets/logo/default")
    assert reset.json() == {"builtin": True, "fileName": None, "mime": None, "size": None}
    assert client.delete("/api/admin/pdf-assets/footer").status_code == 204
    assert fake.calls[-2:] == [("delete", ("footer", "admin")), ("remove", "pdf-asset/new")]
    assert fake.session.committed == 3
    assert client.get("/api/admin/pdf-assets/other").status_code == 422


def test_the_pdf_asset_downloads_only_as_an_attachment() -> None:
    """A stored SVG never comes back inline: octet-stream and an attachment."""
    resp = _client(_FakePdfBranding(), "admin.site").get("/api/admin/pdf-assets/logo/file")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/octet-stream"
    assert resp.headers["content-disposition"].startswith("attachment")


def test_the_pdf_branding_needs_the_site_permission() -> None:
    fake = _FakePdfBranding()
    client = _client(fake)
    assert client.get("/api/admin/pdf-assets/logo").status_code == 403
    files = {"file": ("a.svg", SVG, "image/svg+xml")}
    assert client.put("/api/admin/pdf-assets/logo", files=files).status_code == 403
    assert client.post("/api/admin/pdf-assets/logo/default").status_code == 403
    assert client.delete("/api/admin/pdf-assets/logo").status_code == 403
    assert client.get("/api/admin/pdf-assets/logo/file").status_code == 403
    assert fake.calls == []
