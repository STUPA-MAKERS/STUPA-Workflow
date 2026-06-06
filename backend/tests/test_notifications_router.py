"""Router-Tests Notifications (T-18): Endpunkt-Verdrahtung + RBAC, Service gefaked."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.notifications.router import get_notifications_service
from app.modules.notifications.schemas import (
    MailPreviewOut,
    MailTemplateOut,
    NotificationRuleOut,
    RecipientSpec,
)
from app.shared.errors import ConflictError, NotFoundError


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def list_rules(self) -> list[NotificationRuleOut]:
        self.calls.append("list_rules")
        return [
            NotificationRuleOut(
                id=uuid4(), event="status_changed",
                recipients=[RecipientSpec(kind="applicant")],
                template_key="status_update", application_type_id=None, enabled=True,
            )
        ]

    async def create_rule(self, payload):  # noqa: ANN001
        self.calls.append("create_rule")
        return NotificationRuleOut(
            id=uuid4(), event=payload.event, recipients=payload.recipients,
            template_key=payload.template_key,
            application_type_id=payload.application_type_id, enabled=payload.enabled,
        )

    async def update_rule(self, rule_id, payload):  # noqa: ANN001
        if str(rule_id).startswith("00000000"):
            raise NotFoundError("nope")
        return NotificationRuleOut(
            id=rule_id, event="status_changed", recipients=[],
            template_key="t", application_type_id=None, enabled=False,
        )

    async def list_templates(self) -> list[MailTemplateOut]:
        return [
            MailTemplateOut(
                id=uuid4(), key="magic_link", subject_i18n={"de": "s"},
                body_i18n={"de": "b"}, body_html_i18n={}, placeholders={},
            )
        ]

    async def create_template(self, payload):  # noqa: ANN001
        if payload.key == "dup":
            raise ConflictError("exists")
        return MailTemplateOut(
            id=uuid4(), key=payload.key, subject_i18n=payload.subject_i18n,
            body_i18n=payload.body_i18n, body_html_i18n=payload.body_html_i18n,
            placeholders=payload.placeholders,
        )

    async def update_template(self, template_id, payload):  # noqa: ANN001
        if str(template_id).startswith("00000000"):
            raise NotFoundError("nope")
        return MailTemplateOut(
            id=template_id, key="k", subject_i18n={"de": "s2"},
            body_i18n={"de": "b"}, body_html_i18n={}, placeholders={},
        )

    async def preview_template(self, template_id, req):  # noqa: ANN001
        if str(template_id).startswith("00000000"):
            raise NotFoundError("nope")
        return MailPreviewOut(subject="Hi Max", text="Body", html=None, lang=req.lang)


@pytest.fixture
def fake_service() -> _FakeService:
    return _FakeService()


@pytest.fixture
def app(fake_service: _FakeService) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_notifications_service] = lambda: fake_service
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as_admin(app: FastAPI) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions={"notification.manage"}
    )


# --------------------------------------------------------------------------- auth
def test_requires_auth_401(client: TestClient) -> None:
    assert client.get("/api/admin/notification-rules").status_code == 401


def test_forbidden_without_permission(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="u", permissions=set()
    )
    r = client.get("/api/admin/notification-rules")
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


# --------------------------------------------------------------------------- rules
def test_list_rules(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.get("/api/admin/notification-rules")
    assert r.status_code == 200
    assert r.json()[0]["templateKey"] == "status_update"


def test_create_rule(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.post(
        "/api/admin/notification-rules",
        json={"event": "status_changed", "templateKey": "t",
              "recipients": [{"kind": "applicant"}]},
    )
    assert r.status_code == 201
    assert r.json()["event"] == "status_changed"


def test_mutating_endpoints_declare_400(app: FastAPI) -> None:
    """Body-tragende Mutationen müssen 400 (malformed JSON/Parse) deklarieren —
    sonst schemathesis-Failure »undocumented status code« (be-contract)."""
    spec = app.openapi()
    cases = [
        ("/api/admin/notification-rules", "post"),
        ("/api/admin/notification-rules/{rule_id}", "patch"),
        ("/api/admin/mail-templates", "post"),
        ("/api/admin/mail-templates/{template_id}", "patch"),
        ("/api/admin/mail-templates/{template_id}/preview", "post"),
    ]
    for path, method in cases:
        responses = spec["paths"][path][method]["responses"]
        assert "400" in responses, f"{method.upper()} {path} missing 400"
        assert list(responses["400"]["content"]) == ["application/problem+json"]


def test_create_rule_unknown_event_422(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.post(
        "/api/admin/notification-rules",
        json={"event": "bogus", "templateKey": "t"},
    )
    assert r.status_code == 422


def test_update_rule_404(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.patch(
        "/api/admin/notification-rules/00000000-0000-0000-0000-000000000000",
        json={"enabled": False},
    )
    assert r.status_code == 404


def test_update_rule_ok(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.patch(
        f"/api/admin/notification-rules/{uuid4()}", json={"enabled": False}
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False


# --------------------------------------------------------------------------- templates
def test_list_templates(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.get("/api/admin/mail-templates")
    assert r.status_code == 200
    assert r.json()[0]["key"] == "magic_link"


def test_create_template(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.post(
        "/api/admin/mail-templates",
        json={"key": "welcome", "subjectI18n": {"de": "Hi"}, "bodyI18n": {"de": "B"}},
    )
    assert r.status_code == 201
    assert r.json()["key"] == "welcome"


def test_create_template_duplicate_409(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.post(
        "/api/admin/mail-templates",
        json={"key": "dup", "subjectI18n": {"de": "x"}, "bodyI18n": {"de": "y"}},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"


def test_update_template_ok(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.patch(
        f"/api/admin/mail-templates/{uuid4()}", json={"subjectI18n": {"de": "s2"}}
    )
    assert r.status_code == 200
    assert r.json()["subjectI18n"] == {"de": "s2"}


def test_preview_template(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.post(
        f"/api/admin/mail-templates/{uuid4()}/preview",
        json={"lang": "en", "context": {"name": "Max"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "Hi Max" and body["lang"] == "en"


def test_preview_template_404(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.post(
        "/api/admin/mail-templates/00000000-0000-0000-0000-000000000000/preview",
        json={"lang": "de", "context": {}},
    )
    assert r.status_code == 404
