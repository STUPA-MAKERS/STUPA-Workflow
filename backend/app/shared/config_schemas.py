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

# Maximale Länge eines Feld-Validierungs-Patterns (Speicher-Gate, #sec-audit ReDoS).
# Admin-verfasste Regexes laufen zur Antwort-Laufzeit synchron gegen — teils anonyme —
# Eingabe; die Schranke begrenzt ihre Komplexität.
_MAX_PATTERN_LEN = 200


def _redos_prone(pattern: str) -> bool:
    """Konservativer ReDoS-Detektor: ``True`` bei einem **unbegrenzten** Quantor
    (``*``/``+``/``{n,}``), dessen Rumpf selbst einen unbegrenzten Quantor enthält
    (``(a+)+``, ``(a*)*``, ``([ab]+)+`` …) — die klassische katastrophale Backtracking-
    Form. Best-effort über den internen ``re``-Parser; fehlt er, greift nur die
    Längen-Schranke. Erkennt nicht jede ReDoS-Variante (z. B. ``(a|a)*``), schließt
    aber die häufigste Klasse beim Speichern aus."""
    try:
        from re import _parser as sre_parse  # type: ignore[attr-defined]

        tokens = sre_parse.parse(pattern)
        maxrepeat = sre_parse.MAXREPEAT
    except Exception:  # pragma: no cover - CPython-Interna nicht verfügbar
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
    except Exception:  # pragma: no cover - unerwartete AST-Form → nur Längen-Schranke
        return False


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
    # Kostenpositionen: Liste von Positionen mit je ≥ minOffers Vergleichsangeboten;
    # genau eines bevorzugt → dessen Wert = Positionswert; Σ Positionen = amount.
    "positions",
    # Abschnitts-Marker (mehrstufige Formulare): trägt nur ein Label und trennt die
    # folgenden Felder in einen neuen Schritt. Kein Antwortwert, keine Validierung.
    "section",
]
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
    # `positions`: Mindestzahl Vergleichsangebote je Position bzw. Mindestzahl Positionen.
    min_offers: int | None = Field(default=None, alias="minOffers", ge=1)
    min_positions: int | None = Field(default=None, alias="minPositions", ge=1)
    # `positions`: Höchstzahl Positionen bzw. Vergleichsangebote je Position. Auch ohne
    # Builder-Wert greift in der Engine eine Default-Decke (#sec-audit AUD-047), damit die
    # Validierung/`positions_total` nicht allein vom Body-Cap begrenzt werden.
    max_positions: int | None = Field(default=None, alias="maxPositions", ge=1)
    max_offers: int | None = Field(default=None, alias="maxOffers", ge=1)

    @field_validator("pattern")
    @classmethod
    def _check_pattern(cls, v: str | None) -> str | None:
        """Pattern beim Speichern gegen ReDoS absichern (#sec-audit): Länge begrenzen
        und katastrophale Backtracking-Formen ablehnen — das Pattern läuft sonst synchron
        gegen (auch anonyme) Antwort-Eingabe ohne Timeout.

        Die **Kompilierbarkeit** prüfen weiterhin ``validate_definition`` (Form-Speichern)
        und die Antwort-Laufzeit (defensives 422) — hier NICHT, damit bereits gespeicherte
        Formulare ladbar bleiben und der Vertrag der bestehenden Schichten erhalten bleibt."""
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


# --------------------------------------------------------------------------- #
# 5.2 Flow-Graph
# --------------------------------------------------------------------------- #
StateKind = Literal["normal", "vote"]
TransitionBranch = Literal["pass", "fail"]


class StateDef(_CamelModel):
    key: str = Field(pattern=KEY_PATTERN)
    label: I18nMap
    color: str | None = None
    edit_allowed: bool = Field(default=True, alias="editAllowed")
    is_initial: bool = Field(default=False, alias="isInitial")
    # Endzustand (#PII-Re-Add): terminale Anträge sind aufbewahrungs-/anonymisierbar.
    is_terminal: bool = Field(default=False, alias="isTerminal")
    # Global-Flow-Redesign (#28): State-Art + Konfiguration (vote/approval/decision).
    kind: StateKind = "normal"
    config: dict[str, Any] = Field(default_factory=dict)


class TransitionDef(_CamelModel):
    from_: str = Field(alias="from")
    to: str
    label: I18nMap | None = None
    # Optionale Farbe (#flow): Pfeil im Editor + Entscheidungs-Button im Antrag.
    color: str | None = None
    guard: dict[str, Any] | None = None
    actions: list[dict[str, Any]] = Field(default_factory=list)
    order: int | None = None
    # Automatischer Übergang (#8): vom Worker gefeuert, sobald der Guard erfüllt ist.
    automatic: bool = False
    # Ergebnis-Zweig (#28) für vote/approval-States: pass/fail bzw. accept/reject.
    branch: TransitionBranch | None = None
    # »Erfordert Aktion« (#requires-action): zählt der feuerbare Übergang als offene
    # Aufgabe des Akteurs (Tasks-Tab)? ``False`` = rein optionale Aktion.
    requires_action: bool = Field(default=True, alias="requiresAction")


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

    kind_by_key = {s.key: s.kind for s in states}
    for t in graph.transitions:
        if t.from_ not in key_set:
            raise FlowValidationError(f"transition references unknown from-state: {t.from_!r}")
        if t.to not in key_set:
            raise FlowValidationError(f"transition references unknown to-state: {t.to!r}")
        # Self-Loops sind nicht unterstützt: das optimistische Locking der Engine
        # (``WHERE current_state_id = from_state``) kann konkurrierende Doppel-Feuerungen
        # eines from==to-Übergangs nicht erkennen (doppelte Events/Actions).
        if t.from_ == t.to:
            raise FlowValidationError(
                f"transition {t.from_!r} -> {t.to!r}: self-loops are not supported"
            )
        try:
            # Akteur-Gates (roleIs/isInCommittee) nur auf **manuellen** Übergängen.
            validate_guard(t.guard, allow_actor_ops=not t.automatic)
            for action in t.actions:
                validate_action(action)
                # ``addToNextSession`` darf nur in einen ``vote``-State führen (#28).
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
    """``vote``-States strukturell prüfen (#28-Redesign — nur noch normal + vote).

    ``vote`` — ``config.gremiumId`` Pflicht; genau 2 Ausgänge ``pass``/``fail``.
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
            # Einen vote-State entscheidet AUSSCHLIESSLICH die Abstimmung (pass/fail)
            # bzw. ein bewusster MANUELLER Abbruch (#abort-vote). Ein automatischer
            # Nicht-Branch-Ausgang würde vom Worker sofort gefeuert, sobald sein
            # Guard greift — der Antrag wäre „angenommen", ohne dass je abgestimmt
            # wurde (#vote-bypass).
            for t in outgoing[s.key]:
                if t.automatic and not t.branch:
                    raise FlowValidationError(
                        f"vote state {s.key!r} must not have automatic outgoing "
                        "transitions — only the vote outcome (pass/fail) or a "
                        "manual exit may leave it"
                    )
        elif branches:
            # Branch-Übergänge feuert nur das Vote-Ergebnis — auf einem normal-State
            # wären sie weder manuell noch automatisch erreichbar (tote Kanten).
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
    """Im **automatischen** Teilgraphen darf es keinen Zyklus geben (#auto-cycle).

    Eine guard-lose ``automatic``-Transition feuert der Minuten-Cron sofort. Zwei
    normale States A,B mit je einem automatischen Übergang zum anderen bestehen die
    Erreichbarkeits-Prüfung, würden aber pro Cron-Lauf endlos hin- und herspringen —
    je Hop ein StatusEvent + Audit-Row + Mailversand (Mailbomb / Audit-Bloat). Die
    Selbst-Loops fängt bereits die from==to-Regel ab; hier verbleiben Zyklen über
    ≥2 States. DFS über die automatischen Kanten, Back-Edge ⇒ Zyklus.
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
        name: model.model_json_schema(by_alias=True) for name, model in _exported_models().items()
    }
