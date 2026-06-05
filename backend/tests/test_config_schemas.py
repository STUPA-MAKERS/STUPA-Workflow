"""TDD: Config-Schemas + Flow-Graph-Validierung + JSON-Schema-Export (data-model §5)."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.shared.config_schemas import (
    BudgetField,
    ComparisonOffers,
    FlowGraph,
    FlowValidationError,
    FormFieldDef,
    NotificationRule,
    Quorum,
    VoteConfig,
    WebhookConfig,
    export_json_schemas,
    validate_flow_graph,
)


# --------------------------------------------------------------------------- #
# Form-Definition
# --------------------------------------------------------------------------- #
def test_form_field_minimal() -> None:
    f = FormFieldDef(key="title", type="text", label={"de": "Titel"})
    assert f.key == "title"
    assert f.required is False


def test_form_field_camel_alias_roundtrip() -> None:
    raw = {
        "key": "amount",
        "type": "currency",
        "label": {"de": "Betrag"},
        "isPromoted": True,
        "promoteTarget": "amount",
        "isPII": False,
        "visibleIf": {"==": [{"var": "has_budget"}, True]},
    }
    f = FormFieldDef.model_validate(raw)
    assert f.is_promoted is True
    assert f.promote_target == "amount"
    dumped = f.model_dump(by_alias=True, exclude_none=True)
    assert dumped["isPromoted"] is True
    assert dumped["promoteTarget"] == "amount"
    assert "visibleIf" in dumped
    assert FormFieldDef.model_validate(dumped) == f


def test_form_field_bad_key_rejected() -> None:
    with pytest.raises(ValidationError):
        FormFieldDef(key="Title", type="text", label={"de": "x"})
    with pytest.raises(ValidationError):
        FormFieldDef(key="1abc", type="text", label={"de": "x"})


def test_form_field_promoted_requires_target() -> None:
    with pytest.raises(ValidationError):
        FormFieldDef.model_validate(
            {"key": "a", "type": "number", "label": {"de": "x"}, "isPromoted": True}
        )


def test_form_field_select_requires_options() -> None:
    with pytest.raises(ValidationError):
        FormFieldDef(key="a", type="select", label={"de": "x"})
    f = FormFieldDef(
        key="a",
        type="select",
        label={"de": "x"},
        options=[{"value": "a", "label": {"de": "A"}}],  # type: ignore[list-item]
    )
    assert f.options is not None


def test_form_field_computed_requires_compute() -> None:
    with pytest.raises(ValidationError):
        FormFieldDef(key="a", type="computed", label={"de": "x"})
    f = FormFieldDef(
        key="total",
        type="computed",
        label={"de": "Summe"},
        compute={"*": [{"var": "qty"}, {"var": "unit_price"}]},
    )
    assert f.compute is not None


def test_form_field_rejects_bad_jsonlogic() -> None:
    with pytest.raises(ValidationError):
        FormFieldDef.model_validate(
            {"key": "a", "type": "text", "label": {"de": "x"}, "visibleIf": {"system": ["rm"]}}
        )


def test_form_field_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        FormFieldDef.model_validate(
            {"key": "a", "type": "text", "label": {"de": "x"}, "bogus": 1}
        )


# --------------------------------------------------------------------------- #
# Flow-Graph-Validierung
# --------------------------------------------------------------------------- #
def _valid_graph_dict() -> dict:
    return {
        "states": [
            {"key": "draft", "label": {"de": "Entwurf"}, "category": "open", "isInitial": True},
            {"key": "review", "label": {"de": "Prüfung"}, "category": "running"},
            {"key": "approved", "label": {"de": "Bewilligt"}, "category": "closed"},
        ],
        "transitions": [
            {
                "from": "draft",
                "to": "review",
                "guard": {"and": [{"fieldsComplete": True}, {"roleIs": "applicant"}]},
                "actions": [{"type": "notify", "group": "gremium"}, {"type": "setEditLock"}],
            },
            {"from": "review", "to": "approved", "guard": {"voteResult": "passed"}},
        ],
    }


def test_valid_flow_graph_passes() -> None:
    graph = FlowGraph.model_validate(_valid_graph_dict())
    validate_flow_graph(graph)  # no raise


def test_flow_graph_from_alias_parsed() -> None:
    graph = FlowGraph.model_validate(_valid_graph_dict())
    assert graph.transitions[0].from_ == "draft"


def test_flow_no_initial() -> None:
    g = _valid_graph_dict()
    g["states"][0]["isInitial"] = False
    graph = FlowGraph.model_validate(g)
    with pytest.raises(FlowValidationError, match="no initial state"):
        validate_flow_graph(graph)


def test_flow_two_initials() -> None:
    g = _valid_graph_dict()
    g["states"][1]["isInitial"] = True
    graph = FlowGraph.model_validate(g)
    with pytest.raises(FlowValidationError, match="multiple initial"):
        validate_flow_graph(graph)


def test_flow_dangling_to_ref() -> None:
    g = _valid_graph_dict()
    g["transitions"][0]["to"] = "ghost"
    graph = FlowGraph.model_validate(g)
    with pytest.raises(FlowValidationError, match="unknown to-state"):
        validate_flow_graph(graph)


def test_flow_dangling_from_ref() -> None:
    g = _valid_graph_dict()
    g["transitions"][0]["from"] = "ghost"
    graph = FlowGraph.model_validate(g)
    with pytest.raises(FlowValidationError, match="unknown from-state"):
        validate_flow_graph(graph)


def test_flow_unknown_action_type() -> None:
    g = _valid_graph_dict()
    g["transitions"][0]["actions"] = [{"type": "wipeDb"}]
    graph = FlowGraph.model_validate(g)
    with pytest.raises(FlowValidationError, match="unknown action type"):
        validate_flow_graph(graph)


def test_flow_unknown_guard_operator() -> None:
    g = _valid_graph_dict()
    g["transitions"][0]["guard"] = {"isBoss": True}
    graph = FlowGraph.model_validate(g)
    with pytest.raises(FlowValidationError, match="unknown guard operator"):
        validate_flow_graph(graph)


def test_flow_unreachable_state() -> None:
    g = _valid_graph_dict()
    g["transitions"] = [g["transitions"][0]]  # approved no longer reachable
    graph = FlowGraph.model_validate(g)
    with pytest.raises(FlowValidationError, match="unreachable"):
        validate_flow_graph(graph)


def test_flow_duplicate_keys() -> None:
    g = _valid_graph_dict()
    g["states"][1]["key"] = "draft"
    graph = FlowGraph.model_validate(g)
    with pytest.raises(FlowValidationError, match="duplicate"):
        validate_flow_graph(graph)


def test_flow_no_states() -> None:
    graph = FlowGraph(states=[])
    with pytest.raises(FlowValidationError, match="no states"):
        validate_flow_graph(graph)


def test_flow_diamond_reconverges_ok() -> None:
    # Zwei Pfade münden in denselben State → BFS besucht ihn doppelt (revisit).
    g = {
        "states": [
            {"key": "draft", "label": {"de": "E"}, "isInitial": True},
            {"key": "a", "label": {"de": "A"}},
            {"key": "b", "label": {"de": "B"}},
            {"key": "done", "label": {"de": "D"}},
        ],
        "transitions": [
            {"from": "draft", "to": "a"},
            {"from": "draft", "to": "b"},
            {"from": "a", "to": "done"},
            {"from": "b", "to": "done"},
        ],
    }
    validate_flow_graph(FlowGraph.model_validate(g))  # no raise


def test_form_field_explicit_none_jsonlogic_ok() -> None:
    f = FormFieldDef.model_validate(
        {"key": "a", "type": "text", "label": {"de": "x"}, "visibleIf": None, "compute": None}
    )
    assert f.visible_if is None


# --------------------------------------------------------------------------- #
# Voting-Regeln
# --------------------------------------------------------------------------- #
def test_vote_config_defaults_and_alias() -> None:
    v = VoteConfig.model_validate(
        {"options": ["yes", "no", "abstain"], "majorityRule": "two_thirds",
         "quorum": {"type": "count", "value": 7}}
    )
    assert v.majority_rule == "two_thirds"
    assert v.tie_break == "rejected"
    assert v.quorum == Quorum(type="count", value=7)
    assert v.model_dump(by_alias=True)["abstainCountsQuorum"] is True


def test_vote_config_too_few_options() -> None:
    with pytest.raises(ValidationError):
        VoteConfig.model_validate({"options": ["yes"], "majorityRule": "simple"})


def test_vote_config_duplicate_options() -> None:
    with pytest.raises(ValidationError):
        VoteConfig.model_validate({"options": ["yes", "yes"], "majorityRule": "simple"})


# --------------------------------------------------------------------------- #
# Notification-Regel
# --------------------------------------------------------------------------- #
def test_notification_rule_ok() -> None:
    r = NotificationRule.model_validate(
        {"event": "status_changed",
         "recipients": [{"kind": "group", "ref": "stupa"}, {"kind": "applicant"}],
         "templateKey": "status_update"}
    )
    assert r.enabled is True
    assert r.template_key == "status_update"


def test_notification_recipient_ref_rules() -> None:
    with pytest.raises(ValidationError):
        NotificationRule.model_validate(
            {"event": "status_changed", "recipients": [{"kind": "group"}], "templateKey": "t"}
        )
    with pytest.raises(ValidationError):
        NotificationRule.model_validate(
            {"event": "status_changed",
             "recipients": [{"kind": "applicant", "ref": "x"}], "templateKey": "t"}
        )


def test_notification_unknown_event_rejected() -> None:
    with pytest.raises(ValidationError):
        NotificationRule.model_validate(
            {"event": "meltdown", "recipients": [{"kind": "applicant"}], "templateKey": "t"}
        )


# --------------------------------------------------------------------------- #
# Webhook-Config
# --------------------------------------------------------------------------- #
def test_webhook_config_ok() -> None:
    w = WebhookConfig.model_validate(
        {"name": "buchhaltung", "url": "https://example.org/hook",
         "events": ["application_approved", "budget_booked"]}
    )
    assert w.active is True
    assert str(w.url).startswith("https://")


def test_webhook_requires_event_and_url() -> None:
    with pytest.raises(ValidationError):
        WebhookConfig(name="x", url="https://e.org", events=[])  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        WebhookConfig(name="x", url="not-a-url", events=["budget_booked"])  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Comparison-Offers + Budget-Field
# --------------------------------------------------------------------------- #
def test_comparison_offers_alias() -> None:
    c = ComparisonOffers.model_validate(
        {"required": True, "minCount": 2, "thresholdAmount": "250.00", "as": "file"}
    )
    assert c.min_count == 2
    assert c.threshold_amount == Decimal("250.00")
    assert c.as_ == "file"
    assert c.model_dump(by_alias=True)["as"] == "file"


def test_budget_field_wraps_form_field() -> None:
    bf = BudgetField.model_validate(
        {"field": {"key": "reason", "type": "textarea", "label": {"de": "Begründung"}},
         "order": 3}
    )
    assert bf.field.key == "reason"
    assert bf.order == 3


# --------------------------------------------------------------------------- #
# JSON-Schema-Export
# --------------------------------------------------------------------------- #
def test_export_json_schemas_keys_and_deterministic() -> None:
    schemas = export_json_schemas()
    assert set(schemas) == {
        "FormFieldDef", "FlowGraph", "VoteConfig", "NotificationRule",
        "WebhookConfig", "ComparisonOffers", "BudgetField",
    }
    # deterministisch: zweiter Aufruf identisch
    assert export_json_schemas() == schemas
    # camelCase-Aliase im Schema
    assert "isPromoted" in schemas["FormFieldDef"]["properties"]
