"""Config-Schemas — Single Source of Truth (data-model §5).

Pydantic-Modelle für Form-Definition, Flow-Graph, Voting-Regeln, Notification-
Regeln, Webhook-Config, Comparison-Offers und Budget-Topf-Extra-Felder. Der Server
validiert immer autoritativ; das FE bekommt den **JSON-Schema-Export** für Editoren
und Client-Validierung (`export_json_schemas`).

Guards/Actions/`visibleIf`/`compute` referenzieren die Whitelist-Evaluatoren in
`jsonlogic` und `guards` — **kein `eval`**. Flow-Graphen werden mit
`validate_flow_graph` geprüft (ein Initial-State, erreichbar, bekannte Operatoren/
Action-Typen).
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.shared.guards import GuardError, validate_action, validate_guard
from app.shared.i18n import I18nMap
from app.shared.jsonlogic import JsonLogicError, validate_jsonlogic

# Feld-/State-Keys: kleinbuchstaben, snake-ähnlich (data-model §5.1).
KEY_PATTERN = r"^[a-z][a-z0-9_]*$"

FieldType = Literal[
    "text",
    "textarea",
    "number",
    "currency",
    "date",
    "select",
    "multiselect",
    "checkbox",
    "file",
    "table",
    "markdown",
    "computed",
]
StateCategory = Literal["open", "running", "closed"]

# Event-Namen (api.md §6) — geteilt von Notification- und Webhook-Config.
EventName = Literal[
    "application_created",
    "application_updated",
    "status_changed",
    "vote_opened",
    "vote_closed",
    "application_approved",
    "application_rejected",
    "comment_added",
    "budget_reserved",
    "budget_booked",
    "protocol_finalized",
    "deadline_approaching",
    "deadline_passed",
]


class _CamelModel(BaseModel):
    """Basis: camelCase-Aliase im JSON, Felder per Name befüllbar, kein Extra-Feld."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class FlowValidationError(Exception):
    """Flow-Graph verletzt eine Struktur-Regel (Initial/Erreichbarkeit/Ref/Op/Action)."""


# --------------------------------------------------------------------------- #
# 5.1 Form-Definition
# --------------------------------------------------------------------------- #
class FieldOption(_CamelModel):
    value: str
    label: I18nMap


class FieldValidation(_CamelModel):
    min: float | None = None
    max: float | None = None
    min_len: int | None = Field(default=None, alias="minLen", ge=0)
    max_len: int | None = Field(default=None, alias="maxLen", ge=0)
    pattern: str | None = None
    file_types: list[str] | None = Field(default=None, alias="fileTypes")
    max_size_mb: float | None = Field(default=None, alias="maxSizeMB", gt=0)
    max_rows: int | None = Field(default=None, alias="maxRows", ge=0)


class FormFieldDef(_CamelModel):
    key: str = Field(pattern=KEY_PATTERN)
    type: FieldType
    label: I18nMap
    help: I18nMap | None = None
    required: bool = False
    validation: FieldValidation | None = None
    options: list[FieldOption] | None = None
    visible_if: dict[str, Any] | None = Field(default=None, alias="visibleIf")
    compute: dict[str, Any] | None = None
    is_pii: bool = Field(default=False, alias="isPII")
    is_promoted: bool = Field(default=False, alias="isPromoted")
    promote_target: str | None = Field(default=None, alias="promoteTarget")

    @field_validator("visible_if", "compute")
    @classmethod
    def _check_jsonlogic(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None:
            try:
                validate_jsonlogic(v)
            except JsonLogicError as exc:
                raise ValueError(str(exc)) from exc
        return v

    @model_validator(mode="after")
    def _check_promote_and_options(self) -> FormFieldDef:
        if self.is_promoted and not self.promote_target:
            raise ValueError("promoteTarget is required when isPromoted is true")
        if self.type in ("select", "multiselect") and not self.options:
            raise ValueError(f"options are required for type {self.type!r}")
        if self.type == "computed" and self.compute is None:
            raise ValueError("compute is required for type 'computed'")
        return self


# --------------------------------------------------------------------------- #
# 5.2 Flow-Graph
# --------------------------------------------------------------------------- #
StateKind = Literal["normal", "vote", "approval", "decision"]
TransitionBranch = Literal["pass", "fail", "accept", "reject"]


class StateDef(_CamelModel):
    key: str = Field(pattern=KEY_PATTERN)
    label: I18nMap
    category: StateCategory | None = None
    color: str | None = None
    edit_allowed: bool = Field(default=True, alias="editAllowed")
    is_initial: bool = Field(default=False, alias="isInitial")
    # Global-Flow-Redesign (#28): State-Art + Konfiguration (vote/approval/decision).
    kind: StateKind = "normal"
    config: dict[str, Any] = Field(default_factory=dict)


class TransitionDef(_CamelModel):
    from_: str = Field(alias="from")
    to: str
    label: I18nMap | None = None
    guard: dict[str, Any] | None = None
    actions: list[dict[str, Any]] = Field(default_factory=list)
    order: int | None = None
    # Automatischer Übergang (#8): vom Worker gefeuert, sobald der Guard erfüllt ist.
    automatic: bool = False
    # Ergebnis-Zweig (#28) für vote/approval-States: pass/fail bzw. accept/reject.
    branch: TransitionBranch | None = None


class FlowGraph(_CamelModel):
    states: list[StateDef]
    transitions: list[TransitionDef] = Field(default_factory=list)
    layout: dict[str, Any] | None = None


def validate_flow_graph(graph: FlowGraph) -> None:
    """Flow-Graph strukturell prüfen (flows §9.5). Wirft `FlowValidationError`.

    Regeln: ≥1 State, **genau ein** Initial-State, keine doppelten State-Keys,
    keine danglenden `from`/`to`-Refs, alle States vom Initial erreichbar,
    Guards nur mit Whitelist-Operatoren, Actions nur mit bekannten Typen.
    """
    states = graph.states
    if not states:
        raise FlowValidationError("flow graph has no states")

    keys = [s.key for s in states]
    duplicates = {k for k in keys if keys.count(k) > 1}
    if duplicates:
        raise FlowValidationError(f"duplicate state keys: {sorted(duplicates)}")
    key_set = set(keys)

    initials = [s.key for s in states if s.is_initial]
    if len(initials) == 0:
        raise FlowValidationError("flow graph has no initial state")
    if len(initials) > 1:
        raise FlowValidationError(f"flow graph has multiple initial states: {initials}")

    for t in graph.transitions:
        if t.from_ not in key_set:
            raise FlowValidationError(f"transition references unknown from-state: {t.from_!r}")
        if t.to not in key_set:
            raise FlowValidationError(f"transition references unknown to-state: {t.to!r}")
        try:
            validate_guard(t.guard)
            for action in t.actions:
                validate_action(action)
        except GuardError as exc:
            raise FlowValidationError(str(exc)) from exc

    _validate_state_kinds(graph, key_set)
    _assert_all_reachable(initials[0], key_set, graph.transitions)


def _validate_state_kinds(graph: FlowGraph, key_set: set[str]) -> None:
    """vote/approval/decision-States strukturell prüfen (#28).

    * ``vote``     — ``config.gremiumId`` Pflicht; genau 2 Ausgänge ``pass``/``fail``.
    * ``approval`` — ``config.roleKey`` + ``config.gremiumId``; 2 Ausgänge ``accept``/``reject``.
    * ``decision`` — ``config.rules`` (Liste ``{when,to}``) + ``config.else``; Ziele gültig.
    """
    outgoing: dict[str, list[TransitionDef]] = {k: [] for k in key_set}
    for t in graph.transitions:
        if t.from_ in outgoing:
            outgoing[t.from_].append(t)

    for s in graph.states:
        branches = sorted(t.branch for t in outgoing[s.key] if t.branch)
        if s.kind == "vote":
            if not isinstance(s.config.get("gremiumId"), str):
                raise FlowValidationError(f"vote state {s.key!r} requires config.gremiumId")
            if branches != ["fail", "pass"]:
                raise FlowValidationError(
                    f"vote state {s.key!r} needs exactly two outgoing transitions "
                    "with branch 'pass' and 'fail'"
                )
        elif s.kind == "approval":
            # ``roleKey`` Pflicht; ``gremiumId`` OPTIONAL: fehlt es, entscheidet eine
            # **globale** Rolle (#28-CR), sonst die Gremium-Rolle im Gremium.
            if not isinstance(s.config.get("roleKey"), str):
                raise FlowValidationError(
                    f"approval state {s.key!r} requires config.roleKey"
                )
            gid = s.config.get("gremiumId")
            if gid is not None and not isinstance(gid, str):
                raise FlowValidationError(
                    f"approval state {s.key!r} config.gremiumId must be a string"
                )
            if branches != ["accept", "reject"]:
                raise FlowValidationError(
                    f"approval state {s.key!r} needs exactly two outgoing transitions "
                    "with branch 'accept' and 'reject'"
                )
        elif s.kind == "decision":
            rules = s.config.get("rules")
            fallback = s.config.get("else")
            if not isinstance(rules, list) or not isinstance(fallback, str):
                raise FlowValidationError(
                    f"decision state {s.key!r} requires config.rules (list) and config.else"
                )
            for rule in [*rules, {"to": fallback}]:
                target = rule.get("to") if isinstance(rule, dict) else None
                if not isinstance(target, str) or target not in key_set:
                    raise FlowValidationError(
                        f"decision state {s.key!r} routes to unknown state {target!r}"
                    )


def _assert_all_reachable(
    initial: str, key_set: set[str], transitions: list[TransitionDef]
) -> None:
    adjacency: dict[str, list[str]] = {k: [] for k in key_set}
    for t in transitions:
        adjacency[t.from_].append(t.to)
    seen: set[str] = set()
    queue: deque[str] = deque([initial])
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        queue.extend(adjacency[node])
    unreachable = key_set - seen
    if unreachable:
        raise FlowValidationError(f"unreachable states: {sorted(unreachable)}")


# --------------------------------------------------------------------------- #
# 5.3 Voting-Regeln
# --------------------------------------------------------------------------- #
class Quorum(_CamelModel):
    type: Literal["count", "percent"]
    value: float = Field(ge=0)


class VoteConfig(_CamelModel):
    options: list[str] = Field(min_length=2)
    majority_rule: Literal["simple", "absolute", "two_thirds"] = Field(alias="majorityRule")
    quorum: Quorum | None = None
    abstain_counts_quorum: bool = Field(default=True, alias="abstainCountsQuorum")
    secret: bool = False
    allow_change: bool = Field(default=True, alias="allowChange")
    tie_break: Literal["passed", "rejected", "tie"] = Field(default="rejected", alias="tieBreak")

    @field_validator("options")
    @classmethod
    def _unique_options(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("vote options must be unique")
        return v


# --------------------------------------------------------------------------- #
# 5.4 Notification-Regel
# --------------------------------------------------------------------------- #
class Recipient(_CamelModel):
    kind: Literal["group", "role", "applicant"]
    ref: str | None = None

    @model_validator(mode="after")
    def _check_ref(self) -> Recipient:
        if self.kind in ("group", "role") and not self.ref:
            raise ValueError(f"recipient kind {self.kind!r} requires 'ref'")
        if self.kind == "applicant" and self.ref is not None:
            raise ValueError("recipient kind 'applicant' must not have 'ref'")
        return self


class NotificationRule(_CamelModel):
    event: EventName
    filter_type_id: UUID | None = Field(default=None, alias="filterTypeId")
    recipients: list[Recipient] = Field(min_length=1)
    template_key: str = Field(alias="templateKey")
    enabled: bool = True


# --------------------------------------------------------------------------- #
# 5.5 Webhook-Config
# --------------------------------------------------------------------------- #
class WebhookConfig(_CamelModel):
    name: str
    url: HttpUrl
    events: list[EventName] = Field(min_length=1)
    active: bool = True


# --------------------------------------------------------------------------- #
# 5.6 Comparison-Offers-Regel
# --------------------------------------------------------------------------- #
class ComparisonOffers(_CamelModel):
    required: bool = False
    min_count: int = Field(default=2, alias="minCount", ge=0)
    threshold_amount: Decimal | None = Field(default=None, alias="thresholdAmount", ge=0)
    as_: Literal["file", "field", "both"] = Field(default="file", alias="as")


# --------------------------------------------------------------------------- #
# 5.7 Budget-Topf-Extra-Feld
# --------------------------------------------------------------------------- #
class BudgetField(_CamelModel):
    field: FormFieldDef
    order: int = 0


# --------------------------------------------------------------------------- #
# JSON-Schema-Export (für FE-Editoren / Client-Validierung, api.md /config-schemas)
# --------------------------------------------------------------------------- #
def _exported_models() -> dict[str, type[BaseModel]]:
    """Exportierte Config-Modelle. ``Branding`` (T-24/#21) wird lazy importiert, um
    den Import-Zyklus shared ↔ admin zu vermeiden."""
    from app.modules.admin.branding import Branding

    return {
        "FormFieldDef": FormFieldDef,
        "FlowGraph": FlowGraph,
        "VoteConfig": VoteConfig,
        "NotificationRule": NotificationRule,
        "WebhookConfig": WebhookConfig,
        "ComparisonOffers": ComparisonOffers,
        "BudgetField": BudgetField,
        "Branding": Branding,
    }


def export_json_schemas() -> dict[str, dict[str, Any]]:
    """Deterministischer JSON-Schema-Export aller Config-Modelle (by_alias)."""
    return {
        name: model.model_json_schema(by_alias=True)
        for name, model in _exported_models().items()
    }
