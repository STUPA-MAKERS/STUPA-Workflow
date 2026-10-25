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
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from app.shared.guards import (
    ASSIGN_BUDGET_ACTION_TYPES,
    GREMIUM_SOURCE_BUDGET,
    GuardError,
    validate_action,
    validate_guard,
)
from app.shared.i18n import I18nMap
from app.shared.jsonlogic import JsonLogicError, validate_jsonlogic

#: Pattern of a field or state key: lowercase snake case.
KEY_PATTERN = r"^[a-z][a-z0-9_]*$"

#: Max length of a field-validation pattern. An admin-authored regex runs synchronously
#: against possibly anonymous input, so this bound limits its complexity (ReDoS).
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


#: Field types of a form. ``gremium_select`` and ``budget_select`` are selects whose
#: options the server injects at render time (``effective_form``); the stored value is
#: a UUID. ``email`` and ``iban`` validate themselves, ``daterange`` holds ISO dates
#: ``{from, to}`` with from <= to. ``positions`` is a list of cost positions: each needs
#: minOffers comparison offers, exactly one offer is preferred and gives the position
#: value, and the sum is the amount. ``funding`` is the requested amount, at most one per
#: form, only beside ``positions`` and never above the cost total; when filled it is
#: the amount. ``section`` only splits a multi-step form and has no value.
FieldType = Literal[
    "text",
    "textarea",
    "number",
    "currency",
    "date",
    "select",
    "multiselect",
    "gremium_select",
    "budget_select",
    "email",
    "iban",
    "daterange",
    "checkbox",
    "file",
    "table",
    "markdown",
    "computed",
    "positions",
    "funding",
    "section",
]
#: Event names that the notification and the webhook config share.
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
]


class _CamelModel(BaseModel):
    """Base: camelCase aliases in JSON, fields fillable by name, no extra field."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class FlowValidationError(Exception):
    """The flow graph violates a structural rule (initial, reachability, ref, op, action)."""


class FieldOption(_CamelModel):
    """One option of a select field."""
    value: str
    label: I18nMap


class FieldValidation(_CamelModel):
    """Validation constraints of one form field.

    Attributes:
        min_offers: For ``positions``, the minimum comparison offers per position.
        max_positions: For ``positions``, the max positions. Without a builder value
            the engine applies a default cap, so the body cap is not the only bound on
            validation and on ``positions_total``.
        allow_no_offers: For ``positions``, allow the per-position opt-out of offers.
            The opt-out is a checkbox with a mandatory reason, and the position then
            needs only one offer. Unset means allowed.
    """
    min: float | None = None
    max: float | None = None
    min_len: int | None = Field(default=None, alias="minLen", ge=0)
    max_len: int | None = Field(default=None, alias="maxLen", ge=0)
    pattern: str | None = None
    file_types: list[str] | None = Field(default=None, alias="fileTypes")
    max_size_mb: float | None = Field(default=None, alias="maxSizeMB", gt=0)
    max_rows: int | None = Field(default=None, alias="maxRows", ge=0)
    min_offers: int | None = Field(default=None, alias="minOffers", ge=1)
    min_positions: int | None = Field(default=None, alias="minPositions", ge=1)
    max_positions: int | None = Field(default=None, alias="maxPositions", ge=1)
    max_offers: int | None = Field(default=None, alias="maxOffers", ge=1)
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
    """Definition of one form field."""
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
        """Reject a ``visibleIf`` or ``compute`` rule with a non-whitelisted operator."""
        if v is not None:
            try:
                validate_jsonlogic(v)
            except JsonLogicError as exc:
                raise ValueError(str(exc)) from exc
        return v

    @model_validator(mode="after")
    def _check_promote_and_options(self) -> FormFieldDef:
        """Require the promote target, the select options and the compute rule."""
        if self.is_promoted and not self.promote_target:
            raise ValueError("promoteTarget is required when isPromoted is true")
        if self.type in ("select", "multiselect") and not self.options:
            raise ValueError(f"options are required for type {self.type!r}")
        if self.type == "computed" and self.compute is None:
            raise ValueError("compute is required for type 'computed'")
        return self


StateKind = Literal["normal", "vote"]
TransitionBranch = Literal["pass", "fail"]


class StateDef(_CamelModel):
    """One state of a flow graph.

    Attributes:
        is_terminal: Retention and anonymization apply to an application in this state.
    """
    key: str = Field(pattern=KEY_PATTERN)
    label: I18nMap
    color: str | None = None
    edit_allowed: bool = Field(default=True, alias="editAllowed")
    is_initial: bool = Field(default=False, alias="isInitial")
    is_terminal: bool = Field(default=False, alias="isTerminal")
    kind: StateKind = "normal"
    config: dict[str, Any] = Field(default_factory=dict)


class TransitionDef(_CamelModel):
    """One transition of a flow graph.

    Attributes:
        color: Color of the editor arrow and of the decision button.
        automatic: The worker fires the transition once the guard holds.
        branch: Result branch of a vote state (pass or fail).
        requires_action: The transition counts as an open task of the actor (Tasks
            tab). False marks a purely optional action.
    """
    from_: str = Field(alias="from")
    to: str
    label: I18nMap | None = None
    color: str | None = None
    guard: dict[str, Any] | None = None
    actions: list[dict[str, Any]] = Field(default_factory=list)
    order: int | None = None
    automatic: bool = False
    branch: TransitionBranch | None = None
    requires_action: bool = Field(default=True, alias="requiresAction")


class FlowGraph(_CamelModel):
    """A flow: its states, transitions and editor layout."""
    states: list[StateDef]
    transitions: list[TransitionDef] = Field(default_factory=list)
    layout: dict[str, Any] | None = None


def validate_flow_graph(graph: FlowGraph) -> None:
    """Check the structure of a flow graph.

    The graph needs at least one state and exactly one initial state. The state keys
    must be unique. Every `from` and `to` reference must name a known state. Every
    state must be reachable from the initial state. A guard may use only whitelisted
    operators. An action must have a known type.

    A self-loop is refused, because the optimistic locking of the engine
    (``WHERE current_state_id = from_state``) cannot detect a concurrent double firing
    of a from==to transition, which duplicates events and actions. The actor gates
    (roleIs, isInCommittee) are allowed only on a manual transition.
    ``addToNextSession`` may only lead into a ``vote`` state. A vote state with
    ``gremiumSource: "budget"`` takes its Gremium from the cost center on entry, before
    the post-commit actions run. So an action of the same transition that sets the cost
    center comes too late, and an agenda action with a fixed ``gremiumId`` could name
    another Gremium; both are refused. A ``voteGremium`` recipient is valid only into a
    vote state, because the engine clears that snapshot on every other target before
    the mail goes out.

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
    budget_vote_keys = {
        s.key
        for s in states
        if s.kind == "vote" and s.config.get("gremiumSource") == GREMIUM_SOURCE_BUDGET
    }
    for t in graph.transitions:
        if t.from_ not in key_set:
            raise FlowValidationError(f"transition references unknown from-state: {t.from_!r}")
        if t.to not in key_set:
            raise FlowValidationError(f"transition references unknown to-state: {t.to!r}")
        if t.from_ == t.to:
            raise FlowValidationError(
                f"transition {t.from_!r} -> {t.to!r}: self-loops are not supported"
            )
        try:
            validate_guard(t.guard, allow_actor_ops=not t.automatic)
            for action in t.actions:
                validate_action(action)
                if action.get("type") == "addToNextSession" and kind_by_key.get(t.to) != "vote":
                    raise GuardError(
                        "addToNextSession action is only valid on a transition into a vote state"
                    )
                if (
                    action.get("type") in ASSIGN_BUDGET_ACTION_TYPES
                    and t.to in budget_vote_keys
                ):
                    raise GuardError(
                        f"{action.get('type')} action is not valid on a transition into "
                        "a vote state whose Gremium comes from the cost center; assign "
                        "the cost center on an earlier transition"
                    )
                if (
                    action.get("type") == "addToNextSession"
                    and "gremiumId" in action
                    and t.to in budget_vote_keys
                ):
                    raise GuardError(
                        "addToNextSession must not name a gremiumId on a transition into "
                        "a vote state whose Gremium comes from the cost center"
                    )
                if (
                    action.get("type") == "notify"
                    and kind_by_key.get(t.to) != "vote"
                    and any(
                        isinstance(r, dict) and r.get("kind") == "voteGremium"
                        for r in action.get("recipients") or []
                    )
                ):
                    raise GuardError(
                        "notify recipient kind 'voteGremium' is only valid on a "
                        "transition into a vote state"
                    )
        except GuardError as exc:
            raise FlowValidationError(str(exc)) from exc

    _validate_state_kinds(graph, key_set)
    _assert_all_reachable(initials[0], key_set, graph.transitions)
    _assert_no_automatic_cycle(key_set, graph.transitions)


def _validate_state_kinds(graph: FlowGraph, key_set: set[str]) -> None:
    """Check the structure of the ``vote`` states.

    Only the kinds ``normal`` and ``vote`` exist. A ``vote`` state needs exactly one
    of ``config.gremiumId`` (a fixed Gremium) or ``config.gremiumSource: "budget"``
    (the deciding Gremium of the cost center). It also needs exactly two outgoing
    transitions, one with branch ``pass`` and one with branch ``fail``.

    A vote state has no automatic non-branch exit, because the worker fires it as soon
    as its guard holds and the application would be "approved" without any vote. A
    normal state has no branch transition, because only a vote outcome fires one, so it
    would be a dead edge.
    """
    outgoing: dict[str, list[TransitionDef]] = {k: [] for k in key_set}
    for t in graph.transitions:
        if t.from_ in outgoing:
            outgoing[t.from_].append(t)

    for s in graph.states:
        branches = sorted(t.branch for t in outgoing[s.key] if t.branch)
        if s.kind == "vote":
            _validate_vote_gremium(s)
            if branches != ["fail", "pass"]:
                raise FlowValidationError(
                    f"vote state {s.key!r} needs exactly two outgoing transitions "
                    "with branch 'pass' and 'fail'"
                )
            for t in outgoing[s.key]:
                if t.automatic and not t.branch:
                    raise FlowValidationError(
                        f"vote state {s.key!r} must not have automatic outgoing "
                        "transitions — only the vote outcome (pass/fail) or a "
                        "manual exit may leave it"
                    )
        elif branches:
            raise FlowValidationError(
                f"state {s.key!r} (kind={s.kind!r}) must not have branch transitions"
            )


def _validate_vote_gremium(state: StateDef) -> None:
    """Check that a vote state names its Gremium in exactly one way.

    Raises:
        FlowValidationError: The state sets both ``gremiumId`` and ``gremiumSource``,
            neither of them, an empty ``gremiumId``, or an unknown ``gremiumSource``.
            The initial state cannot use ``gremiumSource``, because a new
            application has no cost center yet.
    """
    has_id = "gremiumId" in state.config
    has_source = "gremiumSource" in state.config
    if has_id and has_source:
        raise FlowValidationError(
            f"vote state {state.key!r} must set either config.gremiumId or "
            "config.gremiumSource, not both"
        )
    if has_source:
        if state.config["gremiumSource"] != GREMIUM_SOURCE_BUDGET:
            raise FlowValidationError(
                f"vote state {state.key!r}: config.gremiumSource must be "
                f"{GREMIUM_SOURCE_BUDGET!r}"
            )
        if state.is_initial:
            raise FlowValidationError(
                f"vote state {state.key!r}: the initial state cannot take its Gremium "
                "from the cost center"
            )
        return
    gremium_id = state.config.get("gremiumId")
    if not isinstance(gremium_id, str) or not gremium_id:
        raise FlowValidationError(
            f"vote state {state.key!r} requires config.gremiumId or "
            "config.gremiumSource 'budget'"
        )


def _assert_all_reachable(
    initial: str, key_set: set[str], transitions: list[TransitionDef]
) -> None:
    """Raise FlowValidationError when a state is not reachable from the initial one."""
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


class Quorum(_CamelModel):
    """Quorum of a vote: a count or a percentage."""
    type: Literal["count", "percent"]
    value: float = Field(ge=0)


#: Keys that an old vote row can still hold. ``VoteConfig.from_stored`` drops them.
_LEGACY_VOTE_KEYS = frozenset({"allowChange", "allow_change"})


class VoteConfig(_CamelModel):
    """The rules of one vote, stored as JSONB in ``vote.config``.

    A ballot can never change after the cast, so the config has no
    ``allowChange``. Migration ``vote_closed_at`` removes the key from the old rows,
    because ``extra=forbid`` refuses it. The API still refuses the key on create. To
    read a stored row, use ``from_stored``: an old container can write the key during a
    deploy, after the migration ran.

    Attributes:
        guests_vote: In a public meeting the admitted guests vote too. Such a vote
            has no quorum; only the majority of the cast ballots counts. Only a
            meeting vote in a meeting with ``guests_mode = vote`` sets it, never on a
            non-public agenda item.
    """

    options: list[str] = Field(min_length=2)
    majority_rule: Literal["simple", "absolute", "two_thirds"] = Field(alias="majorityRule")
    quorum: Quorum | None = None
    abstain_counts_quorum: bool = Field(default=True, alias="abstainCountsQuorum")
    secret: bool = False
    tie_break: Literal["passed", "rejected", "tie"] = Field(default="rejected", alias="tieBreak")
    guests_vote: bool = Field(default=False, alias="guestsVote")

    @model_validator(mode="after")
    def _guests_vote_has_no_quorum(self) -> VoteConfig:
        """A vote with guests has no quorum: only the majority of the cast ballots."""
        if self.guests_vote and self.quorum is not None:
            raise ValueError("a vote with guests (guestsVote) has no quorum")
        return self

    @field_validator("options")
    @classmethod
    def _unique_options(cls, v: list[str]) -> list[str]:
        """Refuse duplicate options."""
        if len(set(v)) != len(v):
            raise ValueError("vote options must be unique")
        return v

    @classmethod
    def from_stored(cls, data: Mapping[str, Any] | VoteConfig) -> VoteConfig:
        """Validate a stored ``vote.config`` row.

        The method drops the legacy ``allowChange`` key (and only that key) before the
        validation. ``extra=forbid`` still refuses every other unknown key. A
        ``VoteConfig`` instance passes as it is. An election row (with ``seats``) and a
        poll row (with ``mode``) return their projection on the motion rules, so the
        readers of secret, guests and options work for every vote kind.
        """
        if isinstance(data, VoteConfig):
            return data
        if "seats" in data:
            return ElectionConfig.model_validate(data).as_vote_config()
        if "mode" in data:
            return PollConfig.model_validate(data).as_vote_config()
        return cls.model_validate({k: v for k, v in data.items() if k not in _LEGACY_VOTE_KEYS})


#: Answer keys of the single-candidate ballot (Ja/Nein/Enthaltung) and of a full
#: abstention. A candidate id never takes one of them.
ELECTION_RESERVED_IDS = frozenset({"yes", "no", "abstain"})
ELECTION_MAX_CANDIDATES = 50


class ElectionCandidate(_CamelModel):
    """One candidate of an election.

    ``id`` is the key of the candidate in the ballots and in the result. The server
    sets it (``c1``, ``c2``, ...), and a runoff keeps the ids of its parent.
    ``principalId`` links an account; a candidate without an account has a name only.
    ``erased`` marks a candidate whose name the DSGVO erasure replaced
    (``voting.erasure``): ``name`` then holds the German placeholder and the UI shows
    its own label. Only the erasure sets it; the create body of an election
    (``livevote.schemas.ElectionCandidateIn``) has no such field.
    """

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    principal_id: UUID | None = Field(default=None, alias="principalId")
    erased: bool = False

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("the candidate name is empty")
        return stripped


class ElectionConfig(_CamelModel):
    """The rules of one election, stored as JSONB in ``vote.config``.

    ``vote.kind = 'election'`` marks the row. An election has no majority rule and no
    tie break: the relative majority elects, a tie at the seat boundary goes to a
    runoff (several seats) or to the lot (one seat, or a runoff round). One candidate
    for one seat is a Ja/Nein/Enthaltung ballot: elected when Ja > Nein.
    """

    seats: int = Field(ge=1, le=ELECTION_MAX_CANDIDATES)
    candidates: list[ElectionCandidate] = Field(
        min_length=1, max_length=ELECTION_MAX_CANDIDATES
    )
    secret: bool = True
    quorum: Quorum | None = None
    abstain_counts_quorum: bool = Field(default=True, alias="abstainCountsQuorum")
    guests_vote: bool = Field(default=False, alias="guestsVote")

    def public(self) -> ElectionConfig:
        """Return the config without the account links of the candidates.

        The beamer and the guests see the names only, never a principal id.
        """
        if all(c.principal_id is None for c in self.candidates):
            return self
        return self.model_copy(
            update={
                "candidates": [
                    c.model_copy(update={"principal_id": None}) for c in self.candidates
                ]
            }
        )

    @model_validator(mode="after")
    def _check(self) -> ElectionConfig:
        ids = [c.id for c in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("candidate ids must be unique")
        if ELECTION_RESERVED_IDS & set(ids):
            raise ValueError("a candidate id must not be yes, no or abstain")
        principals = [c.principal_id for c in self.candidates if c.principal_id is not None]
        if len(set(principals)) != len(principals):
            raise ValueError("a person can stand only once")
        if len(self.candidates) < self.seats:
            raise ValueError("an election needs at least as many candidates as seats")
        if self.guests_vote and self.quorum is not None:
            raise ValueError("a vote with guests (guestsVote) has no quorum")
        return self

    @property
    def yes_no(self) -> bool:
        """Tell whether the ballot is Ja/Nein/Enthaltung (one candidate, one seat)."""
        return len(self.candidates) == 1

    @property
    def candidate_ids(self) -> list[str]:
        """Return the candidate ids in ballot order."""
        return [c.id for c in self.candidates]

    def as_vote_config(self) -> VoteConfig:
        """Project the election on the motion rules for the shared vote readers.

        The options are the candidate ids plus ``abstain`` (or Ja/Nein/Enthaltung for
        one candidate). The majority rule of the projection is never applied: the
        election tally (``tally.tally_election``) decides.
        """
        options = ["yes", "no", "abstain"] if self.yes_no else [*self.candidate_ids, "abstain"]
        return VoteConfig(
            options=options,
            majorityRule="simple",
            quorum=self.quorum,
            abstainCountsQuorum=self.abstain_counts_quorum,
            secret=self.secret,
            tieBreak="tie",
            guestsVote=self.guests_vote,
        )


#: Minimum options of a poll. A poll only counts the answers: no quorum, no majority,
#: no lot, no flow branch. ``abstain`` keys the abstentions, so no option id takes it.
POLL_MIN_OPTIONS = 2
POLL_MAX_OPTIONS = 20
POLL_LABEL_MAX = 200
PollMode = Literal["single", "multi", "date"]
DateAnswer = Literal["yes", "maybe", "no"]


class PollOption(_CamelModel):
    """One option of a poll: a text (``label``) or a date (``start``, optional ``end``).

    The server sets ``id`` (``o1``, ``o2``, ...) in the order of the creator. A
    single and a multi poll take a label, a date poll takes the start and an optional
    end on the same date. ``PollConfig`` checks which form the mode needs.
    """

    id: str = Field(min_length=1, max_length=16, pattern=r"^o[0-9]+$")
    label: str | None = Field(default=None, min_length=1, max_length=POLL_LABEL_MAX)
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None

    @field_validator("label")
    @classmethod
    def _strip_label(cls, v: str | None) -> str | None:
        """Strip the label and refuse an empty one."""
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("the option label is empty")
        return stripped

    @model_validator(mode="after")
    def _end_after_start(self) -> PollOption:
        """Require the end of a date option after its start."""
        if self.end is not None and (self.start is None or self.end <= self.start):
            raise ValueError("the end of a date option must come after its start")
        return self


class PollConfig(_CamelModel):
    """The rules of one poll, stored as JSONB in ``vote.config`` (``vote.kind = 'poll'``).

    ``single``: one option or an abstention. ``multi``: 0 to ``maxChoices`` options
    (``[]`` = abstention; no ``maxChoices`` = every option). ``date``: Ja/Vielleicht/
    Nein for every date. ``secret`` uses the secret ballot tables of a vote.
    """

    mode: PollMode
    options: list[PollOption] = Field(min_length=POLL_MIN_OPTIONS, max_length=POLL_MAX_OPTIONS)
    max_choices: int | None = Field(default=None, alias="maxChoices", ge=1)
    secret: bool = False
    guests_vote: bool = Field(default=False, alias="guestsVote")

    @model_validator(mode="after")
    def _check(self) -> PollConfig:
        """Check unique ids, the option form of the mode and ``maxChoices``."""
        ids = self.option_ids
        if len(set(ids)) != len(ids):
            raise ValueError("poll option ids must be unique")
        dated = self.mode == "date"
        for option in self.options:
            if dated and (option.start is None or option.label is not None):
                raise ValueError("a date poll takes a start (and an end) for each option")
            if not dated and (option.label is None or option.start is not None):
                raise ValueError("a poll takes a label for each option")
        if self.max_choices is not None and (
            self.mode != "multi" or self.max_choices > len(self.options)
        ):
            raise ValueError("maxChoices needs a multi poll and at most one per option")
        return self

    @property
    def option_ids(self) -> list[str]:
        """Return the option ids in creator order."""
        return [o.id for o in self.options]

    @property
    def choice_limit(self) -> int:
        """Return the most options of one ballot (single: 1, multi: maxChoices)."""
        if self.mode == "single":
            return 1
        return self.max_choices or len(self.options)

    def as_vote_config(self) -> VoteConfig:
        """Project the poll on the motion rules for the shared vote readers.

        The options are the option ids plus ``abstain`` (a date poll has no
        abstention). The majority rule of the projection is never applied: the poll
        tally (``tally.tally_poll``) only counts.
        """
        options = self.option_ids if self.mode == "date" else [*self.option_ids, "abstain"]
        return VoteConfig(
            options=options,
            majorityRule="simple",
            quorum=None,
            secret=self.secret,
            tieBreak="tie",
            guestsVote=self.guests_vote,
        )


class Recipient(_CamelModel):
    """Recipient of a notification rule: a group, a role or the applicant."""
    kind: Literal["group", "role", "applicant"]
    ref: str | None = None

    @model_validator(mode="after")
    def _check_ref(self) -> Recipient:
        """Require ``ref`` for a group or role and forbid it for the applicant."""
        if self.kind in ("group", "role") and not self.ref:
            raise ValueError(f"recipient kind {self.kind!r} requires 'ref'")
        if self.kind == "applicant" and self.ref is not None:
            raise ValueError("recipient kind 'applicant' must not have 'ref'")
        return self


class NotificationRule(_CamelModel):
    """Rule that sends a mail template to recipients on an event."""
    event: EventName
    filter_type_id: UUID | None = Field(default=None, alias="filterTypeId")
    recipients: list[Recipient] = Field(min_length=1)
    template_key: str = Field(alias="templateKey")
    enabled: bool = True


class WebhookConfig(_CamelModel):
    """Config of one outgoing webhook."""
    name: str
    url: HttpUrl
    events: list[EventName] = Field(min_length=1)
    active: bool = True


class ComparisonOffers(_CamelModel):
    """Requirement for comparison offers on an application."""
    required: bool = False
    min_count: int = Field(default=2, alias="minCount", ge=0)
    threshold_amount: Decimal | None = Field(default=None, alias="thresholdAmount", ge=0)
    as_: Literal["file", "field", "both"] = Field(default="file", alias="as")


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
        "Branding": Branding,
    }


def export_json_schemas() -> dict[str, dict[str, Any]]:
    """Deterministic JSON-Schema export of all config models (by_alias)."""
    return {
        name: model.model_json_schema(by_alias=True) for name, model in _exported_models().items()
    }
