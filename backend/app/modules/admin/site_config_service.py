"""Site-config and branding service.

The service versions the config like form and flow. A save writes a new active
version and deactivates the one before; there is no draft. Each save writes a
config revision and a ``config_activation`` audit entry. A partial unique index
allows at most one active version. Inactive rows from the time of the draft stay
as history and are never read as a draft.

``admin.branding.Branding`` validates the branding. A logo must be an image and
inline SVG is not allowed. Invalid branding fails with 422.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.branding import (
    Branding,
    HelpSettings,
    PublicBranding,
    TicketSettings,
)
from app.modules.admin.models import SiteConfigVersion
from app.modules.admin.schemas import (
    AttachmentLimitsOut,
    HelpTicketsSettings,
    PublicHelpOut,
    PublicSiteConfigOut,
    PublicTicketsOut,
    SiteConfigOut,
)
from app.modules.applications.guest_settings import load_guest_settings
from app.modules.audit.actions import AuditAction
from app.modules.config_revision.service import (
    ENTITY_SITE_CONFIG,
    GLOBAL_ID,
    ConfigRevisionService,
)
from app.settings import get_settings

# Fallback app names for the case where the config leaves them empty. They match the
# defaults in ``frontend/public/manifest.webmanifest``.
DEFAULT_APP_NAME = "STUPA Antragsplattform"
DEFAULT_APP_SHORT_NAME = "STUPA"

# The manifest colour per theme: the surface of the bottom bar (``--color-surface-3`` of
# the ui-kit tokens). Chrome cannot draw an installed Android app under the system
# navigation bar and paints that bar with a manifest colour, ``theme_color`` or
# ``background_color`` depending on the version. Both take the bottom bar surface, so the
# two bars meet without a seam in every version; the splash screen shows the same colour.
# The status bar follows the ``theme-color`` meta tag of the page (frontend ThemeService),
# so it keeps the page background. The manifest has no per-scheme variant, so the
# frontend links ``?scheme=dark`` while the dark theme is in effect.
MANIFEST_COLORS: dict[str, str] = {"light": "#e6e9e5", "dark": "#262a27"}

# The icon of a manifest shortcut: the app icon at 96 px, the size that Android asks for.
_SHORTCUT_ICON: dict = {"src": "icons/icon-96x96.png", "sizes": "96x96", "type": "image/png"}

# The static manifest fields, that is everything except name and short_name.
# They are the single source of truth for the PWA manifest that the API serves.
_MANIFEST_BASE: dict = {
    "description": (
        "Antragsplattform des Studierendenparlaments — Anträge, Abstimmungen, "
        "Sitzungsprotokolle und Budget."
    ),
    "lang": "de",
    # A fixed identity. Without it the browser derives the id from start_url, and a
    # later change of start_url makes an installed app a different app.
    "id": "/",
    "display": "standalone",
    "scope": "./",
    "start_url": "./",
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
    # The menu of a long press on the home screen icon (Android, desktop). The names are
    # German, because the manifest is German (`lang`). Keep them equal to
    # frontend/public/manifest.webmanifest.
    "shortcuts": [
        {"name": "Neuer Antrag", "url": "apply", "icons": [_SHORTCUT_ICON]},
        {"name": "Meine To-Dos", "url": "todos", "icons": [_SHORTCUT_ICON]},
        {"name": "Sitzungen", "url": "meetings", "icons": [_SHORTCUT_ICON]},
    ],
    # A link into the app opens in the running app and navigates there, not in a second
    # window. A browser without navigate-existing takes its own default.
    "launch_handler": {"client_mode": ["navigate-existing", "auto"]},
}


def _branding(row: SiteConfigVersion | None) -> Branding:
    return Branding.model_validate(row.branding) if row is not None else Branding()


async def active_branding(session: AsyncSession) -> Branding:
    """Return the active branding, or the defaults without an active version.

    Other modules read their settings from here: the ticket report reads
    ``tickets.publicEnabled``, the retention cron ``tickets.retentionMonths``.
    """
    row = (
        await session.scalars(select(SiteConfigVersion).where(SiteConfigVersion.active.is_(True)))
    ).first()
    return _branding(row)


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
        """Return the active branding and its version (0 without one)."""
        active = await self._active()
        return SiteConfigOut(version=active.version if active else 0, branding=_branding(active))

    async def save(self, branding: Branding, actor: str) -> SiteConfigOut:
        """Save the branding as the new active version.

        The admin pages save directly, without a draft. ``help`` and ``tickets`` in
        the payload are ignored and keep the values of the active version, because the
        "Hilfe & Tickets" page is their only writer: an editor that loaded the branding
        earlier sends stale values back, and a save of them would switch anonymous
        reports on again unnoticed.
        """
        return await self.restore_branding(branding, actor, action=AuditAction.CONFIG_ACTIVATION)

    async def restore_branding(
        self,
        branding: Branding,
        actor: str,
        *,
        action: AuditAction = AuditAction.CONFIG_CHANGE,
        extra_data: dict | None = None,
    ) -> SiteConfigOut:
        """Replay a branding config as the new active version (restore or revert).

        The method creates a new active ``SiteConfigVersion`` from the snapshot
        and deactivates the rest. It writes a ``config_revision`` entry plus the
        linked audit entry. Earlier versions stay. ``help`` and ``tickets`` keep
        the values of the active version, because the "Hilfe & Tickets" page is
        their only writer: a restore of an older snapshot would otherwise bring
        back its ticket settings, or the defaults (``publicEnabled=true``) for a
        snapshot without them.
        """
        latest = await self._latest()
        base = latest.version if latest is not None else 0
        payload = _with_help_tickets_of(branding, _branding(await self._active()))
        row = SiteConfigVersion(version=base + 1, active=True, branding=payload, created_by=actor)
        await self.session.execute(
            update(SiteConfigVersion).where(SiteConfigVersion.active.is_(True)).values(active=False)
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
        """Return the public active branding config (auth-free).

        The response also holds ``confirmTtlHours`` and ``linkTtlDays`` from the
        guest settings, so the wizard can tell a guest how long the confirmation
        waits and how long the link works. ``attachmentLimits`` comes from the
        settings of the draft upload (Z4).
        """
        active = await self._active()
        guest = await load_guest_settings(self.session)
        settings = get_settings()
        branding = _branding(active)
        return PublicSiteConfigOut(
            version=active.version if active else 0,
            branding=PublicBranding.model_validate(branding.model_dump(by_alias=True)),
            help=PublicHelpOut(wiki_url=branding.help.wiki_url),
            tickets=PublicTicketsOut(public_enabled=branding.tickets.public_enabled),
            confirm_ttl_hours=guest.confirm_ttl_hours,
            link_ttl_days=guest.link_ttl_days,
            attachment_limits=AttachmentLimitsOut(
                max_file_bytes=settings.attachment_max_bytes,
                max_draft_files=settings.attachment_draft_max_files,
                max_draft_bytes=settings.attachment_draft_max_bytes,
            ),
        )

    async def help_tickets(self) -> HelpTicketsSettings:
        """Return the help and ticket settings of the active branding."""
        return _help_tickets_of(_branding(await self._active()))

    async def put_help_tickets(
        self, payload: HelpTicketsSettings, actor: str
    ) -> HelpTicketsSettings:
        """Save the help and ticket settings as a new active version.

        The method copies the active branding, replaces ``help`` and ``tickets`` and
        writes it as a new active version with a config revision and the
        ``config_activation`` audit entry, as ``save`` does.
        """
        help_settings = HelpSettings(wikiUrl=payload.wiki_url)
        ticket_settings = TicketSettings(
            publicEnabled=payload.public_enabled,
            notifyNew=payload.notify_new,
            retentionMonths=payload.retention_months,
        )
        active = await self._active()
        latest = await self._latest()
        branding = _branding(active).model_copy(
            update={"help": help_settings, "tickets": ticket_settings}
        )
        snapshot = branding.model_dump(by_alias=True)
        base = latest.version if latest is not None else 0
        await self.session.execute(
            update(SiteConfigVersion).where(SiteConfigVersion.active.is_(True)).values(active=False)
        )
        row = SiteConfigVersion(version=base + 1, active=True, branding=snapshot, created_by=actor)
        self.session.add(row)
        await self.session.flush()
        await ConfigRevisionService(self.session).record(
            entity_type=ENTITY_SITE_CONFIG,
            entity_id=GLOBAL_ID,
            snapshot=snapshot,
            actor=actor,
            action=AuditAction.CONFIG_ACTIVATION,
            extra_data={"siteConfigVersion": row.version, "section": "helpTickets"},
        )
        await self.session.commit()
        return _help_tickets_of(branding)

    async def manifest(self, scheme: Literal["light", "dark"] = "light") -> dict:
        """Build the PWA manifest from the active branding config.

        ``name`` and ``short_name`` come from the config. An empty value falls
        back to the default. ``theme_color`` and ``background_color`` follow
        ``scheme``. All other fields are static.
        """
        branding = _branding(await self._active())
        return {
            "name": branding.app_name.strip() or DEFAULT_APP_NAME,
            "short_name": branding.app_short_name.strip() or DEFAULT_APP_SHORT_NAME,
            **_MANIFEST_BASE,
            "theme_color": MANIFEST_COLORS[scheme],
            "background_color": MANIFEST_COLORS[scheme],
        }


def _with_help_tickets_of(branding: Branding, source: Branding) -> dict:
    """Dump ``branding`` with ``help`` and ``tickets`` taken from ``source``."""
    return branding.model_copy(update={"help": source.help, "tickets": source.tickets}).model_dump(
        by_alias=True
    )


def _help_tickets_of(branding: Branding) -> HelpTicketsSettings:
    return HelpTicketsSettings(
        wikiUrl=branding.help.wiki_url,
        publicEnabled=branding.tickets.public_enabled,
        notifyNew=branding.tickets.notify_new,
        retentionMonths=branding.tickets.retention_months,
    )
