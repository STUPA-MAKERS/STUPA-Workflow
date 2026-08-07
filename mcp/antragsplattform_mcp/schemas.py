"""Wire-format request models, mirrored from the Pydantic schemas of the backend.

The field names are the **camelCase wire keys**. The backend accepts camelCase aliases.
`extra="allow"` keeps the mirror tolerant against drift. A caller can pass a new backend
field through without an update to this file. A create model dumps with `exclude_none`.
A patch or update model dumps with `exclude_unset`. Only the keys that the caller sets
go on the wire, so a partial update stays partial.

Source of truth: `backend/app/shared/config_schemas.py` plus the per-module `schemas.py`
files (state 2026-06-12).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WireModel(BaseModel):
    """Base for all request bodies: camelCase field names, unknown keys allowed."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


I18nMap = dict[str, str]


# Flow graph, shared by the flow tools.
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
    """Partial state update. Only the keys you provide change."""

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
        "applicantCommitteeIs, applicationTypeIs (application type key, e.g. 'qsm'/'vsm'), "
        "attachmentPresent (bool — >=1 attachment), budgetIs, budgetFitsApplication, "
        "hasField, compare {field,op,value}; actor gates (manual only): roleIs, "
        "isInCommittee, actorIsApplicant; combinators: and/or (list), not (single child).",
    )
    actions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Actions: notify {recipients}, webhook {webhookId}, "
        "addToNextSession {gremiumId} (target must be a vote state), assignBudget {budgetId}, "
        "assignBudgetFromField {field} (assigns the budget UUID stored in that form field).",
    )
    order: int | None = None
    automatic: bool = False
    branch: Literal["pass", "fail"] | None = Field(
        default=None, description="Result branch — only on transitions leaving a vote state"
    )
    requiresAction: bool = True


class TransitionDefPatch(WireModel):
    """Partial transition update.

    Only the keys you provide change. An explicit `null` removes the key. For example,
    `guard: null` drops the guard.
    """

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
    """Visual node group for the editor only.

    The graph keeps it in `layout.groups` and the engine ignores it. Groups are NESTABLE
    through `groupIds`. The editor draws each group as one box. The content of the box
    opens by drill-down.
    """

    id: str
    name: str
    stateKeys: list[str]
    groupIds: list[str] | None = Field(
        default=None, description="Ids of directly contained sub-groups (nesting)"
    )
    color: str | None = None


# Form fields, shared by the form tools.
class FormFieldDef(WireModel):
    key: str = Field(description="Field key, ^[a-z][a-z0-9_]*$")
    type: str = Field(
        description="text|textarea|number|currency|date|select|multiselect|gremium_select|"
        "budget_select|email|iban|daterange|checkbox|file|table|markdown|computed|positions|"
        "section. gremium_select/budget_select options are injected by the server "
        "(value=UUID); daterange value is {from,to} ISO dates."
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
    """Partial form-field update. Only the keys you provide change."""

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


# Admin: Gremien and RBAC.
class GremiumCreate(WireModel):
    name: str
    slug: str
    # Ids come from `list_cd_variants`.
    cdVariantId: str | None = None
    defaultLang: str = "de"
    allowVoteDelegation: bool = False
    delegationLeadMinutes: int = 0
    delegationAllowExternal: bool = False
    quorumPercent: int | None = Field(default=None, ge=0, le=100)


class GremiumUpdate(WireModel):
    name: str | None = None
    slug: str | None = None
    cdVariantId: str | None = None
    defaultLang: str | None = None
    allowVoteDelegation: bool | None = None
    delegationLeadMinutes: int | None = None
    delegationAllowExternal: bool | None = None
    quorumPercent: int | None = None


CdBaseVariant = Literal["report", "protocol"]
CdLogoSlot = Literal["title", "footer"]
VendoredLogoName = Literal[
    "HSRT",
    "INF",
    "ASTA",
    "STUPA",
    "ECHO",
    "MAKERS",
    "MAKERS-RAlign",
    "MAKERS-Icon",
    "Skyline",
]


class CdVariantCreate(WireModel):
    key: str
    name: str
    baseVariant: CdBaseVariant = "report"


class CdVariantUpdate(WireModel):
    """Patch of a CD variant. `key` and `baseVariant` are create-only."""

    name: str | None = None


class CdVariantLogoVendoredCreate(WireModel):
    """Add a logo that pytex ships. Upload a file through the web UI instead."""

    slot: CdLogoSlot
    vendoredName: VendoredLogoName


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


# Admin: application types, webhooks and deadline policies.
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


# Budget tree, bookings and transfers.
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
    hiddenInBudget: bool | None = Field(
        default=None,
        description="Hide this node (incl. subtree) in the budget tab — display only, "
        "rollups/export unchanged",
    )
    viewGremiumId: str | None = Field(
        default=None,
        description="Committee whose members see this node (incl. subtree) as a "
        "budget-tab root without global budget permissions; null clears",
    )
    fiscalStartMonth: int | None = None
    fiscalStartDay: int | None = None


class ExpenseUpdate(WireModel):
    amount: str | None = Field(default=None, description="Decimal string > 0")
    description: str | None = None
    budgetId: str | None = Field(default=None, description="Move the booking to another cost centre")
    invoiceDate: str | None = Field(default=None, description="ISO date; null clears")
    paymentDate: str | None = Field(default=None, description="ISO date; null clears")
    correspondent: str | None = None
    note: str | None = None
    referenceNumber: str | None = None
    paymentMethod: Literal["ueberweisung", "bar", "lastschrift", "karte", "paypal"] | None = None
    category: str | None = None
    invoiceId: str | None = Field(default=None, description="Linked invoice; null clears")


class TransferCreate(WireModel):
    fromBudgetId: str
    toBudgetId: str
    fiscalYearId: str
    amount: str = Field(description="Decimal string > 0")
    description: str


class InvoiceCreate(WireModel):
    """Create an invoice (#invoices).

    `grossAmount` is required and the rest is optional. `fileToken` links an original PDF
    that you uploaded or parsed before, with `parse_invoice` or `upload_invoice_file`.
    """

    grossAmount: str = Field(description="Decimal string >= 0")
    number: str | None = None
    issueDate: str | None = Field(default=None, description="ISO date")
    dueDate: str | None = Field(default=None, description="ISO date")
    supplier: str | None = None
    netAmount: str | None = None
    taxAmount: str | None = None
    note: str | None = None
    status: Literal["open", "paid"] = "open"
    fileToken: str | None = None
    fileName: str | None = None
    fileMime: str | None = None


class InvoiceUpdate(WireModel):
    number: str | None = None
    issueDate: str | None = None
    dueDate: str | None = None
    supplier: str | None = None
    netAmount: str | None = None
    taxAmount: str | None = None
    grossAmount: str | None = None
    note: str | None = None
    status: Literal["open", "paid"] | None = None


# Meetings and votes.
class MeetingCreate(WireModel):
    gremiumId: str
    title: str
    date: str = Field(description="ISO date")
    startTime: str = Field(description="HH:MM")
    endTime: str | None = Field(
        default=None, description="HH:MM, after startTime. The ICS feed else assumes one hour."
    )
    protokollantId: str | None = None


class MeetingPatch(WireModel):
    activeApplicationId: str | None = None
    status: Literal["planned", "live", "closed"] | None = None
    date: str | None = None
    startTime: str | None = None
    endTime: str | None = None
    protokollantId: str | None = None


class MeetingVoteOpenBody(WireModel):
    agendaItemId: str
    question: str | None = None
    options: list[str] = Field(default_factory=lambda: ["yes", "no", "abstain"])
    majorityRule: Literal["simple", "absolute", "two_thirds"] = "simple"
    secret: bool = False
    # The server derives the quorum denominator from the roster; a client value is ignored.
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


# Notification settings, delegations and substitutes.
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
    """Dump a create body: drop None values, keep defaults, use the wire aliases."""
    return model.model_dump(by_alias=True, exclude_none=True)


def dump_patch(model: BaseModel) -> dict[str, Any]:
    """Dump a patch body with only the keys that the caller set, for a partial update."""
    return model.model_dump(by_alias=True, exclude_unset=True)
