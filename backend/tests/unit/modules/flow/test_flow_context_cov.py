"""Branch-complete unit suite for `app.modules.flow.context`, without a DB.

It covers the guard context assembly (`build_context` and its helpers). Every test is
deterministic. The result-queue fake needs no Docker, Redis or Postgres.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from app.deps import Principal
from app.modules.flow import context as flow_context
from app.modules.flow.context import (
    _budget_fits,
    _compare_type,
    _field_types,
    build_context,
    committee_ids_for_sub,
)
from app.shared.guards import GuardContext
from tests._support.flow_fakes import fake_session, result


@pytest.mark.parametrize(
    ("field_type", "expected"),
    [
        ("number", "number"),
        ("currency", "currency"),
        ("date", "date"),
        ("checkbox", "bool"),
        ("boolean", "bool"),
        ("text", "text"),
        ("freitext-unknown", "text"),
    ],
)
def test_compare_type_mapping(field_type: str, expected: str) -> None:
    assert _compare_type(field_type) == expected


async def testcommittee_ids_for_sub_empty_sub_short_circuits() -> None:
    """Return an empty set for a falsy sub without a DB read."""
    session = fake_session()
    assert await committee_ids_for_sub(session, None) == frozenset()
    assert await committee_ids_for_sub(session, "") == frozenset()
    assert session.statements == []


async def testcommittee_ids_for_sub_maps_rows_to_str() -> None:
    g1, g2 = uuid4(), uuid4()
    session = fake_session(result(g1, g2))
    out = await committee_ids_for_sub(session, "sub-1")
    assert out == frozenset({str(g1), str(g2)})


def _app_for_budget(*, budget_id: Any, fiscal: Any, amount: Any) -> SimpleNamespace:
    return SimpleNamespace(budget_id=budget_id, fiscal_year_id=fiscal, amount=amount)


async def test_budget_fits_fail_closed_when_budget_missing() -> None:
    session = fake_session()
    app = _app_for_budget(budget_id=None, fiscal=uuid4(), amount=Decimal("10"))
    assert await _budget_fits(session, cast("Any", app)) is False


async def test_budget_fits_fail_closed_when_fiscal_missing() -> None:
    session = fake_session()
    app = _app_for_budget(budget_id=uuid4(), fiscal=None, amount=Decimal("10"))
    assert await _budget_fits(session, cast("Any", app)) is False


async def test_budget_fits_fail_closed_when_amount_missing() -> None:
    session = fake_session()
    app = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=None)
    assert await _budget_fits(session, cast("Any", app)) is False


async def test_budget_fits_true_when_amount_within_available() -> None:
    """Fit an amount within the available 80 (allocated 100, flow -20)."""
    session = fake_session()
    session.scalar_results = [Decimal("100"), Decimal("-20")]
    app = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=Decimal("80"))
    assert await _budget_fits(session, cast("Any", app)) is True


async def test_budget_fits_false_when_amount_exceeds_available() -> None:
    """Refuse an amount above the available 80."""
    session = fake_session()
    session.scalar_results = [Decimal("100"), Decimal("-20")]
    app = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=Decimal("80.01"))
    assert await _budget_fits(session, cast("Any", app)) is False


async def test_budget_fits_handles_none_allocated_and_flow() -> None:
    """Treat a None allocation and a None flow as 0, so 0 fits and 0.01 does not."""
    session = fake_session()
    app = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=Decimal("0"))
    assert await _budget_fits(session, cast("Any", app)) is True
    session2 = fake_session()
    app2 = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=Decimal("0.01"))
    assert await _budget_fits(session2, cast("Any", app2)) is False


async def test_field_types_maps_and_adds_amount() -> None:
    """Map the field types and always add the built-in `amount`."""
    rows = [("betrag", "currency"), ("titel", "text"), ("anzahl", "number"), ("ok", "checkbox")]
    session = fake_session(result(*rows))
    app = SimpleNamespace(form_version_id=uuid4())
    out = await _field_types(session, cast("Any", app))
    assert out == {
        "betrag": "currency",
        "titel": "text",
        "anzahl": "number",
        "ok": "bool",
        "amount": "currency",
    }


def _ctx_app(
    *,
    data: Any,
    created_by: str | None,
    budget_id: Any = None,
    amount: Any = Decimal("5"),
    fiscal: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        created_by=created_by,
        budget_id=budget_id,
        vote_gremium_id=None,
        fiscal_year_id=fiscal,
        amount=amount,
        form_version_id=uuid4(),
        id=uuid4(),
        type_id=uuid4(),
    )


@pytest.fixture(autouse=True)
def _ctx_extras_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the context helpers `_application_type_key` and `_has_attachment`.

    The stubs keep the tests free of a DB. `test_flow_context` covers the real bodies.
    This fixture does nothing for the tests in this file that build no context.
    """

    async def _atk(_session: object, _app: object) -> str | None:
        return None

    async def _ha(_session: object, _app: object) -> bool:
        return False

    monkeypatch.setattr(flow_context, "_application_type_key", _atk)
    monkeypatch.setattr(flow_context, "_has_attachment", _ha)


def _principal(**over: object) -> Principal:
    base: dict[str, object] = {"sub": "actor-1", "roles": ["chair"], "permissions": set()}
    base.update(over)
    return Principal(**base)  # type: ignore[arg-type]


@pytest.fixture
def _no_committees(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `committee_ids_for_sub` return frozenset() without a DB."""

    async def _cs(_session: object, _sub: str | None) -> frozenset[str]:
        return frozenset()

    monkeypatch.setattr(flow_context, "committee_ids_for_sub", _cs)


@pytest.fixture
def _no_field_types(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ft(_session: object, _app: object) -> dict[str, str]:
        return {"amount": "currency"}

    monkeypatch.setattr(flow_context, "_field_types", _ft)


@pytest.fixture
def _budget_no_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _bf(_session: object, _app: object) -> bool:
        return False

    monkeypatch.setattr(flow_context, "_budget_fits", _bf)


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_manual_actor_is_creator() -> None:
    """Mark the creator as applicant on a manual fire; the roles come from the principal."""
    app = _ctx_app(
        data={"_applicantRoles": ["member"], "feld": 1},
        created_by="actor-1",
        budget_id=uuid4(),
    )
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert isinstance(ctx, GuardContext)
    assert ctx.manual is True
    assert ctx.actor_is_applicant is True
    assert ctx.roles == frozenset({"chair"})
    assert ctx.applicant_roles == frozenset({"member"})
    assert ctx.budget_id == str(app.budget_id)
    assert ctx.field_values["amount"] == app.amount
    assert ctx.field_values["feld"] == 1
    assert ctx.budget_fits is False


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_manual_as_applicant_magic_link() -> None:
    """Mark the magic-link applicant as applicant when the creator differs."""
    app = _ctx_app(data={}, created_by="someone-else")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True, as_applicant=True
    )
    assert ctx.actor_is_applicant is True


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_manual_not_applicant() -> None:
    """Do not mark a foreign actor without a magic link."""
    app = _ctx_app(data={}, created_by="someone-else")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert ctx.actor_is_applicant is False


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_manual_created_by_none() -> None:
    """Do not mark the actor when the application has no creator."""
    app = _ctx_app(data={}, created_by=None)
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert ctx.actor_is_applicant is False


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_automatic_strips_actor_signals() -> None:
    """Leave the roles and the actor committees empty on an automatic fire.

    The manual gate also blocks actor_is_applicant. A budget_id of None stays None.
    """
    app = _ctx_app(data={"_applicantRoles": ["x"]}, created_by="actor-1", budget_id=None)
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=False, as_applicant=True
    )
    assert ctx.manual is False
    assert ctx.roles == frozenset()
    assert ctx.actor_committees == frozenset()
    assert ctx.actor_is_applicant is False
    assert ctx.budget_id is None


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_data_not_dict_and_roles_not_list() -> None:
    """Start with empty field values for non-dict data and empty roles for None."""
    app = _ctx_app(data=None, created_by="actor-1")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert ctx.applicant_roles == frozenset()
    assert ctx.field_values == {"amount": app.amount}


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_applicant_roles_present_but_not_list() -> None:
    """Leave the applicant roles empty when `_applicantRoles` is not a list."""
    app = _ctx_app(data={"_applicantRoles": "not-a-list"}, created_by="actor-1")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert ctx.applicant_roles == frozenset()


@pytest.mark.usefixtures("_no_field_types", "_budget_no_fit")
async def test_build_context_committees_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _cs(_session: object, _sub: str | None) -> frozenset[str]:
        return frozenset({"g-1"})

    monkeypatch.setattr(flow_context, "committee_ids_for_sub", _cs)
    app = _ctx_app(data={}, created_by="actor-1")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert ctx.actor_committees == frozenset({"g-1"})
    assert ctx.applicant_committees == frozenset({"g-1"})
