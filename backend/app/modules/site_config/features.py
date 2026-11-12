"""The feature switches of the platform (§F/administration/admin/000756).

An admin switches each feature on and off. The switches are a part of the branding of
the site configuration, so a save writes a new version and an audit entry. This module
holds the names, the stored switches, the rule that turns them into the features that
are on, and the read that every module uses. A switch closes a feature on the server
(§F/administration/admin/000757): :func:`feature_gate` answers 404 ``feature_disabled``.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_config.models import SiteConfigVersion
from app.shared.errors import NotFoundError
from app.shared.schemas import FrozenStrictCamelModel


class Feature(StrEnum):
    """A part of the platform that has a switch, in the order of the navigation."""

    TODOS = "todos"
    CALENDAR = "calendar"
    MEETINGS = "meetings"
    VOTING = "voting"
    BUDGET = "budget"
    INVOICES = "invoices"
    TICKETS = "tickets"


#: The features a feature needs (§F/administration/admin/000760). A feature is off while
#: one of them is off. An invoice books on a Kostenstelle, so `Rechnungen` needs `Budget`.
REQUIRES: Mapping[Feature, frozenset[Feature]] = {
    Feature.INVOICES: frozenset({Feature.BUDGET}),
}

ALL_FEATURES: frozenset[Feature] = frozenset(Feature)


class FeatureSwitches(FrozenStrictCamelModel, frozen=True):
    """The stored switches: what the admin set, one per feature.

    A configuration that does not name a feature reads as on. The stored switch of a
    feature stays while a feature it needs is off, so it returns to that state when the
    other feature goes on again.
    """

    todos: bool = Field(default=True)
    calendar: bool = Field(default=True)
    meetings: bool = Field(default=True)
    voting: bool = Field(default=True)
    budget: bool = Field(default=True)
    invoices: bool = Field(default=True)
    tickets: bool = Field(default=True)

    def is_set(self, feature: Feature) -> bool:
        """Return the stored switch of ``feature``."""
        return bool(getattr(self, feature.value))


def enabled_features(switches: FeatureSwitches) -> frozenset[Feature]:
    """Return the features that are on: the own switch and each needed feature is on."""
    return frozenset(
        feature
        for feature in Feature
        if switches.is_set(feature)
        and all(switches.is_set(needed) for needed in REQUIRES.get(feature, frozenset()))
    )


def switches_of(raw: object) -> FeatureSwitches:
    """Read the stored ``features`` value of a branding; anything else gives the defaults."""
    return FeatureSwitches.model_validate(raw) if isinstance(raw, dict) else FeatureSwitches()


async def active_switches(session: AsyncSession) -> FeatureSwitches:
    """Return the stored switches of the active site configuration.

    The read selects only the ``features`` value, because the branding also holds the
    inline logos and every gated request runs this read.
    """
    raw = (
        await session.scalars(
            select(SiteConfigVersion.branding["features"]).where(
                SiteConfigVersion.active.is_(True)
            )
        )
    ).first()
    return switches_of(raw)


async def active_features(session: AsyncSession) -> frozenset[Feature]:
    """Return the features that are on in the active site configuration."""
    return enabled_features(await active_switches(session))


async def feature_on(session: AsyncSession, feature: Feature) -> bool:
    """Return whether ``feature`` is on in the active site configuration."""
    return feature in await active_features(session)


class FeatureDisabledError(NotFoundError):
    """A route or a job of a feature that is off (404 ``feature_disabled``)."""

    def __init__(self, features: frozenset[Feature]) -> None:
        """Name the features that are off in the detail."""
        names = ", ".join(sorted(f.value for f in features))
        super().__init__(f"This feature is switched off: {names}.", code="feature_disabled")
