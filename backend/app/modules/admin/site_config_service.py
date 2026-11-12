"""Site-config and branding service.

The service versions the config like form and flow. A save writes a new active
version and deactivates the one before; there is no draft. Each save writes a
config revision and a ``config_activation`` audit entry. A partial unique index
allows at most one active version. Inactive rows from the time of the draft stay
as history and are never read as a draft.

``admin.branding.Branding`` validates the branding. A logo must be an image and
inline SVG is not allowed. Invalid branding fails with 422. Every write of a
branding from a request (save, restore, revert) scans each inline logo with ClamAV
before the store (``files.scanner.scan_or_raise``), because the stored bytes are the
bytes of the client: an infected logo fails with 415, and a missing or failed
scanner in production with 503.
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.schemas import (
    AttachmentLimitsOut,
    HelpTicketsSettings,
    PublicHelpOut,
    PublicSiteConfigOut,
    PublicTicketsOut,
    SiteConfigOut,
)
from app.modules.application_types.models import ApplicationType
from app.modules.applications.guest_settings import load_guest_settings
from app.modules.audit.actions import AuditAction
from app.modules.config_revision.service import (
    ENTITY_SITE_CONFIG,
    GLOBAL_ID,
    ConfigRevisionService,
)
from app.modules.files.scanner import scan_or_raise
from app.modules.site_config.branding import (
    Branding,
    HelpSettings,
    PublicBranding,
    TicketSettings,
)
from app.modules.site_config.feature_uses import FeatureUse, flow_uses, type_uses, uses_of
from app.modules.site_config.features import (
    ALL_FEATURES,
    Feature,
    FeatureSwitches,
    enabled_features,
)
from app.modules.site_config.models import SiteConfigVersion
from app.modules.site_config.reads import branding_of
from app.settings import Settings, get_settings
from app.shared.errors import ConflictError

#: Fallback app names for the case where the config leaves them empty. They match the
#: defaults in ``frontend/public/manifest.webmanifest``.
DEFAULT_APP_NAME = "STUPA Antragsplattform"
DEFAULT_APP_SHORT_NAME = "STUPA"

#: The manifest colour per theme: the surface of the bottom bar (``--color-surface-3`` of
#: the ui-kit tokens). Chrome cannot draw an installed Android app under the system
#: navigation bar and paints that bar with a manifest colour, ``theme_color`` or
#: ``background_color`` depending on the version. Both take the bottom bar surface, so the
#: two bars meet without a seam in every version; the splash screen shows the same colour.
#: The status bar follows the ``theme-color`` meta tag of the page (frontend ThemeService),
#: so it keeps the page background. The manifest has no per-scheme variant, so the
#: frontend links ``?scheme=dark`` while the dark theme is in effect, and
#: ``?scheme=contrast`` while "Hoher Kontrast" is on, because its bottom bar is black.
MANIFEST_COLORS: dict[str, str] = {
    "light": "#e6e9e5",
    "dark": "#262a27",
    "contrast": "#000000",
}

#: The colour schemes that the manifest route serves.
ManifestScheme = Literal["light", "dark", "contrast"]

#: The icon of a manifest shortcut: the app icon at 96 px, the size that Android asks for.
_SHORTCUT_ICON: dict[str, Any] = {
    "src": "icons/icon-96x96.png",
    "sizes": "96x96",
    "type": "image/png",
}

#: The static manifest fields, that is everything except name and short_name.
#: They are the single source of truth for the PWA manifest that the API serves.
#: The fixed ``id`` keeps an installed app the same app when ``start_url`` changes.
#: The shortcut names are German like ``lang`` and equal those of
#: ``frontend/public/manifest.webmanifest``. ``launch_handler`` opens an app link in
#: the running app, not in a second window.
_MANIFEST_BASE: dict[str, Any] = {
    "description": (
        "Antragsplattform des Studierendenparlaments — Anträge, Abstimmungen, "
        "Sitzungsprotokolle und Budget."
    ),
    "lang": "de",
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
    "shortcuts": [
        {"name": "Neuer Antrag", "url": "apply", "icons": [_SHORTCUT_ICON]},
        {"name": "Meine To-Dos", "url": "todos", "icons": [_SHORTCUT_ICON]},
        {"name": "Sitzungen", "url": "meetings", "icons": [_SHORTCUT_ICON]},
    ],
    "launch_handler": {"client_mode": ["navigate-existing", "auto"]},
}


class SiteConfigService:
    """Site-config operations bound to an ``AsyncSession``.

    Without explicit settings the logo scan reads ``get_settings()``, so the scan
    never falls back to a skip.
    """

    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        """Bind the service to a session and the settings."""
        self.session = session
        self.settings = settings

    async def _scan_logos(self, branding: Branding) -> None:
        """Scan every inline logo of the branding before the store.

        Raises:
            UnsupportedMediaTypeError: The virus scan found a signature (415).
            ServiceUnavailableError: The virus scan is unavailable in production (503).
        """
        settings = self.settings or get_settings()
        for asset in branding.logos.values():
            data = asset.inline_bytes()
            if data is not None:
                await scan_or_raise(data, settings)

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
        return SiteConfigOut(version=active.version if active else 0, branding=branding_of(active))

    async def save(self, branding: Branding, actor: str) -> SiteConfigOut:
        """Save the branding as the new active version.

        The admin pages save directly, without a draft. ``help``, ``tickets`` and
        ``features`` in the payload are ignored and keep the values of the active
        version, because the pages "Hilfe & Tickets" and "Funktionen" are their only
        writers: an editor that loaded the branding earlier sends stale values back, and
        a save of them would switch anonymous reports or a feature on again unnoticed.
        """
        return await self.restore_branding(branding, actor, action=AuditAction.CONFIG_ACTIVATION)

    async def restore_branding(
        self,
        branding: Branding,
        actor: str,
        *,
        action: AuditAction = AuditAction.CONFIG_CHANGE,
        extra_data: dict[str, Any] | None = None,
        with_features: bool = False,
    ) -> SiteConfigOut:
        """Replay a branding config as the new active version (restore or revert).

        The method creates a new active ``SiteConfigVersion`` from the snapshot
        and deactivates the rest. It writes a ``config_revision`` entry plus the
        linked audit entry. Earlier versions stay. ``help`` and ``tickets`` keep
        the values of the active version, because the "Hilfe & Tickets" page is
        their only writer: a restore of an older snapshot would otherwise bring
        back its ticket settings, or the defaults (``publicEnabled=true``) for a
        snapshot without them. ``features`` keeps the active value for the same reason,
        and because the switches need their own permission. ``with_features`` is the
        revert of a save of the page "Funktionen": it takes only the switches of the
        snapshot and keeps the rest of the active branding, and it refuses a feature in
        use like the save does. The inline logos pass the virus scan first
        (``_scan_logos``).

        Raises:
            ConflictError: ``with_features`` would switch off a feature in use (409
                ``feature_in_use``).
        """
        await self._scan_logos(branding)
        active = branding_of(await self._active())
        if with_features:
            await self._refuse_in_use(branding.features)
        payload = (
            active.model_copy(update={"features": branding.features}).model_dump(by_alias=True)
            if with_features
            else _with_sections_of(branding, active)
        )
        await self._write(
            payload,
            actor,
            action=action,
            extra_data={**(extra_data or {}), **({"section": "features"} if with_features else {})},
        )
        await self.session.commit()
        return await self.get()

    async def _write(
        self,
        snapshot: dict[str, Any],
        actor: str,
        *,
        action: AuditAction,
        extra_data: dict[str, Any],
    ) -> None:
        """Add ``snapshot`` as the new active version with its config revision.

        The active version is deactivated before the add, because the partial unique
        index allows one active row. The caller commits.
        """
        latest = await self._latest()
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
            action=action,
            extra_data={**extra_data, "siteConfigVersion": row.version},
        )

    async def public(self) -> PublicSiteConfigOut:
        """Return the public active branding config (auth-free).

        The response also holds ``confirmTtlHours`` and ``linkTtlDays`` from the
        guest settings, so the wizard can tell a guest how long the confirmation
        waits and how long the link works. ``attachmentLimits`` comes from the
        settings of the draft upload.
        """
        active = await self._active()
        guest = await load_guest_settings(self.session)
        settings = get_settings()
        branding = branding_of(active)
        return PublicSiteConfigOut(
            version=active.version if active else 0,
            branding=PublicBranding.model_validate(branding.model_dump(by_alias=True)),
            help=PublicHelpOut(wiki_url=branding.help.wiki_url),
            tickets=PublicTicketsOut(public_enabled=branding.tickets.public_enabled),
            features=_enabled_switches(branding.features),
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
        return _help_tickets_of(branding_of(await self._active()))

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
        branding = branding_of(await self._active()).model_copy(
            update={"help": help_settings, "tickets": ticket_settings}
        )
        await self._write(
            branding.model_dump(by_alias=True),
            actor,
            action=AuditAction.CONFIG_ACTIVATION,
            extra_data={"section": "helpTickets"},
        )
        await self.session.commit()
        return _help_tickets_of(branding)

    async def features(self) -> FeatureSwitches:
        """Return the stored feature switches of the active branding."""
        return branding_of(await self._active()).features

    async def put_features(self, payload: FeatureSwitches, actor: str) -> FeatureSwitches:
        """Save the feature switches as a new active version.

        The method copies the active branding, replaces ``features`` and writes it as a
        new active version with a config revision and the ``config_activation`` audit
        entry. The revision carries ``section = features``, so a revert of the entry
        sets only the switches back. The caller commits.

        Raises:
            ConflictError: The save would switch off a feature that the active flow
                or an Antragsart uses (409 ``feature_in_use``). ``errors`` names
                each use.
        """
        await self._refuse_in_use(payload)
        branding = branding_of(await self._active()).model_copy(update={"features": payload})
        await self._write(
            branding.model_dump(by_alias=True),
            actor,
            action=AuditAction.CONFIG_ACTIVATION,
            extra_data={"section": "features"},
        )
        return payload

    async def _refuse_in_use(self, switches: FeatureSwitches) -> None:
        """Refuse switches that turn off a feature in use.

        An Antrag must not stop in a state that waits for a vote or a meeting that
        nobody can open, so the admin removes each use first.

        Raises:
            ConflictError: The active flow or an Antragsart uses a feature that
                ``switches`` turns off (409 ``feature_in_use``).
        """
        blocking = uses_of(await self._uses(), ALL_FEATURES - enabled_features(switches))
        if blocking:
            raise ConflictError(
                "The Antrag flow or an Antragsart uses a feature that would go off.",
                code="feature_in_use",
                errors=[use.as_error() for use in blocking],
            )

    async def _uses(self) -> tuple[FeatureUse, ...]:
        """Return every use of a feature by the active flow and the Antragsarten."""
        from app.modules.admin.service.flow import FlowOps

        graph = await FlowOps(self.session).get_active_global_flow()
        budget_types = (
            await self.session.scalars(
                select(ApplicationType.name_i18n)
                .where(ApplicationType.has_budget.is_(True))
                .order_by(ApplicationType.key)
            )
        ).all()
        return (*flow_uses(graph), *type_uses(budget_types))

    async def manifest(self, scheme: ManifestScheme = "light") -> dict[str, Any]:
        """Build the PWA manifest from the active branding config.

        ``name`` and ``short_name`` come from the config. An empty value falls
        back to the default. ``theme_color`` and ``background_color`` follow
        ``scheme``. All other fields are static.
        """
        branding = branding_of(await self._active())
        return {
            "name": branding.app_name.strip() or DEFAULT_APP_NAME,
            "short_name": branding.app_short_name.strip() or DEFAULT_APP_SHORT_NAME,
            **_MANIFEST_BASE,
            "theme_color": MANIFEST_COLORS[scheme],
            "background_color": MANIFEST_COLORS[scheme],
        }


def _with_sections_of(branding: Branding, source: Branding) -> dict[str, Any]:
    """Dump ``branding`` with ``help``, ``tickets`` and ``features`` taken from ``source``."""
    return branding.model_copy(
        update={"help": source.help, "tickets": source.tickets, "features": source.features}
    ).model_dump(by_alias=True)


def _enabled_switches(switches: FeatureSwitches) -> FeatureSwitches:
    """Return the features that are on as switches, for the public config."""
    enabled = enabled_features(switches)
    return FeatureSwitches(**{feature.value: feature in enabled for feature in Feature})


def _help_tickets_of(branding: Branding) -> HelpTicketsSettings:
    return HelpTicketsSettings(
        wikiUrl=branding.help.wiki_url,
        publicEnabled=branding.tickets.public_enabled,
        notifyNew=branding.tickets.notify_new,
        retentionMonths=branding.tickets.retention_months,
    )
