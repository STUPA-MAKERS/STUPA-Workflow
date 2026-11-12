"""Unit: the feature switches, their uses and the route table.

§F/administration/admin/000756: each feature is on without an entry.
§F/administration/admin/000760: `Rechnungen` is off while `Budget` is off and keeps its
stored switch.
§F/administration/admin/000761: the uses of a feature by the flow and the Antragsarten.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.feature_routes import features_of_route
from app.modules.site_config.branding import Branding, PublicBranding
from app.modules.site_config.feature_uses import FeatureUse, flow_uses, type_uses, uses_of
from app.modules.site_config.features import (
    ALL_FEATURES,
    Feature,
    FeatureDisabledError,
    FeatureSwitches,
    enabled_features,
    switches_of,
)
from app.shared.config_schemas import FlowGraph


def test_a_configuration_without_feature_entries_reads_each_feature_on() -> None:
    assert enabled_features(switches_of(None)) == ALL_FEATURES
    assert enabled_features(Branding.model_validate({}).features) == ALL_FEATURES
    assert enabled_features(switches_of({"tickets": False})) == ALL_FEATURES - {Feature.TICKETS}


def test_an_unknown_feature_key_is_refused() -> None:
    with pytest.raises(ValidationError):
        FeatureSwitches.model_validate({"wiki": False})


def test_invoices_are_off_while_budget_is_off_and_keep_their_switch() -> None:
    switches = FeatureSwitches(budget=False)
    assert switches.invoices is True
    assert enabled_features(switches) == ALL_FEATURES - {Feature.BUDGET, Feature.INVOICES}
    back_on = switches.model_copy(update={"budget": True})
    assert Feature.INVOICES in enabled_features(back_on)


def test_the_public_branding_leaves_the_stored_switches_out() -> None:
    dumped = PublicBranding.model_validate({"features": {"todos": False}}).model_dump(
        by_alias=True
    )
    assert "features" not in dumped


def test_the_error_names_the_features_and_the_code() -> None:
    err = FeatureDisabledError(frozenset({Feature.VOTING, Feature.MEETINGS}))
    assert (err.status, err.code) == (404, "feature_disabled")
    assert "meetings, voting" in (err.detail or "")


def _graph() -> FlowGraph:
    return FlowGraph.model_validate(
        {
            "states": [
                {"key": "eingang", "label": {"de": "Eingang"}, "isInitial": True},
                {
                    "key": "abstimmung",
                    "label": {"en": "Vote"},
                    "kind": "vote",
                    "config": {"gremiumSource": "budget"},
                },
                {"key": "wahl", "label": {}, "kind": "vote", "config": {"gremiumId": "x"}},
                {"key": "ende", "label": {"de": "Ende"}},
            ],
            "transitions": [
                {
                    "from": "eingang",
                    "to": "abstimmung",
                    "actions": [
                        {"type": "assignBudget"},
                        {"type": "addToNextSession"},
                        {"type": "notify"},
                    ],
                },
                {"from": "abstimmung", "to": "ende", "branch": "pass"},
            ],
        }
    )


def test_the_flow_uses_name_states_and_transitions() -> None:
    assert flow_uses(_graph()) == (
        FeatureUse(Feature.VOTING, "state", "Vote"),
        FeatureUse(Feature.BUDGET, "state", "Vote"),
        FeatureUse(Feature.VOTING, "state", "wahl"),
        FeatureUse(Feature.MEETINGS, "transition", "Eingang → Vote"),
        FeatureUse(Feature.BUDGET, "transition", "Eingang → Vote"),
    )
    assert flow_uses(None) == ()


def test_the_type_uses_name_each_type_with_a_budget() -> None:
    assert type_uses([{"de": "Finanzantrag"}, None]) == (
        FeatureUse(Feature.BUDGET, "type", "Finanzantrag"),
        FeatureUse(Feature.BUDGET, "type", "?"),
    )


def test_uses_of_keeps_the_uses_of_the_given_features() -> None:
    uses = flow_uses(_graph())
    assert uses_of(uses, frozenset({Feature.MEETINGS})) == (
        FeatureUse(Feature.MEETINGS, "transition", "Eingang → Vote"),
    )
    assert uses_of(uses, frozenset()) == ()
    assert uses[0].as_error() == {"field": "voting", "msg": "state:Vote"}


@pytest.mark.parametrize(
    ("template", "features"),
    [
        ("/api/todos/boards/{board_id}", {Feature.TODOS}),
        ("/api/ws/todos", {Feature.TODOS}),
        ("/api/calendar/{token}.ics", {Feature.CALENDAR}),
        ("/api/admin/calendars", {Feature.CALENDAR}),
        ("/api/public/calendar.ics", {Feature.CALENDAR}),
        ("/api/meetings", {Feature.MEETINGS}),
        ("/api/ws/meetings/{meeting_id}/projector", {Feature.MEETINGS}),
        ("/api/public/meetings/{code}", {Feature.MEETINGS}),
        ("/api/public/protocols/{protocol_id}/images/{image_id}", {Feature.MEETINGS}),
        ("/api/public/committees", {Feature.MEETINGS}),
        ("/api/delegations/substitutes", {Feature.MEETINGS}),
        ("/api/admin/meeting-settings", {Feature.MEETINGS}),
        ("/api/committees/{gremium_id}/meeting-defaults", {Feature.MEETINGS}),
        ("/api/committees/{gremium_id}/attendance/{principal_id}", {Feature.MEETINGS}),
        ("/api/votes/{vote_id}/ballot", {Feature.VOTING}),
        ("/api/applications/{application_id}/votes", {Feature.VOTING}),
        ("/api/meetings/{meeting_id}/votes/{vote_id}/open", {Feature.MEETINGS, Feature.VOTING}),
        ("/api/public/meetings/{code}/votes", {Feature.MEETINGS, Feature.VOTING}),
        ("/api/protocols/{protocol_id}/votes", {Feature.MEETINGS, Feature.VOTING}),
        ("/api/delegations/votes/{vote_id}", {Feature.MEETINGS, Feature.VOTING}),
        ("/api/budgets/{budget_id}/fiscal-years", {Feature.BUDGET}),
        ("/api/budget/export.xlsx", {Feature.BUDGET}),
        ("/api/budget-expenses/{expense_id}", {Feature.BUDGET}),
        ("/api/budget-transfers", {Feature.BUDGET}),
        ("/api/expenses/export.xlsx", {Feature.BUDGET}),
        ("/api/applications/{application_id}/assign-budget", {Feature.BUDGET}),
        ("/api/invoices/{invoice_id}/file", {Feature.INVOICES}),
        ("/api/tickets/mine", {Feature.TICKETS}),
        ("/api/applications/{application_id}", set()),
        ("/api/applications/{application_id}/transition", set()),
        ("/api/committees/{gremium_id}/decisions", {Feature.VOTING}),
        ("/api/committees/{gremium_id}/members", set()),
        ("/api/committees", set()),
        ("/api/admin/features", set()),
        ("/api/admin/help-tickets", set()),
        ("/api/site-config", set()),
        ("/api/search", set()),
        ("", set()),
    ],
)
def test_the_route_table_names_the_features_of_a_route(
    template: str, features: set[Feature]
) -> None:
    assert features_of_route(template) == features


def test_every_route_of_the_app_is_in_the_expected_feature() -> None:
    """Each route of the app maps to the feature that its first path segment names.

    A new route under a known segment gets the gate without a new entry, and a new
    segment shows up here.
    """
    from app.main import create_app

    by_feature = {
        feature: sorted(
            path for path in create_app().openapi()["paths"] if feature in features_of_route(path)
        )
        for feature in Feature
    }
    assert all(by_feature.values())
    assert all(p.startswith("/api/invoices") for p in by_feature[Feature.INVOICES])
    assert all(p.startswith("/api/tickets") for p in by_feature[Feature.TICKETS])
    assert all(
        p.startswith(("/api/todos", "/api/ws/todos")) for p in by_feature[Feature.TODOS]
    )
