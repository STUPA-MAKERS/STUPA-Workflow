"""Nextcloud-WebDAV-Export (T-20, deployment §3) — **optional**.

Nach der MinIO-Ablage spiegelt der Worker das PDF best-effort in einen konfigurierten
Nextcloud-Ordner (``W->>NC: WebDAV put`` in flows §6). Fehlt die Config (URL/User/
App-Passwort), ist der Export **aus**: :func:`build_nextcloud_exporter` liefert ``None``,
der Worker überspringt den Schritt sauber (PDF bleibt in MinIO, **kein** Crash).

Der Ziel-Ordner wird vor dem ``PUT`` per ``MKCOL`` angelegt (idempotent: bereits
vorhanden → 405/409 wird ignoriert). Das App-Passwort ist ein Secret und wird **nie**
geloggt; Fehler tragen nur Status/Kurzgrund (kein Pfad-/Credential-Leak).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.settings import Settings


class NextcloudError(RuntimeError):
    """WebDAV-Operation fehlgeschlagen (transient — Worker entscheidet über Retry)."""


def _sanitize_segment(name: str) -> str:
    """Pfad-Segment säubern: keine Slashes/Steuerzeichen/`..` (Path-Traversal-Schutz)."""
    cleaned = "".join(c for c in name if c.isprintable() and c not in '/\\\r\n')
    cleaned = cleaned.replace("..", "_")
    return cleaned or "document.pdf"


@dataclass(slots=True)
class NextcloudExporter:
    """Lädt ein PDF per WebDAV in ``<base_url>/<base_path>/<filename>``."""

    base_url: str
    user: str
    app_password: str
    base_path: str = "Antraege/"
    timeout_seconds: float = 60.0

    def _dir_url(self) -> str:
        base = self.base_url.rstrip("/") + "/"
        path = self.base_path.strip("/")
        return base + path + "/" if path else base

    def remote_path(self, filename: str) -> str:
        """Relativer Zielpfad (für die Job-Persistenz/Anzeige, ohne Host/Credentials)."""
        path = self.base_path.strip("/")
        safe = _sanitize_segment(filename)
        return f"{path}/{safe}" if path else safe

    async def put_pdf(self, filename: str, data: bytes) -> str:
        """PDF hochladen; gibt den relativen Remote-Pfad zurück. Ordner wird sicher­gestellt."""
        dir_url = self._dir_url()
        target = dir_url + _sanitize_segment(filename)
        auth = httpx.BasicAuth(self.user, self.app_password)
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, auth=auth) as c:
                # Ordner idempotent anlegen: existiert er, antwortet WebDAV 405/409.
                mkcol = await c.request("MKCOL", dir_url)
                if mkcol.status_code not in (httpx.codes.CREATED, 405, 409):
                    raise NextcloudError(
                        f"nextcloud mkcol failed (status {mkcol.status_code})"
                    )
                put = await c.put(
                    target,
                    content=data,
                    headers={"Content-Type": "application/pdf"},
                )
        except httpx.HTTPError as exc:
            raise NextcloudError(
                f"nextcloud unreachable ({type(exc).__name__})"
            ) from exc
        if put.status_code not in (httpx.codes.CREATED, httpx.codes.NO_CONTENT, httpx.codes.OK):
            raise NextcloudError(f"nextcloud put failed (status {put.status_code})")
        return self.remote_path(filename)


def build_nextcloud_exporter(settings: Settings) -> NextcloudExporter | None:
    """Exporter aus den Settings — ``None``, wenn die Config unvollständig ist (Export »aus«)."""
    if not settings.nextcloud_enabled:
        return None
    assert settings.nextcloud_webdav_url is not None
    assert settings.nextcloud_user is not None
    assert settings.nextcloud_app_password is not None
    return NextcloudExporter(
        base_url=settings.nextcloud_webdav_url,
        user=settings.nextcloud_user,
        app_password=settings.nextcloud_app_password,
        base_path=settings.nextcloud_base_path,
        timeout_seconds=float(settings.nextcloud_timeout_seconds),
    )
