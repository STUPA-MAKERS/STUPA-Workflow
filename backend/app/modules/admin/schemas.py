"""API schemas for the admin/config module.

camelCase in JSON (populatable by name, out models via ``serialization_alias``).
Field/flow/comparison definitions come from the ``config_schemas`` models;
branding is ``admin.branding.Branding``.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.admin.branding import Branding
from app.shared.config_schemas import ComparisonOffers, EventName, FlowGraph
from app.shared.i18n import I18nMap
from app.shared.permissions import PERMISSION_CATALOGUE


def _validate_permissions(perms: list[str] | None) -> list[str] | None:
    """Reject any key not in PERMISSION_CATALOGUE (→ 422), preserve order/dedup."""
    if perms is None:
        return None
    catalogue = set(PERMISSION_CATALOGUE)
    unknown = [p for p in perms if p not in catalogue]
    if unknown:
        raise ValueError(f"unknown permission(s): {', '.join(sorted(set(unknown)))}")
    seen: set[str] = set()
    return [p for p in perms if not (p in seen or seen.add(p))]


class _CamelModel(BaseModel):
    """camelCase aliases in JSON; fields populatable by name."""

    model_config = ConfigDict(populate_by_name=True)


# --------------------------------------------------------------------------- #
# Gremium
# --------------------------------------------------------------------------- #
class GremiumOut(_CamelModel):
    id: UUID
    name: str
    slug: str
    cd_variant: str = Field(serialization_alias="cdVariant")
    default_lang: str = Field(serialization_alias="defaultLang")
    allow_vote_delegation: bool = Field(serialization_alias="allowVoteDelegation")
    # Lead time (minutes before meeting start) for non-pool delegations; 0 = until start.
    delegation_lead_minutes: int = Field(
        default=0, serialization_alias="delegationLeadMinutes"
    )
    # Allow delegation to users outside gremium & substitute pool.
    delegation_allow_external: bool = Field(
        default=False, serialization_alias="delegationAllowExternal"
    )
    # Default quorum in % of eligible voters (0-100); None = none.
    quorum_percent: int | None = Field(
        default=None, serialization_alias="quorumPercent"
    )


class GremiumCreate(_CamelModel):
    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    cd_variant: str = Field(default="stupa", alias="cdVariant")
    default_lang: str = Field(default="de", alias="defaultLang")
    allow_vote_delegation: bool = Field(default=False, alias="allowVoteDelegation")
    delegation_lead_minutes: int = Field(
        default=0, alias="delegationLeadMinutes", ge=0, le=60 * 24 * 30
    )
    delegation_allow_external: bool = Field(
        default=False, alias="delegationAllowExternal"
    )
    quorum_percent: int | None = Field(
        default=None, alias="quorumPercent", ge=0, le=100
    )


class GremiumUpdate(_CamelModel):
    name: str | None = None
    slug: str | None = None
    cd_variant: str | None = Field(default=None, alias="cdVariant")
    default_lang: str | None = Field(default=None, alias="defaultLang")
    allow_vote_delegation: bool | None = Field(default=None, alias="allowVoteDelegation")
    delegation_lead_minutes: int | None = Field(
        default=None, alias="delegationLeadMinutes", ge=0, le=60 * 24 * 30
    )
    delegation_allow_external: bool | None = Field(
        default=None, alias="delegationAllowExternal"
    )
    quorum_percent: int | None = Field(
        default=None, alias="quorumPercent", ge=0, le=100
    )


class GremiumMailRecipients(_CamelModel):
    """Additional protocol recipients of a gremium.

    These addresses receive finalized protocols in addition to active gremium
    members. Light plausibility check instead of full RFC validation."""

    recipients: list[str] = Field(default_factory=list)

    @field_validator("recipients")
    @classmethod
    def _emails_plausible(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in v:
            addr = raw.strip()
            if not addr:
                continue
            if "@" not in addr[1:-1] or " " in addr:
                raise ValueError(f"not a plausible email address: {addr!r}")
            cleaned.append(addr)
        # Preserve order, drop duplicates (case-insensitive).
        seen: set[str] = set()
        return [a for a in cleaned if not (a.lower() in seen or seen.add(a.lower()))]


# --------------------------------------------------------------------------- #
# Gremium roles + memberships
# --------------------------------------------------------------------------- #
class GremiumRoleOut(_CamelModel):
    id: UUID
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    key: str
    name: I18nMap
    # Forced roles exist in every gremium and are not deletable; the frontend
    # hides the delete action for them.
    forced: bool = False
    # Granular meeting permissions of this role (session.manage/vote.manage/
    # vote.cast/protocol.write).
    permissions: list[str] = Field(default_factory=list)


class GremiumRoleCreate(_CamelModel):
    key: str = Field(min_length=1)
    name: I18nMap = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)


class GremiumRoleUpdate(_CamelModel):
    name: I18nMap | None = None
    permissions: list[str] | None = None


class GremiumMembershipOut(_CamelModel):
    id: UUID
    principal_id: UUID = Field(serialization_alias="principalId")
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    gremium_role_id: UUID = Field(serialization_alias="gremiumRoleId")
    valid_from: str | None = Field(serialization_alias="validFrom")
    valid_until: str | None = Field(serialization_alias="validUntil")


class GremiumMembershipCreate(_CamelModel):
    principal_id: UUID = Field(alias="principalId")
    gremium_role_id: UUID = Field(alias="gremiumRoleId")
    valid_from: str | None = Field(default=None, alias="validFrom")
    valid_until: str | None = Field(default=None, alias="validUntil")


# --------------------------------------------------------------------------- #
# Application-Type
# --------------------------------------------------------------------------- #
class ApplicationTypeOut(_CamelModel):
    id: UUID
    gremium_id: UUID | None = Field(serialization_alias="gremiumId")
    key: str
    name_i18n: I18nMap = Field(serialization_alias="nameI18n")
    has_budget: bool = Field(serialization_alias="hasBudget")
    comparison_offers: dict | None = Field(serialization_alias="comparisonOffers")
    retention_months: int | None = Field(default=None, serialization_alias="retentionMonths")
    active_form_version_id: UUID | None = Field(
        serialization_alias="activeFormVersionId"
    )


class ApplicationTypeCreate(_CamelModel):
    key: str = Field(min_length=1)
    name_i18n: I18nMap = Field(alias="nameI18n")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    has_budget: bool = Field(default=False, alias="hasBudget")
    comparison_offers: ComparisonOffers | None = Field(
        default=None, alias="comparisonOffers"
    )
    retention_months: int | None = Field(
        default=None, alias="retentionMonths", ge=1
    )


class ApplicationTypeUpdate(_CamelModel):
    name_i18n: I18nMap | None = Field(default=None, alias="nameI18n")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    has_budget: bool | None = Field(default=None, alias="hasBudget")
    comparison_offers: ComparisonOffers | None = Field(
        default=None, alias="comparisonOffers"
    )
    retention_months: int | None = Field(
        default=None, alias="retentionMonths", ge=1
    )


# --------------------------------------------------------------------------- #
# Flow version
# --------------------------------------------------------------------------- #
class FlowVersionCreate(_CamelModel):
    """Create a new flow version (graph checked via ``validate_flow_graph``)."""

    graph: FlowGraph
    activate: bool = True


class FlowVersionOut(_CamelModel):
    """The single global flow — per-type flows no longer exist."""

    id: UUID
    version: int
    active: bool


# --------------------------------------------------------------------------- #
# Roles / RBAC
# --------------------------------------------------------------------------- #
class RoleOut(_CamelModel):
    id: UUID
    key: str
    label: I18nMap
    permissions: list[str]


class RoleCreate(_CamelModel):
    key: str = Field(min_length=1)
    label: I18nMap = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)

    @field_validator("permissions")
    @classmethod
    def _check_permissions(cls, value: list[str]) -> list[str]:
        return _validate_permissions(value) or []


class RoleUpdate(_CamelModel):
    label: I18nMap | None = None
    permissions: list[str] | None = None

    @field_validator("permissions")
    @classmethod
    def _check_permissions(cls, value: list[str] | None) -> list[str] | None:
        return _validate_permissions(value)


class RoleAssignmentOut(_CamelModel):
    id: UUID
    principal_id: UUID = Field(serialization_alias="principalId")
    role_id: UUID = Field(serialization_alias="roleId")
    gremium_id: UUID | None = Field(serialization_alias="gremiumId")
    granted_by: str | None = Field(serialization_alias="grantedBy")
    valid_from: str | None = Field(serialization_alias="validFrom")
    valid_until: str | None = Field(serialization_alias="validUntil")
    delegate_voting: bool = Field(serialization_alias="delegateVoting")


class RoleAssignmentCreate(_CamelModel):
    principal_id: UUID = Field(alias="principalId")
    role_id: UUID = Field(alias="roleId")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    valid_from: str | None = Field(default=None, alias="validFrom")
    valid_until: str | None = Field(default=None, alias="validUntil")
    delegate_voting: bool = Field(default=False, alias="delegateVoting")


class RoleAssignmentUpdate(_CamelModel):
    role_id: UUID | None = Field(default=None, alias="roleId")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    valid_from: str | None = Field(default=None, alias="validFrom")
    valid_until: str | None = Field(default=None, alias="validUntil")
    delegate_voting: bool | None = Field(default=None, alias="delegateVoting")


class PrincipalOut(_CamelModel):
    """OIDC principal plus its role assignments (roles/permissions UI)."""

    id: UUID
    sub: str
    email: str | None
    display_name: str | None = Field(serialization_alias="displayName")
    last_login: str | None = Field(serialization_alias="lastLogin")
    active: bool = True
    assignments: list[RoleAssignmentOut]


class PrincipalUpdate(_CamelModel):
    """``PATCH /admin/principals/{id}`` — activate/deactivate."""

    active: bool


class GroupMappingOut(_CamelModel):
    id: UUID
    oidc_group: str = Field(serialization_alias="oidcGroup")
    role_id: UUID = Field(serialization_alias="roleId")
    gremium_id: UUID | None = Field(serialization_alias="gremiumId")


class GroupMappingCreate(_CamelModel):
    oidc_group: str = Field(alias="oidcGroup", min_length=1)
    role_id: UUID = Field(alias="roleId")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")


class GroupMappingUpdate(_CamelModel):
    oidc_group: str | None = Field(default=None, alias="oidcGroup")
    role_id: UUID | None = Field(default=None, alias="roleId")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")


# --------------------------------------------------------------------------- #
# Webhooks (`webhook.manage`)
# --------------------------------------------------------------------------- #
class WebhookOut(_CamelModel):
    id: UUID
    name: str
    url: str
    events: list[EventName]
    active: bool


class WebhookCreate(_CamelModel):
    """New webhook. An empty ``id`` sent by the frontend is ignored."""

    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    # Triggers are optional — they usually come from the flow graph.
    events: list[EventName] = Field(default_factory=list)
    active: bool = True

    @field_validator("url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("webhook url must be http(s)")
        return v


class WebhookUpdate(_CamelModel):
    name: str | None = None
    url: str | None = None
    events: list[EventName] | None = None
    active: bool | None = None

    @field_validator("url")
    @classmethod
    def _http_url(cls, v: str | None) -> str | None:
        if v is not None and not v.lower().startswith(("http://", "https://")):
            raise ValueError("webhook url must be http(s)")
        return v


class WebhookDeliveryStatusOut(_CamelModel):
    """Diagnostic view of the latest delivery state per webhook.

    Deliberately exposes no resolved IP/host topology and no response body —
    only the status class, HTTP status code (if any) and attempt count, so a
    mistyped/internal webhook can be diagnosed without leaking network details.
    ``last_state`` is condensed to ``pending``/``sent``/``dead``.
    """

    webhook_id: UUID
    last_state: str
    reason_class: str
    response_code: int | None = None
    attempts: int = 0
    last_at: str | None = None


# --------------------------------------------------------------------------- #
# Site config / branding — draft/activate semantics
# --------------------------------------------------------------------------- #
class SiteConfigOut(_CamelModel):
    """Active branding config plus current draft plus change flag."""

    version: int
    active: Branding
    draft: Branding
    has_draft_changes: bool = Field(serialization_alias="hasDraftChanges")


class PublicSiteConfigOut(_CamelModel):
    """Public (auth-free) active branding config for frontend rendering."""

    version: int
    branding: Branding
