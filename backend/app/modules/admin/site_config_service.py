"""Site-config and branding service.

The service versions the config like form and flow. An edit goes to the draft,
either as a new inactive version or in place on the existing draft. An edit
never touches the active version.

Activation flips ``active`` and writes a ``config_activation`` audit entry. A
partial unique index allows at most one active version.

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
from app.modules.audit.service import record as audit_record
from app.modules.config_revision.service import (
    ENTITY_SITE_CONFIG,
    GLOBAL_ID,
    ConfigRevisionService,
)
from app.settings import get_settings
from app.shared.errors import ConflictError

# Fallback app names for the case where the config leaves them empty. They match the
# defaults in ``frontend/public/manifest.webmanifest``.
DEFAULT_APP_NAME = "STUPA Antragsplattform"
DEFAULT_APP_SHORT_NAME = "STUPA"

# The page background of the design system per theme (``--color-bg`` of the ui-kit
# tokens, ``THEME_COLOR`` of the frontend ThemeService). An installed Android app paints
# its status and navigation bar with these manifest colours, and the manifest has no
# per-scheme variant, so the frontend links ``?scheme=dark`` while the dark theme is in
# effect.
MANIFEST_COLORS: dict[str, str] = {"light": "#f6f7f5", "dark": "#101211"}

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
        """Save the branding as the open draft.

        ``help`` and ``tickets`` in the payload are ignored: the draft keeps the
        values of the open draft, or of the active version without one. The
        "Hilfe & Tickets" page is the only writer of these two sections, because an
        editor that loaded the branding earlier sends stale values back, and an
        activation of them would switch anonymous reports on again unnoticed.
        """
        latest = await self._latest()
        current = latest if latest is not None and not latest.active else None
        source = _branding(current) if current is not None else _branding(await self._active())
        payload = _with_help_tickets_of(branding, source)
        if latest is not None and not latest.active:
            # The latest version is an open draft. Update it in place.
            latest.branding = payload
            target_id = latest.id
        else:
            # No open draft exists. Add an inactive draft above the active version.
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
            update(SiteConfigVersion).where(SiteConfigVersion.active.is_(True)).values(active=False)
        )
        latest.active = True
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
        """Replay a branding config as the new active version (restore or revert).

        The method creates a new active ``SiteConfigVersion`` from the snapshot
        and deactivates the rest. It writes a ``config_revision`` entry plus the
        linked audit entry. Earlier versions stay. ``help`` and ``tickets`` keep
        the values of the active version, because the "Hilfe & Tickets" page is
        their only writer: a restore of an older snapshot would otherwise bring
        back its ticket settings, or the defaults (``publicEnabled=true``) for a
        snapshot without them. An open draft is not touched.
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

        The admin page saves directly, without draft and activate. The method copies
        the active branding, replaces ``help`` and ``tickets`` and writes it as a new
        active version with a config revision and the ``config_activation`` audit
        entry, as ``activate`` does. An open draft gets the same two values and moves
        above the new version, so it stays the draft and a later activation of it
        does not revert them.
        """
        help_settings = HelpSettings(wikiUrl=payload.wiki_url)
        ticket_settings = TicketSettings(
            publicEnabled=payload.public_enabled,
            notifyNew=payload.notify_new,
            retentionMonths=payload.retention_months,
        )
        active = await self._active()
        latest = await self._latest()
        draft = latest if latest is not None and not latest.active else None
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
        if draft is not None:
            draft.version = base + 2
            draft.branding = {
                **(draft.branding or {}),
                "help": help_settings.model_dump(by_alias=True),
                "tickets": ticket_settings.model_dump(by_alias=True),
            }
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
        color = MANIFEST_COLORS[scheme]
        return {
            "name": branding.app_name.strip() or DEFAULT_APP_NAME,
            "short_name": branding.app_short_name.strip() or DEFAULT_APP_SHORT_NAME,
            **_MANIFEST_BASE,
            "theme_color": color,
            "background_color": color,
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
