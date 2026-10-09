"""Tests of the decision placeholders of a status mail (F1)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.flow.dispatch import DispatchedAction
from app.modules.notifications import service as svc
from app.modules.notifications import templates_catalogue as cat
from app.modules.notifications.action_dispatcher import _decision_context
from app.modules.notifications.templating import _render_str
from tests._support.notifications_fakes import FakeSession


def _action() -> DispatchedAction:
    app_id = uuid.uuid4()
    return DispatchedAction(
        type="notify",
        application_id=app_id,
        transition_id=uuid.uuid4(),
        status_event_id=uuid.uuid4(),
        idempotency_key=f"{app_id}:se:0:notify",
    )


async def _ctx(row: tuple | None, lang: str = "de") -> dict[str, object]:
    session = FakeSession(executes=[[row] if row is not None else []])
    return await _decision_context(cast("AsyncSession", session), _action(), lang)


async def test_no_row_gives_empty_defaults() -> None:
    ctx = await _ctx(None)
    assert ctx == {
        "requestedAmount": "",
        "approvedAmount": "",
        "amountDeviates": False,
        "conditions": [],
    }


async def test_decision_of_the_event_with_deviation() -> None:
    row = (Decimal("1000"), "EUR", Decimal("800"), Decimal("800"), ["Belege", 3])
    ctx = await _ctx(row)
    assert ctx["requestedAmount"] == "1.000,00 €"
    assert ctx["approvedAmount"] == "800,00 €"
    assert ctx["amountDeviates"] is True
    assert ctx["conditions"] == ["Belege"]


async def test_later_status_mail_uses_valid_amount_without_block() -> None:
    row = (Decimal("1000"), None, Decimal("800"), None, None)
    ctx = await _ctx(row, "en")
    assert ctx["approvedAmount"] == "€800.00"
    assert ctx["amountDeviates"] is False
    assert ctx["conditions"] == []


async def test_no_decision_shows_requested_amount() -> None:
    row = (Decimal("50"), "EUR", None, None, None)
    ctx = await _ctx(row)
    assert ctx["approvedAmount"] == "50,00 €"


@pytest.mark.parametrize("lang", ["de", "en"])
def test_builtin_bodies_render_without_decision_keys(lang: str) -> None:
    for body in (svc._BUILTIN_NOTIFY_BODY, cat.STATUS_UPDATE_TEAM_BODY):
        out = _render_str(body[lang], {"applicationTitle": "T", "status": "S"}, html=False)
        assert "Abweichungen" not in out
        assert "deviations" not in out


def test_builtin_body_renders_the_deviation_block() -> None:
    ctx = {
        "applicationTitle": "T",
        "status": "Genehmigt",
        "requestedAmount": "1.000,00 €",
        "approvedAmount": "800,00 €",
        "amountDeviates": True,
        "conditions": ["Belege nachreichen"],
    }
    out = _render_str(svc._BUILTIN_NOTIFY_BODY["de"], ctx, html=False)
    assert "Der Antrag wurde mit Abweichungen genehmigt." in out
    assert "Bewilligt: 800,00 €" in out
    assert "- Belege nachreichen" in out


def test_builtin_body_conditions_only() -> None:
    ctx = {
        "applicationTitle": "T",
        "status": "Approved",
        "requestedAmount": "€1.00",
        "approvedAmount": "€1.00",
        "amountDeviates": False,
        "conditions": ["Report"],
    }
    out = _render_str(cat.STATUS_UPDATE_TEAM_BODY["en"], ctx, html=False)
    assert "approved with deviations" in out
    assert "Approved: " not in out
    assert "- Report" in out


def test_catalogue_lists_the_decision_placeholders() -> None:
    specs = {s.key: s for s in cat.TEMPLATE_CATALOGUE}
    for key in ("status_update", "status_update_team"):
        assert {"requestedAmount", "approvedAmount", "amountDeviates", "conditions"} <= set(
            specs[key].placeholders
        )
