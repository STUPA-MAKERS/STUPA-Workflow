"""Site-Config-/Branding-Service (#21, T-24).

Versioniert wie form/flow: der Draft wird bearbeitet (neue, inaktive Version oder
In-place auf den bestehenden Draft — **nie** auf die aktive Version), Aktivierung
schaltet ``active`` um (max. eine aktive, partial-unique) und schreibt einen
``config_activation``-Audit-Eintrag.

Die Draft/Activate-Form (``{version, active, draft, hasDraftChanges}``) ist exakt
das, wogegen das T-34-FE gebaut ist. Branding wird gegen ``admin.branding.Branding``
validiert (Bild-only-Logos, kein Inline-SVG); ungültiges Branding → 422 (Schema).
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.branding import Branding
from app.modules.admin.models import SiteConfigVersion
from app.modules.admin.schemas import PublicSiteConfigOut, SiteConfigOut
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.shared.errors import ConflictError

# Default-App-Namen (Fallback, wenn die Config sie leer lässt) — 1:1 die Werte des
# bisher statischen ``frontend/public/manifest.webmanifest``.
DEFAULT_APP_NAME = "STUPA Antragsplattform"
DEFAULT_APP_SHORT_NAME = "StuPa"

# Statische Manifest-Felder (alles außer name/short_name) — Single Source of Truth
# fürs dynamisch ausgelieferte PWA-Manifest. Spiegelt das bisherige statische
# ``frontend/public/manifest.webmanifest`` (Icons, theme_color, scope, … ).
_MANIFEST_BASE: dict = {
    "description": (
        "Antragsplattform des Studierendenparlaments — Anträge, Abstimmungen, "
        "Sitzungsprotokolle und Budget."
    ),
    "lang": "de",
    "display": "standalone",
    "scope": "./",
    "start_url": "./",
    "theme_color": "#004225",
    "background_color": "#ffffff",
    "icons": [
        {"src": "icons/icon-72x72.png", "sizes": "72x72", "type": "image/png", "purpose": "any"},
        {"src": "icons/icon-96x96.png", "sizes": "96x96", "type": "image/png", "purpose": "any"},
        {
            "src": "icons/icon-128x128.png",
            "sizes": "128x128",
            "type": "image/png",
            "purpose": "any",
        },
        {
            "src": "icons/icon-144x144.png",
            "sizes": "144x144",
            "type": "image/png",
            "purpose": "any",
        },
        {
            "src": "icons/icon-152x152.png",
            "sizes": "152x152",
            "type": "image/png",
            "purpose": "any",
        },
        {
            "src": "icons/icon-192x192.png",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "any",
        },
        {
            "src": "icons/icon-384x384.png",
            "sizes": "384x384",
            "type": "image/png",
            "purpose": "any",
        },
        {
            "src": "icons/icon-512x512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any",
        },
        {
            "src": "icons/icon-maskable-192x192.png",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "maskable",
        },
        {
            "src": "icons/icon-maskable-512x512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable",
        },
    ],
}


def _branding(row: SiteConfigVersion | None) -> Branding:
    return Branding.model_validate(row.branding) if row is not None else Branding()


class SiteConfigService:
    """An eine ``AsyncSession`` gebundene Site-Config-Operationen."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _active(self) -> SiteConfigVersion | None:
        return (
            await self.session.scalars(
                select(SiteConfigVersion).where(SiteConfigVersion.active.is_(True))
            )
        ).first()

    async def _latest(self) -> SiteConfigVersion | None:
        return (
            await self.session.scalars(
                select(SiteConfigVersion).order_by(SiteConfigVersion.version.desc())
            )
        ).first()

    async def get(self) -> SiteConfigOut:
        active = await self._active()
        latest = await self._latest()
        active_branding = _branding(active)
        if latest is None or latest.active:
            # Kein offener Draft → Draft spiegelt die aktive Version.
            return SiteConfigOut(
                version=active.version if active else 0,
                active=active_branding,
                draft=active_branding,
                has_draft_changes=False,
            )
        return SiteConfigOut(
            version=active.version if active else 0,
            active=active_branding,
            draft=_branding(latest),
            has_draft_changes=True,
        )

    async def put_draft(self, branding: Branding, actor: str) -> SiteConfigOut:
        latest = await self._latest()
        payload = branding.model_dump(by_alias=True)
        if latest is not None and not latest.active:
            # Bestehenden Draft in-place aktualisieren (kein neuer Versionssprung).
            latest.branding = payload
            target_id = latest.id
        else:
            # Neue Draft-Version oberhalb der aktiven anlegen (inaktiv).
            base = latest.version if latest is not None else 0
            row = SiteConfigVersion(
                version=base + 1, active=False, branding=payload, created_by=actor
            )
            self.session.add(row)
            await self.session.flush()
            target_id = row.id
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.CONFIG_CHANGE,
            target_type="site_config",
            target_id=str(target_id),
        )
        await self.session.commit()
        return await self.get()

    async def activate(self, actor: str) -> SiteConfigOut:
        latest = await self._latest()
        if latest is None or latest.active:
            raise ConflictError("no pending site-config draft to activate")
        await self.session.execute(
            update(SiteConfigVersion)
            .where(SiteConfigVersion.active.is_(True))
            .values(active=False)
        )
        latest.active = True
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.CONFIG_ACTIVATION,
            target_type="site_config",
            target_id=str(latest.id),
            data={"version": latest.version},
        )
        await self.session.commit()
        return await self.get()

    async def public(self) -> PublicSiteConfigOut:
        """Öffentliche aktive Branding-Config (auth-frei, #21)."""
        active = await self._active()
        return PublicSiteConfigOut(
            version=active.version if active else 0, branding=_branding(active)
        )

    async def manifest(self) -> dict:
        """PWA-Manifest aus der aktiven Branding-Config bauen (Single Source of Truth).

        ``name``/``short_name`` kommen aus der Config (Fallback auf die Defaults, wenn
        leer); alle übrigen Felder (Icons, theme_color, scope, …) sind statisch."""
        branding = _branding(await self._active())
        return {
            "name": branding.app_name.strip() or DEFAULT_APP_NAME,
            "short_name": branding.app_short_name.strip() or DEFAULT_APP_SHORT_NAME,
            **_MANIFEST_BASE,
        }
