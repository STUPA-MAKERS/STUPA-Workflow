"""Router-Tests Mail-Templates (#5-4): Endpunkt-Wiring + admin.notifications-Gate.

Der Service (CRUD + Vorschau) ist anderweitig unit-getestet; hier wird er gefaked,
um Verdrahtung und Permission-Gate zu prüfen."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.deps import get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.notifications.router import get_notification_service
from app.modules.notifications.schemas import (
    MailPreviewOut,
    MailPreviewPayloadRequest,
    MailTemplateCreate,
    MailTemplateOut,
    MailTemplateUpdate,
    MailTemplateUpsert,
)


class _FakeService:
    def __init__(self) -> None:
        self.tpl_id = uuid4()

    async def list_templates(self) -> list[MailTemplateOut]:
        return [
            MailTemplateOut(
                id=self.tpl_id,
                key="magic_link",
                subject_i18n={"de": "Anmeldung", "en": "Sign in"},
                body_i18n={"de": "Hallo {{name}}", "en": "Hi {{name}}"},
                body_html_i18n={},
                placeholders={"name": "Anzeigename"},
            )
        ]

    async def create_template(self, payload: MailTemplateCreate) -> MailTemplateOut:
        return MailTemplateOut(
            id=uuid4(),
            key=payload.key,
            subject_i18n=payload.subject_i18n,
            body_i18n=payload.body_i18n,
            body_html_i18n=payload.body_html_i18n,
            placeholders=payload.placeholders,
        )

    async def update_template(
        self, template_id: UUID, payload: MailTemplateUpdate
    ) -> MailTemplateOut:
        return MailTemplateOut(
            id=template_id,
            key="magic_link",
            subject_i18n=payload.subject_i18n or {"de": "x"},
            body_i18n=payload.body_i18n or {"de": "y"},
            body_html_i18n=payload.body_html_i18n or {},
            placeholders=payload.placeholders or {},
        )

    async def preview_template(self, template_id, req):  # noqa: ANN001
        return MailPreviewOut(
            subject="Anmeldung", text="Hallo Max", html=None, lang=req.lang
        )

    async def upsert_template(self, payload: MailTemplateUpsert) -> MailTemplateOut:
        self.upserted = payload
        return MailTemplateOut(
            id=uuid4(),
            key=payload.key,
            subject_i18n=payload.subject_i18n,
            body_i18n=payload.body_i18n,
            body_html_i18n=payload.body_html_i18n,
            placeholders={},
            source="override",
        )

    async def reset_template(self, key: str) -> MailTemplateOut:
        self.reset_key = key
        return MailTemplateOut(
            id=None,
            key=key,
            subject_i18n={"de": "B"},
            body_i18n={"de": "B"},
            body_html_i18n={},
            placeholders={},
            source="builtin",
        )

    async def preview_payload(self, req: MailPreviewPayloadRequest) -> MailPreviewOut:
        return MailPreviewOut(
            subject=req.subject_i18n.get("de", ""), text="rendered", html=None, lang=req.lang
        )


def _client(principal: Principal | None) -> tuple[TestClient, _FakeService]:
    app = create_app()
    svc = _FakeService()
    app.dependency_overrides[get_notification_service] = lambda: svc
    app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app), svc


def test_list_templates_ok_for_admin() -> None:
    client, _ = _client(Principal(sub="a", permissions={"admin.notifications"}))
    r = client.get("/api/admin/mail-templates")
    assert r.status_code == 200
    assert r.json()[0]["key"] == "magic_link"
    assert r.json()[0]["subjectI18n"]["de"] == "Anmeldung"


def test_templates_require_admin_notifications() -> None:
    client, _ = _client(Principal(sub="u", permissions={"admin.types"}))
    assert client.get("/api/admin/mail-templates").status_code == 403


def test_templates_require_login() -> None:
    client, _ = _client(None)
    assert client.get("/api/admin/mail-templates").status_code == 401


def test_update_and_preview_template() -> None:
    client, svc = _client(Principal(sub="a", permissions={"admin.notifications"}))
    upd = client.patch(
        f"/api/admin/mail-templates/{svc.tpl_id}",
        json={"subjectI18n": {"de": "Neu"}},
    )
    assert upd.status_code == 200
    assert upd.json()["subjectI18n"]["de"] == "Neu"
    prev = client.post(
        f"/api/admin/mail-templates/{svc.tpl_id}/preview",
        json={"lang": "de", "context": {"name": "Max"}},
    )
    assert prev.status_code == 200
    assert prev.json() == {"subject": "Anmeldung", "text": "Hallo Max", "html": None, "lang": "de"}


def test_upsert_template_by_key() -> None:
    client, svc = _client(Principal(sub="a", permissions={"admin.notifications"}))
    r = client.put(
        "/api/admin/mail-templates",
        json={"key": "task_new", "subjectI18n": {"de": "Neu"}, "bodyI18n": {"de": "Text"}},
    )
    assert r.status_code == 200
    assert r.json()["key"] == "task_new"
    assert r.json()["source"] == "override"
    assert svc.upserted.key == "task_new"


def test_reset_template_by_key() -> None:
    client, svc = _client(Principal(sub="a", permissions={"admin.notifications"}))
    r = client.delete("/api/admin/mail-templates/by-key/task_new")
    assert r.status_code == 200
    assert r.json()["source"] == "builtin"
    assert r.json()["id"] is None
    assert svc.reset_key == "task_new"


def test_preview_payload() -> None:
    client, _ = _client(Principal(sub="a", permissions={"admin.notifications"}))
    r = client.post(
        "/api/admin/mail-templates/preview",
        json={"subjectI18n": {"de": "Hi"}, "bodyI18n": {"de": "B"}, "lang": "de", "context": {}},
    )
    assert r.status_code == 200
    assert r.json()["subject"] == "Hi"


def test_upsert_requires_admin() -> None:
    client, _ = _client(Principal(sub="u", permissions={"admin.types"}))
    r = client.put(
        "/api/admin/mail-templates",
        json={"key": "task_new", "subjectI18n": {"de": "x"}, "bodyI18n": {"de": "y"}},
    )
    assert r.status_code == 403
