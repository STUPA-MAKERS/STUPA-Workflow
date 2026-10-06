"""API schemas for the admin/config module.

The JSON uses camelCase. The models also accept the field names. The out models
carry the JSON name in ``serialization_alias``. The field, flow and comparison
definitions come from the ``config_schemas`` models. The branding model is
``admin.branding.Branding``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.admin.branding import Branding
from app.modules.admin.cd_logos import CdBaseVariant, LogoSlot, VendoredLogoName
from app.modules.applications.models import (
    DEFAULT_CONFIRM_TTL_HOURS,
    MAX_CONFIRM_TTL_HOURS,
)
from app.shared.config_schemas import ComparisonOffers, EventName, FlowGraph
from app.shared.i18n import I18nMap
from app.shared.permissions import PERMISSION_CATALOGUE

# A CD-variant key is a slug. It is the stable handle of the variant and never
# changes after the create.
CD_VARIANT_KEY_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

# A role key (global role and gremium role, A10) starts with a lowercase letter and
# holds lowercase letters, digits and underscores. The key is the stable handle that
# seeds, migrations and the forced gremium roles use. A key that breaks the pattern
# gives 422 on create. The update schemas have no key, because a key never changes.
ROLE_KEY_PATTERN = r"^[a-z][a-z0-9_]*$"


def _validate_permissions(perms: list[str] | None) -> list[str] | None:
    """Reject a key that is not in PERMISSION_CATALOGUE, keep the order, drop duplicates.

    Raises:
        ValueError: A key is unknown. Pydantic turns this into a 422.
    """
    if perms is None:
        return None
    catalogue = set(PERMISSION_CATALOGUE)
    unknown = [p for p in perms if p not in catalogue]
    if unknown:
        raise ValueError(f"unknown permission(s): {', '.join(sorted(set(unknown)))}")
    seen: set[str] = set()
    return [p for p in perms if not (p in seen or seen.add(p))]


class _CamelModel(BaseModel):
    """Base model with camelCase JSON aliases and population by field name."""

    model_config = ConfigDict(populate_by_name=True)


class CdVariantLogoOut(_CamelModel):
    """One logo of a CD variant. Exactly one of vendoredName / fileName is set."""

    id: UUID
    slot: LogoSlot
    position: int
    vendored_name: str | None = Field(default=None, serialization_alias="vendoredName")
    file_name: str | None = Field(default=None, serialization_alias="fileName")
    mime: str | None = None
    size: int | None = None


class CdVariantOut(_CamelModel):
    """A CD variant with its logos, ordered by slot and position."""

    id: UUID
    key: str
    name: str
    base_variant: CdBaseVariant = Field(serialization_alias="baseVariant")
    logos: list[CdVariantLogoOut] = Field(default_factory=list)


class CdVariantOptionOut(_CamelModel):
    """Slim option for the Gremium dropdown."""

    id: UUID
    key: str
    name: str


class CdVariantCreate(_CamelModel):
    key: str = Field(min_length=1, max_length=64, pattern=CD_VARIANT_KEY_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    base_variant: CdBaseVariant = Field(default="report", alias="baseVariant")


class CdVariantUpdate(_CamelModel):
    """Patch of a CD variant. ``key`` is immutable — a different value gives 409."""

    key: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    base_variant: CdBaseVariant | None = Field(default=None, alias="baseVariant")


class CdVariantLogoVendoredCreate(_CamelModel):
    """Add a logo that the render service ships. No upload and no object storage involved."""

    slot: LogoSlot
    vendored_name: VendoredLogoName = Field(alias="vendoredName")


class CdVariantLogoReorder(_CamelModel):
    """Full new order of one slot. The list must name every logo of that slot."""

    slot: LogoSlot
    logo_ids: list[UUID] = Field(alias="logoIds")


class GremiumOut(_CamelModel):
    id: UUID
    name: str
    slug: str
    cd_variant_id: UUID | None = Field(default=None, serialization_alias="cdVariantId")
    default_lang: str = Field(serialization_alias="defaultLang")
    allow_vote_delegation: bool = Field(serialization_alias="allowVoteDelegation")
    # Lead time in minutes before the meeting start, for non-pool delegations.
    # 0 = until the meeting start.
    delegation_lead_minutes: int = Field(
        default=0, serialization_alias="delegationLeadMinutes"
    )
    # Allow delegation to users outside gremium & substitute pool.
    delegation_allow_external: bool = Field(
        default=False, serialization_alias="delegationAllowExternal"
    )
    # Default quorum as a percentage of the eligible voters, from 0 to 100.
    # A None value means no quorum.
    quorum_percent: int | None = Field(
        default=None, serialization_alias="quorumPercent"
    )


class GremiumAdminOut(GremiumOut):
    """A gremium in the admin list (``GET /admin/gremien``), with its counts.

    ``memberCount`` is the number of persons with a membership in the gremium.
    ``roleCount`` is the number of gremium roles, the forced roles included. The
    public master-data list (``GET /gremien``) does not have these fields.
    """

    member_count: int = Field(default=0, serialization_alias="memberCount")
    role_count: int = Field(default=0, serialization_alias="roleCount")


class GremiumCreate(_CamelModel):
    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    cd_variant_id: UUID | None = Field(default=None, alias="cdVariantId")
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
    # Clearable to null: `model_fields_set` separates "not sent" from "set to null".
    cd_variant_id: UUID | None = Field(default=None, alias="cdVariantId")
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

    These addresses receive the finalized protocols in addition to the active
    gremium members. The validator runs a light plausibility check instead of a
    full RFC validation.
    """

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


class GremiumRoleOut(_CamelModel):
    id: UUID
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    key: str
    name: I18nMap
    # Forced roles exist in every gremium and nobody can delete them. The
    # frontend hides the delete action for them.
    forced: bool = False
    # Granular meeting permissions of this role: session.manage, vote.manage,
    # vote.cast and protocol.write.
    permissions: list[str] = Field(default_factory=list)


class GremiumRoleCreate(_CamelModel):
    key: str = Field(min_length=1, pattern=ROLE_KEY_PATTERN)
    name: I18nMap = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)


class GremiumRoleUpdate(_CamelModel):
    name: I18nMap | None = None
    permissions: list[str] | None = None


class GremiumMembershipOut(_CamelModel):
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


def _check_oidc_group(value: str) -> str:
    """Refuse a group name in the ``vote:`` namespace that the RBAC resolver reserves."""
    if value.startswith("vote:"):
        raise ValueError("the prefix 'vote:' is reserved")
    return value


class _OidcGroupField(_CamelModel):
    """The OIDC group name of a mapping, outside the reserved ``vote:`` namespace."""

    @field_validator("oidc_group", check_fields=False)
    @classmethod
    def _group(cls, value: str | None) -> str | None:
        return None if value is None else _check_oidc_group(value)


class GremiumMembershipMappingOut(_CamelModel):
    """OIDC group → membership in one gremium."""

    id: UUID
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    oidc_group: str = Field(serialization_alias="oidcGroup")


class GremiumMembershipMappingCreate(_OidcGroupField):
    oidc_group: str = Field(alias="oidcGroup", min_length=1, max_length=256)
    gremium_id: UUID = Field(alias="gremiumId")


class GremiumMembershipMappingUpdate(_OidcGroupField):
    """Change the group or the gremium of one membership mapping."""

    oidc_group: str | None = Field(default=None, alias="oidcGroup", min_length=1, max_length=256)
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")

    @model_validator(mode="after")
    def _at_least_one(self) -> GremiumMembershipMappingUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field required")
        return self


class GremiumRoleMappingOut(_CamelModel):
    """OIDC group → role in a gremium. ``gremiumId`` is the gremium of the role."""

    id: UUID
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    gremium_role_id: UUID = Field(serialization_alias="gremiumRoleId")
    oidc_group: str = Field(serialization_alias="oidcGroup")


class GremiumRoleMappingCreate(_OidcGroupField):
    oidc_group: str = Field(alias="oidcGroup", min_length=1, max_length=256)
    gremium_role_id: UUID = Field(alias="gremiumRoleId")


class GremiumRoleMappingUpdate(_OidcGroupField):
    """Change the group or the gremium role of one role mapping."""

    oidc_group: str | None = Field(default=None, alias="oidcGroup", min_length=1, max_length=256)
    gremium_role_id: UUID | None = Field(default=None, alias="gremiumRoleId")

    @model_validator(mode="after")
    def _at_least_one(self) -> GremiumRoleMappingUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field required")
        return self


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
    # The number of the active form version. ``None`` while no version is active.
    active_form_version: int | None = Field(
        default=None, serialization_alias="activeFormVersion"
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


class FlowVersionCreate(_CamelModel):
    """Create a new flow version (graph checked via ``validate_flow_graph``)."""

    graph: FlowGraph
    activate: bool = True


class FlowVersionOut(_CamelModel):
    """The single global flow. There are no per-type flows."""

    id: UUID
    version: int
    active: bool


class RoleOut(_CamelModel):
    id: UUID
    key: str
    label: I18nMap
    permissions: list[str]


class RoleCreate(_CamelModel):
    key: str = Field(min_length=1, pattern=ROLE_KEY_PATTERN)
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


class PrincipalOut(_CamelModel):
    """OIDC principal plus its role assignments (roles/permissions UI)."""

    id: UUID
    sub: str
    email: str | None
    display_name: str | None = Field(serialization_alias="displayName")
    last_login: str | None = Field(serialization_alias="lastLogin")
    active: bool = True
    assignments: list[RoleAssignmentOut]
    # The OIDC groups as of the last login. They drive the group mappings.
    oidc_groups: list[str] = Field(default_factory=list, serialization_alias="oidcGroups")
    # Account merge: set when an admin merged this (old) account into another one.
    # The account is then a locked reference and shows "merged into <name>".
    merged_into_id: UUID | None = Field(default=None, serialization_alias="mergedIntoId")
    merged_into_name: str | None = Field(default=None, serialization_alias="mergedIntoName")
    merged_at: str | None = Field(default=None, serialization_alias="mergedAt")


# Account merge (``admin/principal_merge.py``). The areas of the preview and the result,
# in display order. Each area counts the rows that the merge rewrites to the new account,
# the duplicate rows that it combines (drops, because the new account has the same row),
# and the rows that it removes (sessions, tokens, derived memberships, the feed token).
MergeArea = Literal[
    "applications",
    "versions",
    "timeline",
    "comments",
    "votes",
    "delegations",
    "substitutes",
    "attendance",
    "meetings",
    "budget",
    "config",
    "notifications",
    "roles",
    "privacy",
    "backups",
    "sessions",
    "memberships",
    "calendar",
]

# A real conflict blocks the merge. Each kind names a rule that the merged data would
# break:
# - ``ballot_same_vote``: both accounts voted in the same vote (open or secret).
# - ``delegation_same_meeting``: both accounts delegated their seat in the same meeting.
# - ``delegation_vote_twice``: both accounts received a vote transfer in the same meeting.
# - ``delegation_chain``: one account delegated to the other, or is delegator while the
#   other is delegate, in the same meeting.
# - ``attendance_differs``: both accounts have a different attendance in the same meeting.
# - ``erasure_open``: an erasure request for one of the accounts is still open.
MergeConflictKind = Literal[
    "ballot_same_vote",
    "delegation_same_meeting",
    "delegation_vote_twice",
    "delegation_chain",
    "attendance_differs",
    "erasure_open",
]


class PrincipalMergeIn(_CamelModel):
    """Body of ``POST /admin/principals/{id}/merge``: the account that stays."""

    target_id: UUID = Field(alias="targetId")


class MergePrincipalOut(_CamelModel):
    """One side of a merge: the old account (source) or the account that stays."""

    id: UUID
    display_name: str | None = Field(serialization_alias="displayName")
    email: str | None
    last_login: str | None = Field(serialization_alias="lastLogin")


class MergeAreaOut(_CamelModel):
    """The counts of one area of a merge."""

    area: MergeArea
    rewritten: int = 0
    combined: int = 0
    removed: int = 0


class MergeConflictOut(_CamelModel):
    """One real conflict. ``label`` names the vote or the meeting, never an id."""

    kind: MergeConflictKind
    label: str | None = None


class MergePermissionOut(_CamelModel):
    """A right of the old account that the target lacks.

    ``key`` is a permission key, or ``admin`` for the admin role (every right).
    ``gremium`` names the gremium of a gremium permission, else null.
    """

    key: str
    gremium: str | None = None


class MergePreviewOut(_CamelModel):
    """``GET /admin/principals/{id}/merge-preview``: what a merge would do."""

    source: MergePrincipalOut
    target: MergePrincipalOut
    areas: list[MergeAreaOut]
    conflicts: list[MergeConflictOut]
    # The rights of the old account that the target lacks. The merge moves no right,
    # but it moves ownership, so these block it unless the admin holds them all.
    extra_permissions: list[MergePermissionOut] = Field(
        default_factory=list, serialization_alias="extraPermissions"
    )
    actor_holds_extra: bool = Field(default=True, serialization_alias="actorHoldsExtra")
    can_merge: bool = Field(serialization_alias="canMerge")


class MergeResultOut(_CamelModel):
    """``POST /admin/principals/{id}/merge``: what the merge did."""

    source: MergePrincipalOut
    target: MergePrincipalOut
    areas: list[MergeAreaOut]
    merged_at: str = Field(serialization_alias="mergedAt")


class PrincipalUpdate(_CamelModel):
    """Body of ``PATCH /admin/principals/{id}``: activate or deactivate a user."""

    active: bool


class GroupMappingOut(_CamelModel):
    """OIDC group → global role. A global role has no gremium scope."""

    id: UUID
    oidc_group: str = Field(serialization_alias="oidcGroup")
    role_id: UUID = Field(serialization_alias="roleId")


class GroupMappingCreate(_OidcGroupField):
    oidc_group: str = Field(alias="oidcGroup", min_length=1, max_length=256)
    role_id: UUID = Field(alias="roleId")


class GroupMappingUpdate(_OidcGroupField):
    oidc_group: str | None = Field(default=None, alias="oidcGroup", min_length=1, max_length=256)
    role_id: UUID | None = Field(default=None, alias="roleId")


class WebhookOut(_CamelModel):
    id: UUID
    name: str
    url: str
    events: list[EventName]
    active: bool


class WebhookCreate(_CamelModel):
    """New webhook. The model ignores an empty ``id`` from the frontend."""

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

    The model exposes no resolved IP or host topology and no response body. It
    holds the status class, the HTTP status code if there is one, and the
    attempt count. An operator can diagnose a mistyped or internal webhook
    without a leak of network details. ``last_state`` is condensed to
    ``pending``, ``sent`` or ``dead``.
    """

    webhook_id: UUID = Field(serialization_alias="webhookId")
    last_state: str = Field(serialization_alias="lastState")
    reason_class: str = Field(serialization_alias="reasonClass")
    response_code: int | None = Field(default=None, serialization_alias="responseCode")
    attempts: int = 0
    last_at: str | None = Field(default=None, serialization_alias="lastAt")


class SiteConfigOut(_CamelModel):
    """Active branding config plus current draft plus change flag."""

    version: int
    active: Branding
    draft: Branding
    has_draft_changes: bool = Field(serialization_alias="hasDraftChanges")


class AttachmentLimitsOut(_CamelModel):
    """Upload limits of the wizard (Z4), for the text below the drop zone.

    ``maxFileBytes`` is the cap of one file. ``maxDraftFiles`` and
    ``maxDraftBytes`` are the caps of all draft files of one draft token. The
    server checks all three on each upload; the values only tell the applicant
    the rules before a file is refused.
    """

    max_file_bytes: int = Field(serialization_alias="maxFileBytes")
    max_draft_files: int = Field(serialization_alias="maxDraftFiles")
    max_draft_bytes: int = Field(serialization_alias="maxDraftBytes")


class PublicSiteConfigOut(_CamelModel):
    """Public (auth-free) active branding config for frontend rendering.

    ``confirmTtlHours`` is the time a guest has to confirm the email. The
    confirmation page of the wizard shows it. ``linkTtlDays`` is the lifetime of a
    new magic link in days; null means that the link does not expire. The
    confirmation page and the status page show it. ``attachmentLimits`` holds the
    upload limits of the wizard.
    """

    version: int
    branding: Branding
    confirm_ttl_hours: int = Field(
        default=DEFAULT_CONFIRM_TTL_HOURS, serialization_alias="confirmTtlHours"
    )
    link_ttl_days: int | None = Field(default=None, serialization_alias="linkTtlDays")
    attachment_limits: AttachmentLimitsOut | None = Field(
        default=None, serialization_alias="attachmentLimits"
    )


# The API caps the link lifetime at ten years. A larger value adds nothing, and a
# far-future expiry can overflow the datetime arithmetic.
MAX_LINK_TTL_DAYS = 3650


class GuestSettingsOut(_CamelModel):
    """Settings for applications without an account (Z1).

    ``linkTtlDays`` null means: a new magic link has no expiry.
    """

    confirm_ttl_hours: int = Field(serialization_alias="confirmTtlHours")
    link_ttl_days: int | None = Field(serialization_alias="linkTtlDays")
    updated_at: datetime | None = Field(default=None, serialization_alias="updatedAt")
    updated_by: str | None = Field(default=None, serialization_alias="updatedBy")


class GuestSettingsUpdate(_CamelModel):
    """Full replacement of the guest settings. Send ``linkTtlDays: null`` for no expiry."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    confirm_ttl_hours: int = Field(
        alias="confirmTtlHours", ge=1, le=MAX_CONFIRM_TTL_HOURS
    )
    link_ttl_days: int | None = Field(alias="linkTtlDays", ge=1, le=MAX_LINK_TTL_DAYS)
