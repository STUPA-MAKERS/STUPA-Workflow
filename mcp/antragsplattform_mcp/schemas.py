"""Wire-format request models, mirrored from the Pydantic schemas of the backend.

The field names are the **camelCase wire keys**. The backend accepts camelCase aliases.
`extra="allow"` keeps the mirror tolerant against drift. A caller can pass a new backend
field through without an update to this file. A create model dumps with `exclude_none`.
A patch or update model dumps with `exclude_unset`. Only the keys that the caller sets
go on the wire, so a partial update stays partial.

Source of truth: `backend/app/shared/config_schemas.py` plus the per-module `schemas.py`
files (state 2026-10-07).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel, frozen=True):
    """An immutable Pydantic model.

    The package does not import the backend, so it keeps its own frozen base. A subclass
    repeats `frozen=True`, because basedpyright requires it.
    """


class WireModel(FrozenModel, frozen=True):
    """Base for all request bodies: camelCase field names, unknown keys allowed."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


I18nMap = dict[str, str]

# Allowed values of `config.gremiumSource` on a vote state. `budget` takes the deciding
# Gremium from the cost center of the application when it enters the state.
VOTE_GREMIUM_SOURCES: frozenset[str] = frozenset({"budget"})


def check_vote_config(config: dict[str, Any]) -> None:
    """Check the Gremium keys of a vote-state config, as the backend save gate does.

    A vote state takes EXACTLY ONE of `gremiumId` (a fixed Gremium) or
    `gremiumSource: "budget"` (the deciding Gremium of the cost center).

    Raises:
        ValueError: Both keys, neither key, or an unknown `gremiumSource` value.
    """
    gremium_id = config.get("gremiumId")
    source = config.get("gremiumSource")
    if source is not None and source not in VOTE_GREMIUM_SOURCES:
        raise ValueError(f"unknown gremiumSource {source!r}; allowed: 'budget'")
    has_id = isinstance(gremium_id, str) and bool(gremium_id)
    if has_id == (source is not None):
        raise ValueError(
            "a vote state needs exactly one of config.gremiumId or "
            "config.gremiumSource='budget'"
        )



# Flow graph, shared by the flow tools.
class StateDef(WireModel, frozen=True):
    key: str = Field(description="State key, ^[a-z][a-z0-9_]*$")
    label: I18nMap = Field(
        description='Display label per language, e.g. {"de": "...", "en": "..."}'
    )
    color: str | None = None
    editAllowed: bool = True
    isInitial: bool = False
    kind: Literal["normal", "vote"] = "normal"
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Kind-specific config. A vote state needs EXACTLY ONE of "
        "{gremiumId: '<uuid>'} (fixed Gremium) or {gremiumSource: 'budget'} (the "
        "deciding Gremium of the cost center, taken when the application enters the "
        "state; the transition is refused with 409 no_vote_gremium when the cost center "
        "has none).",
    )

    @model_validator(mode="after")
    def _vote_gremium(self) -> StateDef:
        if self.kind == "vote":
            check_vote_config(self.config)
        return self


class StateDefPatch(WireModel, frozen=True):
    """Partial state update. Only the keys you provide change."""

    key: str | None = Field(
        default=None, description="New key (renames cascade to transitions/layout/groups)"
    )
    label: I18nMap | None = None
    color: str | None = None
    editAllowed: bool | None = None
    isInitial: bool | None = None
    kind: Literal["normal", "vote"] | None = None
    config: dict[str, Any] | None = Field(
        default=None,
        description="Replaces the whole config. For a vote state: exactly one of "
        "{gremiumId} or {gremiumSource: 'budget'}.",
    )

    @model_validator(mode="after")
    def _gremium_source(self) -> StateDefPatch:
        source = (self.config or {}).get("gremiumSource")
        if source is not None and source not in VOTE_GREMIUM_SOURCES:
            raise ValueError(f"unknown gremiumSource {source!r}; allowed: 'budget'")
        return self


class TransitionDef(WireModel, frozen=True):
    from_: str = Field(alias="from", description="Source state key")
    to: str = Field(description="Target state key")
    label: I18nMap | None = None
    color: str | None = None
    guard: dict[str, Any] | None = Field(
        default=None,
        description="Guard tree. Leaf operators: applicantRoleIs, "
        "applicantCommitteeIs, applicationTypeIs (application type key, e.g. 'qsm'/'vsm'), "
        "attachmentPresent (bool — >=1 attachment), budgetIs, budgetFitsApplication, "
        "budgetHasDecisionGremium (bool — the cost center has an own or inherited "
        "deciding Gremium), hasField, compare {field,op,value}; actor gates (manual "
        "only): roleIs, isInCommittee, actorIsApplicant, isInVoteGremium (bool — the "
        "actor is a member of the Gremium that decides the current vote); combinators: "
        "and/or (list), not (single child).",
    )
    actions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Actions: notify {recipients: [{kind, ref?}]} with kinds gremium/role/"
        "email (need ref), applicant, voteGremium (members of the Gremium that decides "
        "the vote) and budgetGremium (members of the deciding Gremium of the cost "
        "center) — the last three without ref; "
        "addToNextSession {gremiumId?} (target must be a vote state; without gremiumId "
        "the Gremium of the vote is used); assignBudget {budgetId}; "
        "assignBudgetFromField {field} (assigns the budget UUID stored in that form "
        "field); assignBudgetFromApplicantGremium {parentId?} (assigns the single node, "
        "in the subtree of parentId, whose OWN decisionGremiumId is a Gremium of the "
        "applicant; 0 or several matches assign nothing); assignBudgetFromMap {field, "
        "map: {fieldValue: budgetId}} (assigns the node mapped to the field value). "
        "The assignBudget* actions are refused on a transition INTO a vote state with "
        "gremiumSource 'budget'.",
    )
    order: int | None = None
    automatic: bool = False
    branch: Literal["pass", "fail"] | None = Field(
        default=None, description="Result branch — only on transitions leaving a vote state"
    )
    requiresAction: bool = True


class TransitionDefPatch(WireModel, frozen=True):
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


class FlowGroupDef(WireModel, frozen=True):
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
class FormFieldDef(WireModel, frozen=True):
    key: str = Field(description="Field key, ^[a-z][a-z0-9_]*$")
    type: str = Field(
        description="text|textarea|number|currency|date|select|multiselect|gremium_select|"
        "budget_select|email|iban|daterange|checkbox|file|table|markdown|computed|positions|"
        "funding|section. gremium_select/budget_select options are injected by the server "
        "(value=UUID); daterange value is {from,to} ISO dates. funding is the requested "
        "funding in euro: at most one per form, needs a positions field, value <= the cost "
        "total; when filled in it is the amount instead of the cost total."
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
    format: Literal["number", "money", "percent"] | None = Field(
        default=None, description="Display format of a 'computed' field"
    )


class FormFieldPatch(WireModel, frozen=True):
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
    format: Literal["number", "money", "percent"] | None = None


# Admin: Gremien and RBAC.
class GremiumCreate(WireModel, frozen=True):
    name: str
    slug: str
    # The corporate design is a row now, not a name. `list_cd_variants`
    # returns the ids.
    cdVariantId: str | None = None
    defaultLang: str = "de"
    allowVoteDelegation: bool = False
    delegationLeadMinutes: int = 0
    delegationAllowExternal: bool = False
    delegationMaxPerDelegate: int = Field(default=2, ge=1, le=20)
    delegationInElections: bool = False
    quorumPercent: int | None = Field(default=None, ge=0, le=100)
    termStartMonth: int | None = Field(
        default=None,
        ge=1,
        le=12,
        description="The month in which a term (Amtszeit) starts. Without it the setting counts.",
    )
    repeatQuorumPercent: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="The quorum of a Wiederholungssitzung. Without it the normal quorum counts.",
    )
    guestsMayVote: bool = Field(
        default=False,
        description="Guests of a public meeting can get a ballot. Counts only without a quorum.",
    )
    protocolsPublic: bool = Field(
        default=False,
        description=(
            "Show the final protocols of this Gremium without login on the public "
            "protocols page (public version only)."
        ),
    )
    protocolSignatures: list[str] = Field(
        default_factory=list[str],
        description="The signature lines that end the protocol PDF, in order",
    )


class GremiumUpdate(WireModel, frozen=True):
    name: str | None = None
    slug: str | None = None
    cdVariantId: str | None = None
    defaultLang: str | None = None
    allowVoteDelegation: bool | None = None
    delegationLeadMinutes: int | None = None
    delegationAllowExternal: bool | None = None
    delegationMaxPerDelegate: int | None = Field(default=None, ge=1, le=20)
    delegationInElections: bool | None = None
    quorumPercent: int | None = None
    termStartMonth: int | None = Field(default=None, ge=1, le=12)
    repeatQuorumPercent: int | None = None
    guestsMayVote: bool | None = None
    protocolsPublic: bool | None = Field(
        default=None,
        description=(
            "Switch the public protocols page for this Gremium. Switching it on "
            "publishes ALL final protocols that are not held back; a job builds the "
            "missing public versions first."
        ),
    )
    protocolSignatures: list[str] | None = Field(
        default=None,
        description="Replaces the signature lines that end the protocol PDF, in order",
    )


class CdVariantCreate(WireModel, frozen=True):
    key: str
    name: str


class CdVariantUpdate(WireModel, frozen=True):
    """Patch of a CD variant. `key` is immutable — a different value gives 409."""

    name: str | None = None


class CdVariantLogoVendoredCreate(WireModel, frozen=True):
    """Add a logo that the render service ships. Deprecated: upload a file through the web UI.

    The worker turns a vendored logo into a normal upload at its next start.
    """

    slot: Literal["title", "footer"] = Field(
        description=(
            "title or footer. The slot square (the 1:1 logo of a Gremium in the app) "
            "takes a PNG, JPEG or WebP upload only."
        )
    )
    vendoredName: str


class GremiumRoleCreate(WireModel, frozen=True):
    key: str
    name: I18nMap = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)


class GremiumRoleUpdate(WireModel, frozen=True):
    name: I18nMap | None = None
    permissions: list[str] | None = None


class GremiumMembershipMappingCreate(WireModel, frozen=True):
    oidcGroup: str = Field(description="OIDC group name. The prefix 'vote:' is reserved.")
    gremiumId: str = Field(description="The Gremium that the group gives membership in")


class GremiumMembershipMappingUpdate(WireModel, frozen=True):
    """Partial update. Send at least one key."""

    oidcGroup: str | None = None
    gremiumId: str | None = None


class GremiumRoleMappingCreate(WireModel, frozen=True):
    oidcGroup: str = Field(description="OIDC group name. The prefix 'vote:' is reserved.")
    gremiumRoleId: str = Field(
        description="A Gremium role. It applies only to members of its Gremium."
    )


class GremiumRoleMappingUpdate(WireModel, frozen=True):
    """Partial update. Send at least one key."""

    oidcGroup: str | None = None
    gremiumRoleId: str | None = None


class RoleCreate(WireModel, frozen=True):
    key: str
    label: I18nMap = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(WireModel, frozen=True):
    label: I18nMap | None = None
    permissions: list[str] | None = None


class GroupMappingCreate(WireModel, frozen=True):
    """OIDC group to a global role. A global role has no Gremium scope."""

    oidcGroup: str
    roleId: str


class GroupMappingUpdate(WireModel, frozen=True):
    oidcGroup: str | None = None
    roleId: str | None = None


# Admin: application types and webhooks.
class ApplicationTypeCreate(WireModel, frozen=True):
    key: str
    nameI18n: I18nMap
    gremiumId: str | None = None
    hasBudget: bool = False
    pdfSignatures: bool = False
    signatureRows: list[dict[str, str]] = Field(
        default_factory=list[dict[str, str]],
        description="The signature rows of the Antrag PDF: [{label, signer}], in order",
    )
    attachmentRequired: bool = Field(
        default=False, description="The Antrag needs a file before the submit"
    )
    comparisonOffers: dict[str, Any] | None = None
    groupId: str | None = Field(
        default=None, description="The group of Antragsarten in step 1 of the apply wizard"
    )


class ApplicationTypeUpdate(WireModel, frozen=True):
    nameI18n: I18nMap | None = None
    gremiumId: str | None = None
    hasBudget: bool | None = None
    pdfSignatures: bool | None = None
    signatureRows: list[dict[str, str]] | None = Field(
        default=None,
        description="Replaces the signature rows of the Antrag PDF: [{label, signer}]",
    )
    attachmentRequired: bool | None = Field(
        default=None, description="The Antrag needs a file before the submit"
    )
    comparisonOffers: dict[str, Any] | None = None
    groupId: str | None = Field(
        default=None, description="The group of Antragsarten in step 1 of the apply wizard"
    )


class ApplicationTypeGroupCreate(WireModel, frozen=True):
    nameI18n: I18nMap = Field(description="The name by language; German is required")
    textI18n: I18nMap | None = Field(default=None, description="The text under the name")


class ApplicationTypeGroupUpdate(WireModel, frozen=True):
    nameI18n: I18nMap | None = None
    textI18n: I18nMap | None = None


class GremiumInfoLink(WireModel, frozen=True):
    label: str = Field(description="1 to 80 characters")
    url: str = Field(description="An http(s) or mailto address")


class AppointmentIn(WireModel, frozen=True):
    """A Termin of the Kalender with its invitations."""

    title: str = Field(description="1 to 200 characters")
    startsOn: str = Field(description="ISO date YYYY-MM-DD")
    endsOn: str = Field(description="ISO date YYYY-MM-DD, not before startsOn")
    startTime: str | None = Field(default=None, description="HH:MM; none for a whole day")
    endTime: str | None = Field(default=None, description="HH:MM")
    place: str | None = Field(default=None, description="Up to 200 characters")
    description: str | None = Field(default=None, description="Up to 5000 characters")
    forAll: bool = Field(default=False, description="Invite every account")
    public: bool = Field(default=False, description="Show the Termin on the public calendar")
    gremiumIds: list[str] = Field(default_factory=list, description="Invited Gremien")
    principalIds: list[str] = Field(default_factory=list, description="Invited persons")


class ExternalCalendarIn(WireModel, frozen=True):
    name: str = Field(description="1 to 120 characters")
    url: str = Field(description="The http(s) address of the ICS feed")
    gremiumId: str | None = Field(default=None, description="The Gremium that reads it; none: all")
    intervalMinutes: Literal[15, 60, 360, 1440] = 60


class PollOptionIn(WireModel, frozen=True):
    label: str | None = Field(default=None, description="The text of a text option")
    start: str | None = Field(default=None, description="ISO date-time of a date option")
    end: str | None = Field(default=None, description="ISO date-time, optional end")


class GremiumVoteCreate(WireModel, frozen=True):
    """A poll (Umfrage) or an Umlaufverfahren of a Gremium, without a meeting."""

    kind: Literal["poll", "circular"] = "poll"
    eligibleGroup: str = Field(description="The Gremium")
    question: str = Field(description="1 to 2000 characters")
    closesAt: str = Field(
        description="ISO date-time of the end; a poll at least one hour ahead, an "
        "Umlaufverfahren at least `minDays` of `get_circular_vote_rules` days ahead"
    )
    draft: bool = Field(default=False, description="Keep it a draft; else it opens at once")
    mode: Literal["single", "multi", "date"] | None = Field(
        default=None, description="Poll only: one choice, several choices or a date poll"
    )
    options: list[PollOptionIn] | None = Field(
        default=None, description="Poll only: 2 to 20 options"
    )
    maxChoices: int | None = Field(default=None, description="Poll only, mode `multi`")


class PollPatch(WireModel, frozen=True):
    question: str | None = None
    options: list[PollOptionIn] | None = None
    maxChoices: int | None = None
    closesAt: str | None = None


class UiLanguageCreate(WireModel, frozen=True):
    """An extra UI language. `code` is a BCP 47 tag such as `fr` or `pt-BR`."""

    code: str
    name: str
    active: bool = False


class UiLanguageUpdate(WireModel, frozen=True):
    """A change of the name or of the switch `active`. An absent field stays."""

    name: str | None = None
    active: bool | None = None


class WebhookSubscription(WireModel, frozen=True):
    event: str = Field(description="An event of get_webhook_catalog, e.g. application.transition")
    fields: list[str] = Field(
        default_factory=list,
        description="The fields of the event for the data object; the IDs are always sent",
    )


class WebhookCreate(WireModel, frozen=True):
    name: str
    url: str
    active: bool = True
    subscriptions: list[WebhookSubscription] = Field(default_factory=list)
    gremiumIds: list[str] = Field(default_factory=list, description="Empty = every Gremium")
    typeIds: list[str] = Field(default_factory=list, description="Empty = every Antragsart")
    stateKeys: list[str] = Field(
        default_factory=list,
        description="Target status keys for application.transition; empty = every status",
    )


class WebhookUpdate(WireModel, frozen=True):
    name: str | None = None
    url: str | None = None
    active: bool | None = None
    subscriptions: list[WebhookSubscription] | None = None
    gremiumIds: list[str] | None = None
    typeIds: list[str] | None = None
    stateKeys: list[str] | None = None


# Budget tree, bookings and transfers.
class BudgetNodeCreate(WireModel, frozen=True):
    key: str
    name: str
    parentId: str | None = None
    gremiumId: str | None = Field(default=None, description="Top-level nodes only")
    currency: str = "EUR"
    active: bool = True
    color: str | None = None
    fiscalStartMonth: int = 1
    fiscalStartDay: int = 1
    decisionGremiumId: str | None = Field(
        default=None,
        description="Gremium that decides on spending from this node (and from its "
        "subtree unless a descendant sets its own)",
    )


class PlanLineSet(WireModel, frozen=True):
    side: Literal["income", "expense"] | None = Field(
        default=None,
        description="The side of a Titel, a direct child of the top-level node. A "
        "cost center further down takes the side of its Titel.",
    )
    amount: str | None = Field(
        default=None,
        description="The Ansatz as a decimal string. Ignored for a cost center with a "
        "child line: it holds the sum of its children.",
    )
    note: str | None = Field(default=None, description="The Erläuterung")
    transferable: bool | None = Field(default=None, description="Vermerk übertragbar")
    coverable: bool | None = Field(default=None, description="Vermerk deckungsfähig")
    blocked: str | None = Field(
        default=None, description="The gesperrt amount as a decimal string, at most the Ansatz"
    )


class PlanLineRename(WireModel, frozen=True):
    name: str | None = Field(default=None, description="The new name of the cost center")
    key: str | None = Field(
        default=None, description="The new key, the last segment of the path key"
    )


class PlanStep(WireModel, frozen=True):
    name: str
    gremiumId: str | None = Field(
        default=None, description="The Gremium that decides this step by a vote"
    )


class PlanNodeCreate(WireModel, frozen=True):
    parentId: str
    key: str
    name: str
    side: Literal["income", "expense"] | None = Field(
        default=None, description="The side of a Titel, a direct child of the top-level node"
    )
    amount: str = "0"


class BudgetNodeUpdate(WireModel, frozen=True):
    key: str | None = None
    name: str | None = None
    active: bool | None = None
    color: str | None = None
    viewGremiumId: str | None = Field(
        default=None,
        description="Committee whose members see this node (incl. subtree) as a "
        "budget-tab root without global budget permissions; null clears",
    )
    fiscalStartMonth: int | None = None
    fiscalStartDay: int | None = None
    #: Top level only: a plan line starts deckungsfähig when it becomes an expense line.
    planCoverableDefault: bool | None = None
    decisionGremiumId: str | None = Field(
        default=None,
        description="Deciding Gremium of this node. A descendant without an own value "
        "inherits it. A vote state with gremiumSource 'budget' takes it. null clears "
        "(the node then inherits from its ancestors again)",
    )


class ExpenseUpdate(WireModel, frozen=True):
    amount: str | None = Field(default=None, description="Decimal string > 0")
    description: str | None = None
    budgetId: str | None = Field(
        default=None, description="Move the booking to another cost centre"
    )
    invoiceDate: str | None = Field(default=None, description="ISO date; null clears")
    paymentDate: str | None = Field(default=None, description="ISO date; null clears")
    correspondent: str | None = None
    note: str | None = None
    referenceNumber: str | None = None
    paymentMethod: Literal["ueberweisung", "bar", "lastschrift", "karte", "paypal"] | None = None
    category: str | None = None
    invoiceId: str | None = Field(default=None, description="Linked invoice; null clears")


class TransferCreate(WireModel, frozen=True):
    fromBudgetId: str
    toBudgetId: str
    fiscalYearId: str
    amount: str = Field(description="Decimal string > 0")
    description: str
    paymentDate: str | None = Field(
        default=None, description="ISO date; a past fiscal year needs one inside the year"
    )


class InvoiceCreate(WireModel, frozen=True):
    """Create an invoice.

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


class InvoiceUpdate(WireModel, frozen=True):
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
class MeetingCreate(WireModel, frozen=True):
    gremiumId: str
    title: str
    date: str | None = Field(default=None, description="ISO date")
    startTime: str | None = Field(default=None, description="HH:MM")
    endTime: str | None = Field(
        default=None,
        description="HH:MM, the planned end, after `startTime`; the time plan of the agenda "
        "and the calendar use it",
    )
    protokollantId: str | None = None
    publicJoin: bool | None = Field(
        default=None,
        description="Public participation with a QR code: persons without an account ask "
        "to join, the meeting lead admits them.",
    )
    guestsMode: Literal["vote", "watch"] | None = Field(
        default=None,
        description="Admitted guests vote (`vote`) or only follow (`watch`). `vote` needs a "
        "Gremium that lets guests vote and has no quorum (422 `guests_vote_off`, "
        "`guests_vote_needs_no_quorum`).",
    )
    kind: Literal["ordinary", "extraordinary", "repeat", "constituent"] | None = Field(
        default=None,
        description="The kind of the meeting. A new meeting is `ordinary`.",
    )
    repeatOfId: str | None = Field(
        default=None,
        description="The first meeting of a `repeat` meeting: an earlier meeting of the same "
        "Gremium. A `repeat` meeting needs it (422 `repeat_needs_first_meeting`, "
        "`repeat_first_meeting_invalid`).",
    )
    location: str | None = Field(default=None, description="The place, at most 200 characters.")
    form: Literal["presence", "hybrid", "video"] | None = Field(
        default=None, description="The form of the meeting. A new meeting is `presence`."
    )


class MeetingPatch(WireModel, frozen=True):
    activeApplicationId: str | None = None
    status: Literal["planned", "live", "closed"] | None = None
    title: str | None = Field(
        default=None,
        description="New title, 1 to 200 characters. A closed meeting keeps its title (409).",
    )
    date: str | None = None
    startTime: str | None = None
    endTime: str | None = Field(
        default=None,
        description="HH:MM, the planned end, after `startTime`; the time plan of the agenda "
        "and the calendar use it",
    )
    currentAgendaItemId: str | None = Field(
        default=None,
        description="Live meeting: the agenda item that the room is on now (the lead or the "
        "protokollant)",
    )
    completeAgendaItemId: str | None = Field(
        default=None,
        description="The item that the room leaves (\"Nächster TOP\"): its done mark is set "
        "in the same step; needs `currentAgendaItemId` in the same patch",
    )
    protokollantId: str | None = None
    publicJoin: bool | None = Field(
        default=None,
        description="Switching it off voids the open join requests and removes the "
        "admitted guests; their cast ballots stay counted.",
    )
    guestsMode: Literal["vote", "watch"] | None = Field(
        default=None,
        description="`watch` gives 409 `guest_vote_open` while a vote with guests is open.",
    )
    kind: Literal["ordinary", "extraordinary", "repeat", "constituent"] | None = Field(
        default=None,
        description="The kind of the meeting. It changes only while the meeting is planned "
        "(409 `meeting_not_planned`).",
    )
    repeatOfId: str | None = Field(
        default=None,
        description="The first meeting of a `repeat` meeting: an earlier meeting of the same "
        "Gremium. A meeting that becomes `repeat` needs it (422 "
        "`repeat_needs_first_meeting`, `repeat_first_meeting_invalid`).",
    )
    location: str | None = Field(default=None, description="The place, at most 200 characters.")
    form: Literal["presence", "hybrid", "video"] | None = Field(
        default=None, description="The form of the meeting. A new meeting is `presence`."
    )


class DecisionProposal(WireModel, frozen=True):
    """A decision: the approved amount and the conditions (approval with deviations).

    When a vote with this proposal passes, the proposal becomes the decision of the
    application. The cost center then binds the approved amount.
    """

    approvedAmount: str | None = Field(
        default=None,
        description="Approved amount as a decimal string, e.g. \"800.00\". Greater than 0 "
        "and not above the requested amount (422 `approved_amount_invalid` / "
        "`approved_amount_exceeds_requested`). null means as requested.",
    )
    conditions: list[str] = Field(
        default_factory=list,
        description="Conditions (Auflagen), at most 20, each 1 to 1000 characters.",
    )


class ElectionCandidateIn(WireModel, frozen=True):
    """One candidate of a personnel election. The server gives the ids c1..cn.

    Only `name` and `principalId`. The server rejects any other key with 422, so do
    not copy `id` or `erased` from a vote read into a new election.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(description="Display name, 1 to 200 characters.")
    principalId: str | None = Field(
        default=None,
        description="Account of the candidate, if the person has one (422 "
        "`candidate_unknown` for an unknown id). One person is a candidate only once.",
    )


class MeetingVoteOpenBody(WireModel, frozen=True):
    """Open a live vote. A meeting vote has no casting vote: a tie is `rejected`.

    `kind: "election"` opens a personnel election: `question` names the round,
    `seats` the number of posts and `candidates` the persons (at least `seats`). An
    election is only possible on a free-text item (422 `election_on_application_item`).
    The server ignores `options` for an election: each voter gives up to `seats` votes,
    the candidates with the most votes are elected. `majorityRule` `members_majority`
    on an election for one seat asks for more votes than half of all eligible members;
    without that majority nobody is elected (result `no_majority`). Other rules do not
    change an election.
    """

    agendaItemId: str
    kind: Literal["motion", "election"] = "motion"
    question: str | None = None
    options: list[str] = Field(default_factory=lambda: ["yes", "no", "abstain"])
    majorityRule: Literal[
        "simple", "absolute", "two_thirds", "members_majority", "members_two_thirds"
    ] = Field(
        default="simple",
        description=(
            "`members_majority` and `members_two_thirds` count the yes ballots against "
            "all eligible members; the other rules count against the cast ballots. The "
            "vote on a Haushaltsplan always uses `members_majority`."
        ),
    )
    secret: bool | None = Field(
        default=None,
        description="A motion and an election are always secret. Leave it out; false "
        "gives 422 `open_vote_unavailable`.",
    )
    seats: int = Field(default=1, ge=1, le=50, description="Election only: posts.")
    candidates: list[ElectionCandidateIn] = Field(
        default_factory=list, description="Election only: 1 to 50 candidates."
    )
    # The server counts the eligible voters from the roster of the gremium and takes the
    # quorum from the settings of the gremium. A quorum on one vote gives 422.
    guestsVote: bool | None = Field(
        default=None,
        description="Public meeting: the admitted guests vote too (no quorum, majority of "
        "the cast ballots). Default: on when guests vote in the meeting and the item is "
        "public. Never on a non-public item (422).",
    )
    proposal: DecisionProposal | None = Field(
        default=None,
        description="Decision proposal of an application item. A free-text item gives "
        "422 `decision_not_allowed`.",
    )
    draft: bool = Field(
        default=False,
        description="Prepare the question only: it stays a draft, also in a planned "
        "meeting, until `open_meeting_vote` opens it in the live meeting.",
    )


class VoteCreate(WireModel, frozen=True):
    """Application-bound vote (voting module).

    The server counts the eligible voters from the roster of the gremium. The body has
    no `eligibleCount`.
    """

    config: dict[str, Any] = Field(
        description=(
            "Vote config: options, majorityRule, quorum, abstainCountsQuorum. A tie "
            "always rejects: `tieBreak` other than `rejected` gives 422. The vote is "
            "always secret: `secret` false gives 422. A ballot "
            "never changes after the cast, so there is no `allowChange` (the server "
            "refuses the key with 422)."
        )
    )
    eligibleGroup: str = Field(
        description=(
            "UUID of the gremium that votes. It must be the gremium of the application "
            "(see `get_application` / `list_gremien`). A free group key gives 422."
        )
    )
    question: str | None = None
    opensStateId: str | None = None
    closesAt: str | None = Field(default=None, description="ISO datetime")
    resultBranchTransitionId: str | None = None
    proposal: DecisionProposal | None = Field(
        default=None, description="Decision proposal that applies when the vote passes."
    )


# Notification settings, delegations and substitutes.
class NotificationSettingsUpdate(WireModel, frozen=True):
    taskReminderEnabled: bool | None = None
    taskReminderAfterDays: int | None = None
    taskReminderRepeatDays: int | None = None


class GuestSettingsUpdate(WireModel, frozen=True):
    confirmTtlHours: int = Field(
        ge=1, le=720, description="Hours a guest has to confirm the email (1..720)"
    )
    # Required on purpose, like in the backend: the PUT replaces both fields, and
    # null means "no expiry". A default would silently remove the expiry when a
    # caller changes only confirmTtlHours.
    linkTtlDays: int | None = Field(
        ge=1,
        le=3650,
        description=(
            "Lifetime of a new magic link in days. Required: send null for no expiry, "
            "or the current value from get_guest_settings to keep it"
        ),
    )


class MeetingSettingsUpdate(WireModel, frozen=True):
    openLeadMinutes: int = Field(
        ge=0,
        le=10080,
        description="Earliest open of a meeting, in minutes before its planned start",
    )


class DelegationCreate(WireModel, frozen=True):
    meetingId: str
    delegateId: str
    delegatorId: str | None = Field(
        default=None,
        description=(
            "Meeting lead only, while the meeting is live: the missing member to "
            "substitute. The delegate must be in the substitute pool for that member "
            "(a personal entry for the member or a gremium-wide entry). "
            "Leave unset to delegate for yourself while the meeting is planned."
        ),
    )


class SubstituteCreate(WireModel, frozen=True):
    gremiumId: str
    memberId: str | None = Field(default=None, description="None = pool substitute for any member")
    substituteId: str


TodoLinkKind = Literal[
    "application",
    "meeting",
    "agenda_item",
    "vote",
    "appointment",
    "gremium",
    "invoice",
    "expense",
    "budget",
    "ticket",
    "todo",
]
TicketKind = Literal["bug", "question", "idea", "barrier"]
TicketStatus = Literal["new", "in_progress", "waiting", "done", "rejected"]


class TodoLinkIn(WireModel, frozen=True):
    kind: TodoLinkKind
    targetId: str = Field(
        description="The id of the linked object; the caller must be able to read it"
    )


#: The kinds of a link end of the link tools: the card kinds and a Paperless document
#: (§F/integrations/mcp/002922).
LinkKind = Literal[
    "application",
    "meeting",
    "agenda_item",
    "vote",
    "appointment",
    "gremium",
    "invoice",
    "expense",
    "budget",
    "ticket",
    "todo",
    "paperless",
]

#: The kinds of an element whose filed Paperless document has an address.
PaperlessElementKind = Literal["protocol", "application", "plan"]


class LinkEndIn(WireModel, frozen=True):
    kind: LinkKind
    id: str = Field(
        description=(
            "The id of the element; the caller must be able to read it. For the kind "
            "`paperless` the number of the document in Paperless, for example `41`"
        )
    )


TodoEntryRole = Literal["read", "edit", "manage"]


TodoLabelColor = Literal["green", "blue", "violet", "amber", "red", "gray"]


class TodoEventIn(WireModel, frozen=True):
    """The event data of a card (Veranstaltung)."""

    startsOn: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    endsOn: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    startTime: str | None = Field(default=None, description="HH:MM")
    endTime: str | None = Field(default=None, description="HH:MM")
    place: str | None = Field(default=None, description="Up to 200 characters")
    participants: int | None = Field(default=None, description="Expected number of participants")
    seriesId: str | None = Field(
        default=None, description="The Reihe of the event (see `todo_series`)"
    )


class TodoBoardEntryIn(WireModel, frozen=True):
    gremiumId: str | None = Field(default=None, description="A gremium; or set principalId")
    principalId: str | None = Field(default=None, description="A person; or set gremiumId")
    role: TodoEntryRole = Field(
        default="edit",
        description="read reads, edit works on the cards, manage also changes the board",
    )


class TodoCardCreate(WireModel, frozen=True):
    boardId: str
    columnId: str | None = Field(default=None, description="Default: the first column")
    title: str = Field(description="1 to 300 characters")
    descriptionMd: str | None = Field(default=None, description="Markdown, up to 20000 characters")
    dueDate: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    assigneeIds: list[str] | None = Field(
        default=None,
        description="Principal ids; each must be a member of the board (422 otherwise)",
    )
    labelIds: list[str] | None = Field(default=None, description="Label ids of the same board")
    links: list[TodoLinkIn] | None = None
    checklist: list[str] | None = Field(
        default=None, description="The texts of the first checklist items (subtasks), up to 100"
    )
    event: TodoEventIn | None = Field(
        default=None, description="Event data: the card is an Event (Veranstaltung) for good"
    )


class TodoCardPatch(WireModel, frozen=True):
    version: int = Field(description="The `version` of the card as last read; 409 on a mismatch")
    title: str | None = Field(default=None, description="1 to 300 characters")
    descriptionMd: str | None = Field(default=None, description="Markdown; explicit null clears it")
    dueDate: str | None = Field(default=None, description="ISO date; explicit null clears it")


class TicketCategoryIn(WireModel, frozen=True):
    id: str | None = Field(
        default=None, description="The id of a stored Kategorie; leave out for a new one"
    )
    name: str


class TicketAreaCreate(WireModel, frozen=True):
    name: str
    gremiumId: str | None = Field(
        default=None, description="The Gremium whose roles grant ticket.work in the Bereich"
    )
    notifyNew: bool = Field(default=True, description="Mail each new ticket to the team")
    inApp: bool = Field(
        default=False,
        description="A signed-in person can choose the Bereich in the ticket dialog",
    )
    categories: list[TicketCategoryIn] = Field(default_factory=list)


class TicketAreaPatch(WireModel, frozen=True):
    name: str | None = None
    gremiumId: str | None = Field(
        default=None, description="Explicit null leaves the Bereich without a Gremium"
    )
    notifyNew: bool | None = None
    inApp: bool | None = Field(
        default=None,
        description="A signed-in person can choose the Bereich in the ticket dialog",
    )
    categories: list[TicketCategoryIn] | None = Field(
        default=None,
        description="The whole ordered list; a stored Kategorie that is left out is deleted",
    )


class TicketManualCreate(WireModel, frozen=True):
    areaId: str = Field(description="A Bereich in which the caller works")
    title: str = Field(description="1 to 200 characters")
    body: str = Field(default="", description="The note of the team; the person does not read it")
    kind: TicketKind | None = Field(
        default=None, description="Required for the Bereich Plattform, not allowed elsewhere"
    )
    categoryId: str | None = Field(
        default=None, description="A Kategorie of the Bereich; not for Plattform"
    )
    reporterId: str | None = Field(
        default=None, description="The account of the person; or set email"
    )
    email: str | None = Field(
        default=None,
        description="The address of the person; the Bereich needs a Postfach (422 otherwise)",
    )
    message: str = Field(default="", description="The first public message to the person")


class TicketPatch(WireModel, frozen=True):
    status: TicketStatus | None = None
    assigneeId: str | None = Field(
        default=None,
        description="A person with the work right in the Bereich of the ticket (see the "
        "ticket assignees with `area`); explicit null unassigns",
    )
    kind: TicketKind | None = Field(
        default=None, description="The Kategorie of a ticket of the Bereich Plattform"
    )
    categoryId: str | None = Field(
        default=None,
        description="A Kategorie of the Bereich of the ticket (see the ticket areas); "
        "explicit null clears it. Not for a ticket of Plattform",
    )
    areaId: str | None = Field(
        default=None,
        description="Move the ticket to this Bereich: clears the Kategorie, and the "
        "assignee without the work right there",
    )
    duplicateOfId: str | None = Field(
        default=None, description="Another ticket's id; only together with status `rejected`"
    )
    completeTodos: bool | None = Field(
        default=None,
        description="Only with status `done` or `rejected`: move every open linked to-do the "
        "caller can write into its done column",
    )


def dump_create(model: BaseModel) -> dict[str, Any]:
    """Dump a create body: drop None values, keep defaults, use the wire aliases."""
    return model.model_dump(by_alias=True, exclude_none=True)


def dump_patch(model: BaseModel) -> dict[str, Any]:
    """Dump a patch body with only the keys that the caller set, for a partial update."""
    return model.model_dump(by_alias=True, exclude_unset=True)
