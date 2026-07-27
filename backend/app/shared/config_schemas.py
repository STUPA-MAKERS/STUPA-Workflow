"""Config schemas — the single source of truth.

Pydantic models for form definition, flow graph, voting rules, notification rules,
webhook config, comparison offers and budget-pot extra fields. The server always
validates authoritatively. The frontend gets the JSON-Schema export for its editors
and for client-side validation (`export_json_schemas`).

Guards, actions, `visibleIf` and `compute` reference the whitelist evaluators in
`jsonlogic` and `guards`. There is NO `eval`. `validate_flow_graph` checks a flow
graph: one initial state, all states reachable, known operators and known action
types.
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

# Field and state keys: lowercase, snake case.
KEY_PATTERN = r"^[a-z][a-z0-9_]*$"

# Max length of a field-validation pattern (save gate, ReDoS). An admin-authored regex
# runs synchronously against possibly anonymous input at response time. This bound
# limits its complexity.
_MAX_PATTERN_LEN = 200


def _redos_prone(pattern: str) -> bool:
    """Detect a pattern that is prone to ReDoS.

    The function returns ``True`` for an unbounded quantifier (``*``, ``+`` or
    ``{n,}``) whose body itself contains an unbounded quantifier. Examples are
    ``(a+)+``, ``(a*)*`` and ``([ab]+)+``. That is the classic catastrophic-backtracking
    form. The detector is best effort and uses the internal ``re`` parser. If that
    parser is absent, only the length bound applies. The detector misses some ReDoS
    variants, for example ``(a|a)*``. It still rules out the most common class at save
    time.
    """
    try:
        from re import _parser as sre_parse  # type: ignore[attr-defined]

        tokens = sre_parse.parse(pattern)
        maxrepeat = sre_parse.MAXREPEAT
    except Exception:  # pragma: no cover - CPython internals unavailable
        return False

    def children(op_name: str, av: Any) -> tuple:
        if op_name in ("MAX_REPEAT", "MIN_REPEAT"):
            return (av[2],)
        if op_name == "SUBPATTERN":
            return (av[3],)
        if op_name == "BRANCH":
            return tuple(av[1])
        return ()

    def has_unbounded_repeat(toks: Any) -> bool:
        for op, av in toks:
            if op.name in ("MAX_REPEAT", "MIN_REPEAT") and av[1] is maxrepeat:
                return True
            if any(has_unbounded_repeat(c) for c in children(op.name, av)):
                return True
        return False

    def walk(toks: Any) -> bool:
        for op, av in toks:
            if op.name in ("MAX_REPEAT", "MIN_REPEAT"):
                _min, _max, body = av
                if _max is maxrepeat and has_unbounded_repeat(body):
                    return True
                if walk(body):
                    return True
            elif any(walk(c) for c in children(op.name, av)):
                return True
        return False

    try:
        return walk(tokens)
    except Exception:  # pragma: no cover - unexpected AST shape -> length bound only
        return False


FieldType = Literal[
    "text",
    "textarea",
    "number",
    "currency",
    "date",
    "select",
    "multiselect",
    # Gremium and cost-center pickers: a `select` whose options the server injects at
    # render time from the current Gremien or from the budget tree (effective_form).
    # The form does not hold them. The stored value is a UUID.
    "gremium_select",
    "budget_select",
    # Typed inputs with built-in validation (instead of a hand-maintained `pattern`).
    "email",
    "iban",
    # Date range {from, to} — both ISO dates, from <= to.
    "daterange",
    "checkbox",
    "file",
    "table",
    "markdown",
    "computed",
    # Cost positions: a list of positions. Each position needs at least minOffers
    # comparison offers. Exactly one offer is the preferred one, and its value is the
    # position value. The sum of the positions is the amount.
    "positions",
    # Section marker (multi-step forms): carries only a label and splits the following
    # fields into a new step. No answer value, no validation.
    "section",
]
# Event names — shared by notification and webhook config.
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
    """Base: camelCase aliases in JSON, fields fillable by name, no extra field."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class FlowValidationError(Exception):
    """The flow graph violates a structural rule (initial, reachability, ref, op, action)."""


# Form definition
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
    # `positions`: minimum comparison offers per position / minimum positions.
    min_offers: int | None = Field(default=None, alias="minOffers", ge=1)
    min_positions: int | None = Field(default=None, alias="minPositions", ge=1)
    # `positions`: max positions and max offers per position. Even without a builder
    # value the engine applies a default cap. The body cap is then not the only bound
    # on validation and on `positions_total`.
    max_positions: int | None = Field(default=None, alias="maxPositions", ge=1)
    max_offers: int | None = Field(default=None, alias="maxOffers", ge=1)
    # `positions`: allow the per-position opt-out of comparison offers. The opt-out is a
    # checkbox with a mandatory reason. The position then needs only one offer. Unset
    # means allowed.
    allow_no_offers: bool | None = Field(default=None, alias="allowNoOffers")

    @field_validator("pattern")
    @classmethod
    def _check_pattern(cls, v: str | None) -> str | None:
        """Harden the pattern against ReDoS at save time.

        The check caps the length and rejects the catastrophic-backtracking forms.
        Without it the pattern runs synchronously against answer input, which can be
        anonymous, and without a timeout.

        ``validate_definition`` (form save) and the answer runtime (defensive 422) still
        check that the pattern compiles. This validator does NOT check that. An
        already-stored form therefore stays loadable, and the contract of the existing
        layers stays intact.
        """
        if v is None:
            return v
        if len(v) > _MAX_PATTERN_LEN:
            raise ValueError(f"validation pattern too long (max {_MAX_PATTERN_LEN} characters)")
        if _redos_prone(v):
            raise ValueError(
                "validation pattern has nested unbounded quantifiers (ReDoS risk); "
                "rewrite without a repeat inside a repeated group"
            )
        return v


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


# Flow graph
StateKind = Literal["normal", "vote"]
TransitionBranch = Literal["pass", "fail"]


class StateDef(_CamelModel):
    key: str = Field(pattern=KEY_PATTERN)
    label: I18nMap
    color: str | None = None
    edit_allowed: bool = Field(default=True, alias="editAllowed")
    is_initial: bool = Field(default=False, alias="isInitial")
    # Terminal state: retention and anonymization apply to a terminal application.
    is_terminal: bool = Field(default=False, alias="isTerminal")
    kind: StateKind = "normal"
    config: dict[str, Any] = Field(default_factory=dict)


class TransitionDef(_CamelModel):
    from_: str = Field(alias="from")
    to: str
    label: I18nMap | None = None
    # Optional color for the editor arrow and for the decision button in the
    # application.
    color: str | None = None
    guard: dict[str, Any] | None = None
    actions: list[dict[str, Any]] = Field(default_factory=list)
    order: int | None = None
    # The worker fires an automatic transition once the guard holds.
    automatic: bool = False
    # Result branch of a vote state: pass or fail.
    branch: TransitionBranch | None = None
    # Does a firable transition count as an open task for the actor (Tasks tab)?
    # ``False`` marks a purely optional action.
    requires_action: bool = Field(default=True, alias="requiresAction")


class FlowGraph(_CamelModel):
    states: list[StateDef]
    transitions: list[TransitionDef] = Field(default_factory=list)
    layout: dict[str, Any] | None = None


def validate_flow_graph(graph: FlowGraph) -> None:
    """Check the structure of a flow graph.

    The graph needs at least one state and exactly one initial state. The state keys
    must be unique. Every `from` and `to` reference must name a known state. Every
    state must be reachable from the initial state. A guard may use only whitelisted
    operators. An action must have a known type.

    Raises:
        FlowValidationError: The graph violates one of these rules.
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

    kind_by_key = {s.key: s.kind for s in states}
    for t in graph.transitions:
        if t.from_ not in key_set:
            raise FlowValidationError(f"transition references unknown from-state: {t.from_!r}")
        if t.to not in key_set:
            raise FlowValidationError(f"transition references unknown to-state: {t.to!r}")
        # The engine does not support a self-loop. Its optimistic locking
        # (``WHERE current_state_id = from_state``) cannot detect a concurrent double
        # firing of a from==to transition, which duplicates events and actions.
        if t.from_ == t.to:
            raise FlowValidationError(
                f"transition {t.from_!r} -> {t.to!r}: self-loops are not supported"
            )
        try:
            # Allow the actor gates (roleIs, isInCommittee) only on a manual transition.
            validate_guard(t.guard, allow_actor_ops=not t.automatic)
            for action in t.actions:
                validate_action(action)
                # ``addToNextSession`` may only lead into a ``vote`` state.
                if action.get("type") == "addToNextSession" and kind_by_key.get(t.to) != "vote":
                    raise GuardError(
                        "addToNextSession action is only valid on a transition into a vote state"
                    )
        except GuardError as exc:
            raise FlowValidationError(str(exc)) from exc

    _validate_state_kinds(graph, key_set)
    _assert_all_reachable(initials[0], key_set, graph.transitions)
    _assert_no_automatic_cycle(key_set, graph.transitions)


def _validate_state_kinds(graph: FlowGraph, key_set: set[str]) -> None:
    """Check the structure of the ``vote`` states.

    Only the kinds ``normal`` and ``vote`` exist. A ``vote`` state needs
    ``config.gremiumId``. It also needs exactly two outgoing transitions, one with
    branch ``pass`` and one with branch ``fail``.
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
            # Only the vote (pass/fail) or a deliberate manual abort may decide a vote
            # state. The worker fires an automatic non-branch exit as soon as its guard
            # holds. The application would then be "approved" without any vote.
            for t in outgoing[s.key]:
                if t.automatic and not t.branch:
                    raise FlowValidationError(
                        f"vote state {s.key!r} must not have automatic outgoing "
                        "transitions — only the vote outcome (pass/fail) or a "
                        "manual exit may leave it"
                    )
        elif branches:
            # Only the vote outcome fires a branch transition. On a normal state such a
            # transition is reachable neither manually nor automatically. It is a dead
            # edge.
            raise FlowValidationError(
                f"state {s.key!r} (kind={s.kind!r}) must not have branch transitions"
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


def _assert_no_automatic_cycle(
    key_set: set[str], transitions: list[TransitionDef]
) -> None:
    """Assert that the automatic subgraph has no cycle.

    A guard-less ``automatic`` transition fires at once on the minute cron. Take two
    normal states A and B, each with an automatic transition to the other. They pass
    the reachability check, but they ping-pong forever on every cron run. Each hop
    writes one StatusEvent, one audit row and one mail send. That is a mail bomb and
    audit bloat. The from==to rule already catches a self-loop. This check catches a
    cycle over two or more states. It runs a DFS over the automatic edges and reports a
    back edge as a cycle.
    """
    auto_adj: dict[str, list[str]] = {k: [] for k in key_set}
    for t in transitions:
        if t.automatic:
            auto_adj[t.from_].append(t.to)

    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {k: WHITE for k in key_set}

    def _visit(node: str, path: list[str]) -> None:
        color[node] = GREY
        path.append(node)
        for nxt in auto_adj[node]:
            if color[nxt] == GREY:
                cycle = path[path.index(nxt) :] + [nxt]
                raise FlowValidationError(
                    "automatic transitions form a cycle "
                    f"(infinite auto-advance): {' -> '.join(cycle)}"
                )
            if color[nxt] == WHITE:
                _visit(nxt, path)
        path.pop()
        color[node] = BLACK

    for key in key_set:
        if color[key] == WHITE:
            _visit(key, [])


# Voting rules
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


# Notification rule
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


class WebhookConfig(_CamelModel):
    name: str
    url: HttpUrl
    events: list[EventName] = Field(min_length=1)
    active: bool = True


class ComparisonOffers(_CamelModel):
    required: bool = False
    min_count: int = Field(default=2, alias="minCount", ge=0)
    threshold_amount: Decimal | None = Field(default=None, alias="thresholdAmount", ge=0)
    as_: Literal["file", "field", "both"] = Field(default="file", alias="as")


# A budget pot can add this extra field to the effective form.
class BudgetField(_CamelModel):
    field: FormFieldDef
    order: int = 0


# JSON-Schema export for the frontend editors and for client-side validation
def _exported_models() -> dict[str, type[BaseModel]]:
    """Return the config models to export.

    The function imports ``Branding`` lazily. This breaks the import cycle between
    ``shared`` and ``admin``.
    """
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
    """Deterministic JSON-Schema export of all config models (by_alias)."""
    return {
        name: model.model_json_schema(by_alias=True) for name, model in _exported_models().items()
    }
