"""The page head, the link preview, the app icons and the names follow the branding.

Specs F/administration/admin/001090 (page head), 001091 (preview image), 001092 (app
icons), 001093 (description) and F/meetings/calendar/001094 (feed names).
"""

from __future__ import annotations

import base64
import io
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.modules.admin.page_head import (
    DEFAULT_APP_NAME,
    DEFAULT_DESCRIPTION,
    description,
    render_page_head,
)
from app.modules.admin.router import get_site_config_service
from app.modules.admin.site_config_service import SiteConfigService, manifest_icons
from app.modules.site_config.brand_images import icon_png, preview_png, square_png
from app.modules.site_config.branding import Branding
from app.modules.site_config.models import SiteConfigVersion
from app.modules.site_config.names import app_short_name, name_slug
from tests._support.auth_fakes import fake_session, result

BASE = "https://stupa.example"


def _png_bytes(width: int, height: int, colour: tuple[int, int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _asset(data: bytes, name: str = "mark.png") -> dict[str, Any]:
    url = "data:image/png;base64," + base64.b64encode(data).decode()
    return {"url": url, "filename": name, "mime": "image/png", "size": len(data)}


def _branding(**logos: bytes) -> Branding:
    return Branding.model_validate(
        {"appName": "STUPA Workflow", "logos": {k: _asset(v) for k, v in logos.items()}}
    )


RED = _png_bytes(40, 20, (200, 0, 0, 255))
BLUE = _png_bytes(30, 30, (0, 0, 200, 255))


def test_the_head_names_the_platform_by_the_branding() -> None:
    head = render_page_head(
        Branding(appName="STUPA Workflow", appShortName="StuPa"), base_url=BASE, version=7
    )
    assert "<title>STUPA Workflow</title>" in head
    assert '<meta property="og:title" content="STUPA Workflow" />' in head
    assert '<meta property="og:site_name" content="STUPA Workflow" />' in head
    assert '<meta name="twitter:title" content="STUPA Workflow" />' in head
    assert '<meta name="apple-mobile-web-app-title" content="StuPa" />' in head
    assert "Antragsplattform" not in head


def test_an_empty_branding_gives_the_built_in_names_and_description() -> None:
    head = render_page_head(Branding(), base_url=BASE, version=0)
    assert f"<title>{DEFAULT_APP_NAME}</title>" in head
    assert '<meta name="apple-mobile-web-app-title" content="STUPA" />' in head
    assert f'content="{DEFAULT_DESCRIPTION["de"]}"' in head


def test_the_head_escapes_the_admin_texts() -> None:
    branding = Branding(appName='A "B" <script>', description={"de": "x & <y>"})
    head = render_page_head(branding, base_url=BASE, version=1)
    assert "<script>" not in head
    assert "<title>A &quot;B&quot; &lt;script&gt;</title>" in head
    assert 'content="x &amp; &lt;y&gt;"' in head


def test_the_description_comes_from_the_branding_with_a_language_fallback() -> None:
    branding = Branding(description={"de": "  Die  Plattform. ", "en": " "})
    assert description(branding) == "Die Plattform."
    assert description(branding, "en") == "Die Plattform."
    assert description(Branding(), "en") == DEFAULT_DESCRIPTION["en"]


def test_the_description_is_capped() -> None:
    with pytest.raises(ValueError, match="300"):
        Branding(description={"de": "x" * 301})


def test_the_preview_image_is_the_built_in_icon_without_a_mark() -> None:
    head = render_page_head(Branding(), base_url=BASE + "/", version=3)
    assert f'<meta property="og:image" content="{BASE}/icons/icon-512x512.png" />' in head
    assert f'<meta name="twitter:image" content="{BASE}/icons/icon-512x512.png" />' in head
    assert '<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />' in head
    assert 'href="/favicon.ico"' in head


def test_the_preview_image_takes_the_bildmarke_else_the_wortmarke() -> None:
    url = f"{BASE}/api/branding/preview.png?v=4"
    for branding in (_branding(imagemark=BLUE), _branding(wordmark=RED)):
        head = render_page_head(branding, base_url=BASE, version=4)
        assert f'<meta property="og:image" content="{url}" />' in head
    both = preview_png(_branding(imagemark=BLUE, wordmark=RED))
    assert both is not None
    with Image.open(io.BytesIO(both)) as image:
        assert image.size == (512, 512)
        assert image.convert("RGB").getpixel((256, 256)) == (0, 0, 200)
        assert image.convert("RGB").getpixel((2, 2)) == (255, 255, 255)


def test_the_apple_icon_and_the_favicon_follow_the_uploads() -> None:
    branding = _branding(imagemark=BLUE, favicon=BLUE)
    head = render_page_head(branding, base_url=BASE, version=5)
    assert 'href="/api/branding/icons/icon-180x180.png?v=5"' in head
    assert '<link rel="icon" type="image/png" href="/api/branding/favicon?v=5" />' in head
    assert "favicon.ico" not in head


def test_a_wortmarke_alone_gives_no_app_icon() -> None:
    branding = _branding(wordmark=RED)
    assert icon_png(branding, 192) is None
    assert manifest_icons(branding, 2)["icons"][0]["src"] == "icons/icon-72x72.png"


def test_the_manifest_icons_follow_the_bildmarke() -> None:
    icons = manifest_icons(_branding(imagemark=BLUE), 9)
    srcs = [icon["src"] for icon in icons["icons"]]
    assert "api/branding/icons/icon-192x192.png?v=9" in srcs
    assert "api/branding/icons/icon-maskable-512x512.png?v=9" in srcs
    assert icons["shortcuts"][0]["icons"] == [
        {"src": "api/branding/icons/icon-96x96.png?v=9", "sizes": "96x96", "type": "image/png"}
    ]


def test_an_app_icon_is_an_opaque_square_of_its_size() -> None:
    data = icon_png(_branding(imagemark=RED), 192, "maskable")
    assert data is not None
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (192, 192)
        assert image.mode == "RGB"
        assert image.getpixel((96, 96)) == (200, 0, 0)
        assert image.getpixel((96, 30)) == (255, 255, 255)


def test_square_png_refuses_bytes_that_are_no_image() -> None:
    assert square_png(b"\x89PNG\r\n\x1a\nbroken", 64, margin=0.1) is None


async def test_the_manifest_takes_the_description_of_the_branding() -> None:
    branding = Branding(description={"de": "Unsere Plattform."})
    active = SiteConfigVersion(
        version=3, active=True, branding=branding.model_dump(by_alias=True), created_by="admin"
    )
    man = await SiteConfigService(fake_session(result(active))).manifest()
    assert man["description"] == "Unsere Plattform."
    assert man["icons"][0]["src"] == "icons/icon-72x72.png"


def test_the_short_name_and_its_file_name_part() -> None:
    assert app_short_name(Branding()) == "STUPA"
    assert app_short_name(Branding(appShortName=" AStA ")) == "AStA"
    assert name_slug("AStA Gremien") == "asta-gremien"
    assert name_slug("Fußball Ä") == "fussball-ae"
    assert name_slug("—") == "stupa"


class _SiteFake:
    def __init__(self, branding: Branding) -> None:
        self.branding = branding
        self.base_urls: list[str] = []

    async def page_head(self, base_url: str) -> str:
        self.base_urls.append(base_url)
        return render_page_head(self.branding, base_url=base_url, version=1)

    async def branding_and_version(self) -> tuple[Branding, int]:
        return self.branding, 1


def _client(branding: Branding) -> TestClient:
    application = create_app()
    application.dependency_overrides[get_site_config_service] = lambda: _SiteFake(branding)
    return TestClient(application)


def test_the_page_head_route_serves_the_fragment_without_auth() -> None:
    resp = _client(Branding(appName="STUPA Workflow")).get("/api/page-head")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "<title>STUPA Workflow</title>" in resp.text


def test_the_image_routes_serve_the_branding_images() -> None:
    client = _client(_branding(imagemark=BLUE, favicon=RED))
    preview = client.get("/api/branding/preview.png")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.headers["cache-control"] == "public, max-age=300"
    icon = client.get("/api/branding/icons/icon-maskable-192x192.png")
    assert icon.status_code == 200
    with Image.open(io.BytesIO(icon.content)) as image:
        assert image.size == (192, 192)
    favicon = client.get("/api/branding/favicon")
    assert favicon.status_code == 200
    assert favicon.content == RED


def test_the_image_routes_answer_404_without_an_image() -> None:
    client = _client(Branding())
    for path in (
        "/api/branding/preview.png",
        "/api/branding/icons/icon-192x192.png",
        "/api/branding/favicon",
    ):
        resp = client.get(path)
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/problem+json")
    assert _client(_branding(imagemark=BLUE)).get("/api/branding/icons/x.png").status_code == 404
