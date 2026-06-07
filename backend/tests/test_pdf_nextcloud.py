"""Unit-Tests Nextcloud-WebDAV-Export (T-20): respx-Mock von MKCOL + PUT.

Deckt Erfolg, idempotentes MKCOL (405 = Ordner existiert), PUT-/MKCOL-Fehler,
Transport-Fehler, Pfad-Sanitisierung und die »Export aus«-Config ab.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.modules.pdf.nextcloud import (
    NextcloudError,
    NextcloudExporter,
    build_nextcloud_exporter,
)
from app.settings import load_settings

DAV = "https://cloud.local/remote.php/dav/files/u/"


def _exp() -> NextcloudExporter:
    return NextcloudExporter(
        base_url=DAV, user="u", app_password="pw", base_path="Antraege/", timeout_seconds=5
    )


@respx.mock
async def test_put_pdf_success_returns_remote_path() -> None:
    respx.request("MKCOL", f"{DAV}Antraege/").mock(return_value=httpx.Response(201))
    put = respx.put(f"{DAV}Antraege/antrag.pdf").mock(return_value=httpx.Response(201))
    path = await _exp().put_pdf("antrag.pdf", b"%PDF")
    assert path == "Antraege/antrag.pdf"
    assert put.called
    # Basic-Auth-Header gesetzt (Credentials nie im Pfad).
    assert put.calls.last.request.headers["authorization"].startswith("Basic ")


@respx.mock
async def test_mkcol_405_existing_dir_is_ignored() -> None:
    respx.request("MKCOL", f"{DAV}Antraege/").mock(return_value=httpx.Response(405))
    respx.put(f"{DAV}Antraege/antrag.pdf").mock(return_value=httpx.Response(204))
    assert await _exp().put_pdf("antrag.pdf", b"%PDF") == "Antraege/antrag.pdf"


@respx.mock
async def test_mkcol_hard_error_raises() -> None:
    respx.request("MKCOL", f"{DAV}Antraege/").mock(return_value=httpx.Response(500))
    with pytest.raises(NextcloudError):
        await _exp().put_pdf("antrag.pdf", b"%PDF")


@respx.mock
async def test_put_failure_raises() -> None:
    respx.request("MKCOL", f"{DAV}Antraege/").mock(return_value=httpx.Response(201))
    respx.put(f"{DAV}Antraege/antrag.pdf").mock(return_value=httpx.Response(403))
    with pytest.raises(NextcloudError):
        await _exp().put_pdf("antrag.pdf", b"%PDF")


@respx.mock
async def test_transport_error_raises() -> None:
    respx.request("MKCOL", f"{DAV}Antraege/").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(NextcloudError):
        await _exp().put_pdf("antrag.pdf", b"%PDF")


@respx.mock
async def test_filename_traversal_sanitized() -> None:
    respx.request("MKCOL", f"{DAV}Antraege/").mock(return_value=httpx.Response(201))
    # `../` und Slashes raus → kein Ausbruch aus dem Zielordner.
    put = respx.put(f"{DAV}Antraege/__etcpasswd").mock(return_value=httpx.Response(201))
    path = await _exp().put_pdf("../../etc/passwd", b"x")
    assert put.called
    assert path == "Antraege/__etcpasswd"


def test_build_exporter_disabled_when_config_incomplete() -> None:
    assert build_nextcloud_exporter(load_settings()) is None
    partial = load_settings(nextcloud_webdav_url=DAV, nextcloud_user="u")
    assert build_nextcloud_exporter(partial) is None


def test_build_exporter_enabled_with_full_config() -> None:
    settings = load_settings(
        nextcloud_webdav_url=DAV,
        nextcloud_user="u",
        nextcloud_app_password="pw",
        nextcloud_base_path="X/",
    )
    exp = build_nextcloud_exporter(settings)
    assert exp is not None
    assert exp.base_path == "X/"
