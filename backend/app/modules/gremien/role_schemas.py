"""Schemas of the gremium roles and of the derived memberships.

The admin routes answer with them, and `gremium_roles` builds them.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.shared.i18n import I18nMap
from app.shared.schemas import FrozenCamelModel

#: A role key (global and gremium role): a lowercase letter, then lowercase letters,
#: digits and underscores. Seeds, migrations and the forced gremium roles use it as the
#: stable handle, so the update schemas have no key.
ROLE_KEY_PATTERN = r"^[a-z][a-z0-9_]*$"


class GremiumRoleOut(FrozenCamelModel, frozen=True):
    """A role of a gremium."""

    id: UUID
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    key: str
    name: I18nMap
    #: Forced roles exist in every gremium and nobody can delete them. The
    #: frontend hides the delete action for them.
    forced: bool = False
    #: Granular meeting permissions of this role: session.manage, vote.manage,
    #: vote.cast, protocol.write and protocol.finalize.
    permissions: list[str] = Field(default_factory=list)


class GremiumRoleCreate(FrozenCamelModel, frozen=True):
    """New gremium role."""

    key: str = Field(min_length=1, pattern=ROLE_KEY_PATTERN)
    name: I18nMap = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)


class GremiumRoleUpdate(FrozenCamelModel, frozen=True):
    """Partial update of a gremium role."""

    name: I18nMap | None = None
    permissions: list[str] | None = None


class GremiumMembershipOut(FrozenCamelModel, frozen=True):
    """A membership that the sync derived from the OIDC groups (read-only).

    The display name and the e-mail address of the member come with the row, so the
    members page needs no principal list. Without them a page must load every principal,
    and the principal list stops after 50 rows.

    ``active`` uses the same rule as the member count of the gremien list: the
    principal is active and the membership is valid now. The members page shows only
    the active rows, so its count agrees with the gremien list.
    """

    id: UUID
    principal_id: UUID = Field(serialization_alias="principalId")
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    gremium_role_id: UUID = Field(serialization_alias="gremiumRoleId")
    display_name: str | None = Field(default=None, serialization_alias="displayName")
    email: str | None = None
    active: bool = True
