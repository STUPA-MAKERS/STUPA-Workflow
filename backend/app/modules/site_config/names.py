"""The names of the platform from the branding, with the built-in fallbacks.

Every place that names the platform outside the app frame (the page head, the PWA
manifest, the calendar feeds) reads the name here, so an empty field gives the same
built-in name everywhere.
"""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_config.branding import Branding
from app.modules.site_config.reads import active_branding

#: Fallback app names for the case where the branding leaves them empty. They match the
#: built-in tags of ``frontend/src/index.html`` and ``frontend/public/manifest.webmanifest``.
DEFAULT_APP_NAME = "STUPA Workflow"
DEFAULT_APP_SHORT_NAME = "STUPA"

_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def app_name(branding: Branding) -> str:
    """Return the app name of the branding, or the built-in name."""
    return " ".join(branding.app_name.split()) or DEFAULT_APP_NAME


def app_short_name(branding: Branding) -> str:
    """Return the short name of the branding, or the built-in short name."""
    return " ".join(branding.app_short_name.split()) or DEFAULT_APP_SHORT_NAME


def name_slug(name: str) -> str:
    """Return a file name part of a name: lower case ASCII letters, digits and hyphens.

    A name with no such character gives the slug of the built-in short name.
    """
    ascii_name = name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    slug = _NOT_SLUG.sub("-", ascii_name.replace("ß", "ss")).strip("-")
    return slug or DEFAULT_APP_SHORT_NAME.lower()


async def active_short_name(session: AsyncSession) -> str:
    """Return the short name of the active branding, or the built-in short name."""
    return app_short_name(await active_branding(session))
