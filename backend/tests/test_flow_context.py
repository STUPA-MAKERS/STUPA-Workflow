"""TDD: Guard-Kontext-Aufbau der Flow-Engine (T-14, flows §9.2)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from app.modules.flow import context as flow_context
from tests.flow_fakes import fake_session, result


def _field(**over: object) -> SimpleNamespace:
    base = {
        "key": "title",
        "type": "text",
        "label_i18n": {"de": "Titel"},
        "help_i18n": None,
        "required": True,
        "validation": None,
        "visible_if": None,
        "compute": None,
        "options": None,
        "is_pii": False,
        "is_promoted": False,
        "promote_target": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _app(**over: object) -> Application:
    base = {
        "form_version_id": uuid4(),
        "budget_pot_id": None,
        "type_id": uuid4(),
        "data": {"title": "Mein Antrag"},
    }
    base.update(over)
    return cast("Application", SimpleNamespace(**base))


# --------------------------------------------------------------------------- #
# fields_complete
# --------------------------------------------------------------------------- #
async def test_fields_complete_true_when_required_present() -> None:
    db = fake_session(
        result(_field()),  # form_field-Zeilen
        result(SimpleNamespace(has_budget=False)),  # application_type
    )
    assert await flow_context.fields_complete(db, _app()) is True


async def test_fields_complete_false_when_required_missing() -> None:
    db = fake_session(
        result(_field()),
        result(SimpleNamespace(has_budget=False)),
    )
    assert await flow_context.fields_complete(db, _app(data={})) is False


async def test_fields_complete_app_type_missing_defaults_no_budget() -> None:
    db = fake_session(
        result(_field()),
        result(),  # kein application_type → has_budget=False
    )
    assert await flow_context.fields_complete(db, _app()) is True


async def test_fields_complete_merges_budget_pot_fields() -> None:
    pot_field = {
        "key": "receipt",
        "type": "text",
        "label": {"de": "Beleg"},
        "required": True,
    }
    db = fake_session(
        result(_field()),  # form_field
        result(SimpleNamespace(field=pot_field)),  # budget_field (Topf)
        result(SimpleNamespace(has_budget=True)),  # application_type
    )
    app = _app(budget_pot_id=uuid4(), data={"title": "x"})  # receipt fehlt
    assert await flow_context.fields_complete(db, app) is False


# --------------------------------------------------------------------------- #
# build_context
# --------------------------------------------------------------------------- #
def test_build_context_maps_principal_and_signals() -> None:
    principal = Principal(
        sub="u-1", roles=["chair"], permissions={"application.manage"}
    )
    ctx = flow_context.build_context(
        principal,
        fields_complete=True,
        vote_result="passed",
        deadline_passed=True,
        manual=False,
    )
    assert ctx.roles == frozenset({"chair"})
    assert ctx.permissions == frozenset({"application.manage"})
    assert ctx.fields_complete is True
    assert ctx.vote_result == "passed"
    assert ctx.deadline_passed is True
    assert ctx.manual is False
