"""Wire-format request models, mirrored from the backend's Pydantic schemas.

Field names are the **camelCase wire keys** (the backend accepts camelCase aliases);
``extra="allow"`` keeps the mirror drift-tolerant — new backend fields can be passed
through without updating this file. Create models are dumped with ``exclude_none``,
patch/update models with ``exclude_unset`` (only the explicitly provided keys go on
the wire, so partial updates stay partial).

Source of truth: ``backend/app/shared/config_schemas.py`` + the per-module
``schemas.py`` files (state 2026-06-12).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WireModel(BaseModel):
    """Base for all request bodies: camelCase field names, unknown keys allowed."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


I18nMap = dict[str, str]


# ============================================================ flow graph (shared)
class StateDef(WireModel):
    key: str = Field(description="State key, ^[a-z][a-z0-9_]*$")
    label: I18nMap = Field(description='Display label per language, e.g. {"de": "...", "en": "..."}')
    color: str | None = None
    editAllowed: bool = True
    isInitial: bool = False
    kind: Literal["normal", "vote"] = "normal"
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Kind-specific config: vote states need {gremiumId}; any state may "
        "set {deadlinePolicyKey} to materialise a deadline on entry.",
    )


class StateDefPatch(WireModel):
    """Partial state update — only provided keys are applied."""

    key: str | None = Field(default=None, description="New key (renames cascade to transitions/layout/groups)")
    label: I18nMap | None = None
    color: str | None = None
    editAllowed: bool | None = None
    isInitial: bool | None = None
    kind: Literal["normal", "vote"] | None = None
    config: dict[str, Any] | None = None


class TransitionDef(WireModel):
    from_: str = Field(alias="from", description="Source state key")
    to: str = Field(description="Target state key")
    label: I18nMap | None = None
    color: str | None = None
    guard: dict[str, Any] | None = Field(
        default=None,
        description="Guard tree. Leaf operators: deadlinePassed, applicantRoleIs, "
        "applicantCommitteeIs, budgetIs, budgetFitsApplication, hasField, "
        "compare {field,op,value}; actor gates (manual only): roleIs, isInCommittee, "
        "actorIsApplicant; combinators: and/or (list), not (single child).",
    )
    actions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Actions: notify {recipients}, webhook {webhookId}, "
        "addToNextSession {gremiumId} (target must be a vote state), assignBudget {budgetId}.",
    )
    order: int | None = None
    automatic: bool = False
    branch: Literal["pass", "fail"] | None = Field(
        default=None, description="Result branch — only on transitions leaving a vote state"
    )
    requiresAction: bool = True


class TransitionDefPatch(WireModel):
    """Partial transition update — only provided keys are applied; an explicit
    ``null`` removes the key (e.g. ``guard: null`` drops the guard)."""

    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    label: I18nMap | None = None
    color: str | None = None
    guard: dict[str, Any] | None = None
    actions: list[dict[str, Any]] | None = None
    order: int | None = None
    automatic: bool | None = None
    branch: Literal["pass", "fail"] | None = None
    requiresAction: bool | None = None


class FlowGroupDef(WireModel):
    """Visual node group (editor-only, stored in ``layout.groups``; the engine
    ignores it). Groups are NESTABLE via ``groupIds``; the editor renders each
    group as one box whose content opens by drill-down."""

    id: str
    name: str
    stateKeys: list[str]
    groupIds: list[str] | None = Field(
        default=None, description="Ids of directly contained sub-groups (nesting)"
    )
    color: str | None = None


# ============================================================ form fields (shared)
class FormFieldDef(WireModel):
    key: str = Field(description="Field key, ^[a-z][a-z0-9_]*$")
    type: str = Field(
        description="text|textarea|number|currency|date|select|multiselect|checkbox|"
        "file|table|markdown|computed|positions|section"
    )
    label: I18nMap
    help: I18nMap | None = None
    required: bool = False
    validation: dict[str, Any] | None = Field(
        default=None,
        description="min/max/minLen/maxLen/pattern/fileTypes/maxSizeMB/maxRows/"
        "minOffers/minPositions",
    )
    options: list[dict[str, Any]] | None = Field(
        default=None, description="[{value, label:{de,en}}] — required for select/multiselect"
    )
    visibleIf: dict[str, Any] | None = Field(default=None, description="JsonLogic visibility rule")
    compute: dict[str, Any] | None = Field(default=None, description="Required for type 'computed'")
    isPromoted: bool = False
    promoteTarget: str | None = None


class FormFieldPatch(WireModel):
    """Partial form-field update — only provided keys are applied."""

    key: str | None = None
    type: str | None = None
    label: I18nMap | None = None
    help: I18nMap | None = None
    required: bool | None = None
    validation: dict[str, Any] | None = None
    options: list[dict[str, Any]] | None = None
    visibleIf: dict[str, Any] | None = None
    compute: dict[str, Any] | None = None
    isPromoted: bool | None = None
    promoteTarget: str | None = None


# ============================================================ admin: gremien/RBAC
class GremiumCreate(WireModel):
    name: str
    slug: str
    cdVariant: str = "stupa"
    defaultLang: str = "de"
    allowVoteDelegation: bool = False
    delegationLeadMinutes: int = 0
    delegationAllowExternal: bool = False
    quorumPercent: int | None = Field(default=None, ge=0, le=100)


class GremiumUpdate(WireModel):
    name: str | None = None
    slug: str | None = None
    cdVariant: str | None = None
    defaultLang: str | None = None
    allowVoteDelegation: bool | None = None
    delegationLeadMinutes: int | None = None
    delegationAllowExternal: bool | None = None
    quorumPercent: int | None = None


class GremiumRoleCreate(WireModel):
    key: str
    name: I18nMap = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)


class GremiumRoleUpdate(WireModel):
    name: I18nMap | None = None
    permissions: list[str] | None = None


class GremiumMembershipCreate(WireModel):
    principalId: str
    gremiumRoleId: str
    validFrom: str | None = None
    validUntil: str | None = None


class RoleCreate(WireModel):
    key: str
    label: I18nMap = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(WireModel):
    label: I18nMap | None = None
    permissions: list[str] | None = None


class RoleAssignmentCreate(WireModel):
    principalId: str
    roleId: str
    gremiumId: str | None = None
    validFrom: str | None = None
    validUntil: str | None = None
    delegateVoting: bool = False


class RoleAssignmentUpdate(WireModel):
    roleId: str | None = None
    gremiumId: str | None = None
    validFrom: str | None = None
    validUntil: str | None = None
    delegateVoting: bool | None = None


class GroupMappingCreate(WireModel):
    oidcGroup: str
    roleId: str
    gremiumId: str | None = None


class GroupMappingUpdate(WireModel):
    oidcGroup: str | None = None
    roleId: str | None = None
    gremiumId: str | None = None


# ============================================================ admin: types/webhooks
class ApplicationTypeCreate(WireModel):
    key: str
    nameI18n: I18nMap
    gremiumId: str | None = None
    hasBudget: bool = False
    comparisonOffers: dict[str, Any] | None = None


class ApplicationTypeUpdate(WireModel):
    nameI18n: I18nMap | None = None
    gremiumId: str | None = None
    hasBudget: bool | None = None
    comparisonOffers: dict[str, Any] | None = None


class WebhookCreate(WireModel):
    name: str
    url: str
    events: list[str] = Field(default_factory=list)
    active: bool = True


class WebhookUpdate(WireModel):
    name: str | None = None
    url: str | None = None
    events: list[str] | None = None
    active: bool | None = None


class DeadlinePolicyCreate(WireModel):
    key: str
    label: I18nMap
    kind: Literal["absolute", "relative_submitted", "relative_changed"]
    absoluteAt: str | None = Field(default=None, description="ISO datetime — for kind 'absolute'")
    offsetDays: int | None = Field(default=None, description="For the relative kinds")


class DeadlinePolicyUpdate(WireModel):
    label: I18nMap | None = None
    kind: Literal["absolute", "relative_submitted", "relative_changed"] | None = None
    absoluteAt: str | None = None
    offsetDays: int | None = None


# ============================================================ budget tree
class BudgetNodeCreate(WireModel):
    key: str
    name: str
    parentId: str | None = None
    gremiumId: str | None = Field(default=None, description="Top-level nodes only")
    currency: str = "EUR"
    active: bool = True
    color: str | None = None
    fiscalStartMonth: int = 1
    fiscalStartDay: int = 1


class BudgetNodeUpdate(WireModel):
    key: str | None = None
    name: str | None = None
    active: bool | None = None
    color: str | None = None
    acceptedStateKeys: list[str] | None = None
    deniedStateKeys: list[str] | None = None
    fullyBound: bool | None = None
    fiscalStartMonth: int | None = None
    fiscalStartDay: int | None = None


class ExpenseUpdate(WireModel):
    amount: str | None = Field(default=None, description="Decimal string > 0")
    description: str | None = None


class TransferCreate(WireModel):
    fromBudgetId: str
    toBudgetId: str
    fiscalYearId: str
    amount: str = Field(description="Decimal string > 0")
    description: str


class AccountCreate(WireModel):
    name: str
    iban: str = ""
    active: bool = True


class AccountUpdate(WireModel):
    name: str | None = None
    iban: str | None = None
    active: bool | None = None


# ============================================================ meetings/votes
class MeetingCreate(WireModel):
    gremiumId: str
    title: str
    date: str | None = Field(default=None, description="ISO date")
    startTime: str | None = Field(default=None, description="HH:MM")
    protokollantId: str | None = None


class MeetingPatch(WireModel):
    activeApplicationId: str | None = None
    status: Literal["planned", "live", "closed"] | None = None
    date: str | None = None
    startTime: str | None = None
    protokollantId: str | None = None


class MeetingVoteOpenBody(WireModel):
    agendaItemId: str
    question: str | None = None
    options: list[str] = Field(default_factory=lambda: ["yes", "no", "abstain"])
    majorityRule: Literal["simple", "absolute", "two_thirds"] = "simple"
    secret: bool = False
    eligibleCount: int | None = None
    quorumPercent: int | None = None


class VoteCreate(WireModel):
    """Application-bound vote (voting module)."""

    config: dict[str, Any] = Field(description="Vote config (options/majority/secret …)")
    eligibleGroup: str
    question: str | None = None
    eligibleCount: int | None = None
    opensStateId: str | None = None
    closesAt: str | None = Field(default=None, description="ISO datetime")
    resultBranchTransitionId: str | None = None


# ============================================================ misc
class NotificationSettingsUpdate(WireModel):
    taskReminderEnabled: bool | None = None
    taskReminderAfterDays: int | None = None
    taskReminderRepeatDays: int | None = None


class DelegationCreate(WireModel):
    meetingId: str
    delegateId: str
    delegateVoting: bool = False


class SubstituteCreate(WireModel):
    gremiumId: str
    memberId: str | None = Field(default=None, description="None = pool substitute for any member")
    substituteId: str


def dump_create(model: BaseModel) -> dict[str, Any]:
    """Create bodies: omit unset Nones, keep defaults, use wire aliases."""
    return model.model_dump(by_alias=True, exclude_none=True)


def dump_patch(model: BaseModel) -> dict[str, Any]:
    """Patch bodies: only the explicitly provided keys (partial update)."""
    return model.model_dump(by_alias=True, exclude_unset=True)
