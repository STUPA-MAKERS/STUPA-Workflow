"""Unit tests of the later change of the approved amount (specs 001620-001622).

The integration suite covers the database path of `amend_approved_amount`. These tests
cover the input rules, the mail and the route gate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.modules.applications.amend_mail as mail_mod
import app.modules.applications.amend_router as router_mod
from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.applications.amend import (
    AmendIn,
    AmendOut,
    berlin_today,
    check_amendment,
)
from app.modules.auth.principal import Principal
from app.modules.notifications.templating import TemplateRenderError
from app.settings import load_settings
from app.shared.errors import ValidationProblem

SETTINGS = load_settings()
TODAY = date(2026, 11, 19)


def _payload(**kw: Any) -> AmendIn:
    return AmendIn.model_validate(
        {
            "approvedAmount": "122.00",
            "reason": "  Mehrkosten Druck  ",
            "decisionDate": "2026-11-18",
            "gremiumId": str(uuid.uuid4()),
            **kw,
        }
    )


def test_reason_is_trimmed_and_needs_ten_characters() -> None:
    assert _payload().reason == "Mehrkosten Druck"
    with pytest.raises(ValueError):
        _payload(reason="   kurz    ")


def test_check_allows_an_amount_above_the_request() -> None:
    """§ 001622: a change may exceed the requested amount."""
    check_amendment(_payload(), requested=Decimal("100.00"), old=Decimal("100.00"), today=TODAY)
    check_amendment(_payload(), requested=Decimal("100.00"), old=None, today=TODAY)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"approvedAmount": "100.00"}, "approved_amount_unchanged"),
        ({"approvedAmount": "-1.00"}, "approved_amount_invalid"),
        ({"approvedAmount": "1.001"}, "approved_amount_invalid"),
        ({"decisionDate": "2026-11-20"}, "decision_date_invalid"),
    ],
)
def test_check_refuses(change: dict[str, str], code: str) -> None:
    with pytest.raises(ValidationProblem) as err:
        check_amendment(
            _payload(**change), requested=Decimal("100.00"), old=Decimal("100.00"), today=TODAY
        )
    assert err.value.code == code


def test_berlin_today_crosses_midnight() -> None:
    assert berlin_today(datetime(2026, 11, 19, 23, 30, tzinfo=UTC)) == date(2026, 11, 20)


class _Service:
    template: object = None
    fail = False
    last: _Service | None = None

    def __init__(self, session: object, **_kw: object) -> None:
        self.resolver = SimpleNamespace(resolve=self._resolve)
        self.sent: list[Any] = []
        _Service.last = self

    async def _resolve(self, *_a: object, **_kw: object) -> list[str]:
        return ["a@example.org"]

    async def _get_template_by_key(self, key: str) -> object:
        return self.template

    async def _render_and_enqueue(self, tpl: object, recipients: list[str], **kw: Any) -> bool:
        self.sent.append(("template", kw["context"]))
        return True

    async def render_context(self, context: dict[str, Any]) -> dict[str, Any]:
        return context

    async def _message(self, rendered: Any, *_a: object) -> Any:
        return rendered

    async def _enqueue(self, msg: Any) -> bool:
        self.sent.append(("builtin", msg))
        return True


def _facts(
    found: bool = True, currency: str | None = "EUR", gremium: str | None = "StuPa"
) -> Any:
    """Stub `mail_facts`; the integration suite runs the query on Postgres."""

    async def _read(*_a: object) -> mail_mod.MailFacts | None:
        if not found:
            return None
        return mail_mod.MailFacts(
            data={"title": "Exkursion"}, currency=currency, created_by=None, gremium=gremium
        )

    return _read


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> type[_Service]:
    _Service.template = None
    _Service.last = None
    monkeypatch.setattr(mail_mod, "mail_facts", _facts())

    async def _lang(*_a: object, **_kw: object) -> str:
        return "de"

    async def _keep(_s: object, recipients: list[str], _kind: str) -> list[str]:
        return recipients

    monkeypatch.setattr(mail_mod, "NotificationService", _Service)
    monkeypatch.setattr(mail_mod, "resolve_application_lang", _lang)
    monkeypatch.setattr(mail_mod, "filter_recipients_by_preference", _keep)
    return _Service


async def _send(previous: Decimal | None = Decimal("100.00")) -> int:
    return await mail_mod.send_amount_changed_mail(
        object(),  # type: ignore[arg-type]
        queue=None,
        settings=SETTINGS,
        application_id=uuid.uuid4(),
        previous=previous,
        approved=Decimal("1222.50"),
        gremium_id=uuid.uuid4(),
        decision_date=TODAY,
    )


async def test_mail_names_the_old_and_the_new_amount(service: type[_Service]) -> None:
    """§ 001621: the applicant gets the old and the new amount."""
    assert await _send() == 1
    assert service.last is not None
    kind, rendered = service.last.sent[0]
    assert kind == "builtin"
    assert "Bisher: 100,00 €" in rendered.text
    assert "Neu: 1.222,50 €" in rendered.text
    assert "StuPa" in rendered.text
    assert "19.11.2026" in rendered.text


async def test_mail_uses_a_stored_template(
    service: type[_Service], monkeypatch: pytest.MonkeyPatch
) -> None:
    service.template = object()
    monkeypatch.setattr(mail_mod, "mail_facts", _facts(currency=None, gremium=None))
    assert await _send(previous=None) == 1
    assert service.last is not None
    kind, context = service.last.sent[0]
    assert kind == "template"
    assert context["previousAmount"] == ""
    assert context["gremium"] == ""


async def test_mail_skips_a_missing_application_and_no_recipient(
    service: type[_Service], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mail_mod, "mail_facts", _facts(found=False))
    assert await _send() == 0
    monkeypatch.setattr(mail_mod, "mail_facts", _facts())

    async def _none(*_a: object) -> list[str]:
        return []

    monkeypatch.setattr(mail_mod, "filter_recipients_by_preference", _none)
    assert await _send() == 0


async def test_mail_survives_a_render_error(
    service: type[_Service], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _broken(**_kw: object) -> object:
        raise TemplateRenderError("boom")

    monkeypatch.setattr(mail_mod, "render_mail", _broken)
    assert await _send() == 0


def test_mail_date_in_english() -> None:
    assert mail_mod._date_text(TODAY, "en") == "2026-11-19"


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    async def _read(*_a: object) -> None:
        return None

    monkeypatch.setattr(router_mod, "resolve_app_read", _read)
    application = create_app()
    application.dependency_overrides[get_current_applicant] = lambda: None
    return application


def test_route_needs_its_permission_and_mails(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 001620: the route needs `application.amend_decision`."""
    delivered: list[object] = []

    async def _amend(*_a: object, **_kw: object) -> AmendOut:
        return AmendOut(
            previousAmount=Decimal("1"), approvedAmount=Decimal("2"), decidedAt=datetime.now(UTC)
        )

    async def _deliver(*args: object) -> None:
        delivered.append(args)

    class _Db:
        async def commit(self) -> None:
            return None

    from app.db import get_session

    monkeypatch.setattr(router_mod, "amend_approved_amount", _amend)
    monkeypatch.setattr(router_mod, "_deliver", _deliver)
    app.dependency_overrides[get_session] = lambda: _Db()
    client = TestClient(app)
    url = f"/api/applications/{uuid.uuid4()}/approved-amount"
    body = {
        "approvedAmount": "2.00",
        "reason": "Mehrkosten Druck",
        "decisionDate": "2026-11-18",
        "gremiumId": str(uuid.uuid4()),
    }
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="x", permissions={"application.transition"}
    )
    assert client.post(url, json=body).status_code == 403
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="x", permissions={"application.amend_decision"}
    )
    r = client.post(url, json=body)
    assert r.status_code == 200
    assert r.json()["approvedAmount"] == "2"
    assert len(delivered) == 1


async def test_deliver_opens_its_own_session(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class _Ctx:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_a: object) -> None:
            return None

    async def _send_mail(_db: object, **kw: Any) -> int:
        calls.append(kw)
        return 1

    monkeypatch.setattr(router_mod, "get_sessionmaker", lambda: lambda: _Ctx())
    monkeypatch.setattr(router_mod, "send_amount_changed_mail", _send_mail)
    payload = _payload()
    out = AmendOut(previousAmount=None, approvedAmount=Decimal("2"), decidedAt=datetime.now(UTC))
    await router_mod._deliver(SETTINGS, uuid.uuid4(), out, payload, None)
    assert calls[0]["gremium_id"] == payload.gremium_id
    assert calls[0]["queue"] is None
