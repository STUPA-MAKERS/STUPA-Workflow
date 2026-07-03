"""Site-config/branding service.

Versioned like form/flow: edits go to the draft (a new inactive version or
in-place on the existing draft — never on the active version); activation flips
``active`` (at most one active, partial unique) and writes a
``config_activation`` audit entry. Branding is validated against
``admin.branding.Branding`` (image-only logos, no inline SVG); invalid branding
fails with 422.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.branding import Branding
from app.modules.admin.models import SiteConfigVersion
from app.modules.admin.schemas import PublicSiteConfigOut, SiteConfigOut
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.config_revision.service import (
    ENTITY_SITE_CONFIG,
    GLOBAL_ID,
    ConfigRevisionService,
)
from app.shared.errors import ConflictError

# Default app names (fallback when the config leaves them empty) — the values
# of the previously static ``frontend/public/manifest.webmanifest``.
DEFAULT_APP_NAME = "STUPA Antragsplattform"
DEFAULT_APP_SHORT_NAME = "StuPa"

# Static manifest fields (everything except name/short_name) — single source of
# truth for the dynamically served PWA manifest.
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
    """Site-config operations bound to an ``AsyncSession``."""

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
            # No open draft: the draft mirrors the active version.
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
            # Update the existing draft in place (no new version bump).
            latest.branding = payload
            target_id = latest.id
        else:
            # Create a new draft version above the active one (inactive).
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
        # Versioned snapshot of the now-active branding config plus linked audit entry.
        await ConfigRevisionService(self.session).record(
            entity_type=ENTITY_SITE_CONFIG,
            entity_id=GLOBAL_ID,
            snapshot=dict(latest.branding or {}),
            actor=actor,
            action=AuditAction.CONFIG_ACTIVATION,
            extra_data={"siteConfigVersion": latest.version},
        )
        await self.session.commit()
        return await self.get()

    async def restore_branding(
        self,
        branding: Branding,
        actor: str,
        *,
        action: AuditAction = AuditAction.CONFIG_CHANGE,
        extra_data: dict | None = None,
    ) -> SiteConfigOut:
        """Replay a branding config as the new active version (restore/revert).

        Creates a new active ``SiteConfigVersion`` from the snapshot (deactivates
        the rest) and writes a ``config_revision``/audit entry. Earlier versions
        are kept.
        """
        latest = await self._latest()
        base = latest.version if latest is not None else 0
        payload = branding.model_dump(by_alias=True)
        row = SiteConfigVersion(
            version=base + 1, active=True, branding=payload, created_by=actor
        )
        await self.session.execute(
            update(SiteConfigVersion)
            .where(SiteConfigVersion.active.is_(True))
            .values(active=False)
        )
        self.session.add(row)
        await self.session.flush()
        await ConfigRevisionService(self.session).record(
            entity_type=ENTITY_SITE_CONFIG,
            entity_id=GLOBAL_ID,
            snapshot=payload,
            actor=actor,
            action=action,
            extra_data={**(extra_data or {}), "siteConfigVersion": row.version},
        )
        await self.session.commit()
        return await self.get()

    async def public(self) -> PublicSiteConfigOut:
        """Return the public active branding config (auth-free)."""
        active = await self._active()
        return PublicSiteConfigOut(
            version=active.version if active else 0, branding=_branding(active)
        )

    async def manifest(self) -> dict:
        """Build the PWA manifest from the active branding config.

        ``name``/``short_name`` come from the config (defaults when empty); all
        other fields are static."""
        branding = _branding(await self._active())
        return {
            "name": branding.app_name.strip() or DEFAULT_APP_NAME,
            "short_name": branding.app_short_name.strip() or DEFAULT_APP_SHORT_NAME,
            **_MANIFEST_BASE,
        }
