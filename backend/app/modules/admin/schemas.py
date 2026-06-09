"""API-Schemata des Admin-/Config-Moduls (T-24, api.md »admin«).

camelCase im JSON (per-Name befüllbar, Out-Modelle via ``serialization_alias``).
Quelle der Wahrheit ist ``api.md``; die DTO-Form ist 1:1 das, wogegen das Admin-FE
(T-34, #54) gebaut ist, damit dessen ``TODO(T-24)``-Mock-Grenzen scharf schalten.

Feld-/Flow-/Comparison-Definitionen sind die ``config_schemas``-Modelle (Single
Source). Branding ist ``admin.branding.Branding``.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.admin.branding import Branding
from app.shared.config_schemas import ComparisonOffers, EventName, FlowGraph
from app.shared.i18n import I18nMap


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

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


class GremiumCreate(_CamelModel):
    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    cd_variant: str = Field(default="stupa", alias="cdVariant")
    default_lang: str = Field(default="de", alias="defaultLang")
    allow_vote_delegation: bool = Field(default=False, alias="allowVoteDelegation")


class GremiumUpdate(_CamelModel):
    name: str | None = None
    slug: str | None = None
    cd_variant: str | None = Field(default=None, alias="cdVariant")
    default_lang: str | None = Field(default=None, alias="defaultLang")
    allow_vote_delegation: bool | None = Field(default=None, alias="allowVoteDelegation")


# --------------------------------------------------------------------------- #
# Gremium-Rollen + Mitgliedschaften (#42)
# --------------------------------------------------------------------------- #
class GremiumRoleOut(_CamelModel):
    id: UUID
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    key: str
    name: I18nMap
    # Pflichtrollen (Vorstand/Manager/Mitglied) sind in jedem Gremium vorhanden und
    # nicht löschbar; das FE blendet die Löschen-Aktion dafür aus (#Meetings).
    forced: bool = False
    # Granulare Sitzungs-Berechtigungen dieser Rolle (session.manage/vote.manage/
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
    active_form_version_id: UUID | None = Field(
        serialization_alias="activeFormVersionId"
    )
    active_flow_version_id: UUID | None = Field(
        serialization_alias="activeFlowVersionId"
    )


class ApplicationTypeCreate(_CamelModel):
    key: str = Field(min_length=1)
    name_i18n: I18nMap = Field(alias="nameI18n")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    has_budget: bool = Field(default=False, alias="hasBudget")
    comparison_offers: ComparisonOffers | None = Field(
        default=None, alias="comparisonOffers"
    )


class ApplicationTypeUpdate(_CamelModel):
    name_i18n: I18nMap | None = Field(default=None, alias="nameI18n")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    has_budget: bool | None = Field(default=None, alias="hasBudget")
    comparison_offers: ComparisonOffers | None = Field(
        default=None, alias="comparisonOffers"
    )


# --------------------------------------------------------------------------- #
# Flow-Version (mirror der Form-Version, T-11)
# --------------------------------------------------------------------------- #
class FlowVersionCreate(_CamelModel):
    """Neue Flow-Version anlegen (Graph wird ``validate_flow_graph``-geprüft)."""

    graph: FlowGraph
    activate: bool = True


class FlowVersionOut(_CamelModel):
    id: UUID
    # ``None`` für den globalen Flow (#28).
    application_type_id: UUID | None = Field(serialization_alias="applicationTypeId")
    version: int
    active: bool


# --------------------------------------------------------------------------- #
# Rollen / RBAC
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


class RoleUpdate(_CamelModel):
    label: I18nMap | None = None
    permissions: list[str] | None = None


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
    """OIDC-Principal + dessen Rollenzuweisungen (Rollen-/Rechte-UI, #72)."""

    id: UUID
    sub: str
    email: str | None
    display_name: str | None = Field(serialization_alias="displayName")
    last_login: str | None = Field(serialization_alias="lastLogin")
    active: bool = True
    assignments: list[RoleAssignmentOut]


class PrincipalUpdate(_CamelModel):
    """``PATCH /admin/principals/{id}`` — aktivieren/deaktivieren (#30)."""

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
# Webhooks (api.md `webhook.manage`)
# --------------------------------------------------------------------------- #
class WebhookOut(_CamelModel):
    id: UUID
    name: str
    url: str
    events: list[EventName]
    active: bool


class WebhookCreate(_CamelModel):
    """Neuer Webhook. Ein vom FE mitgesendetes leeres ``id`` wird ignoriert."""

    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    # Trigger sind optional (TASKS #6) — sie kommen i. d. R. aus dem Flow-Graph.
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


# --------------------------------------------------------------------------- #
# Site-Config / Branding (#21) — Draft/Activate-Semantik wie vom T-34-FE erwartet
# --------------------------------------------------------------------------- #
class SiteConfigOut(_CamelModel):
    """Aktive Branding-Config + aktueller Draft + Änderungsflag (FE-Kontrakt)."""

    version: int
    active: Branding
    draft: Branding
    has_draft_changes: bool = Field(serialization_alias="hasDraftChanges")


class PublicSiteConfigOut(_CamelModel):
    """Öffentliche (auth-freie) aktive Branding-Config fürs FE-Rendering (#21)."""

    version: int
    branding: Branding
