"""Router-Tests Forms (T-11): Endpunkt-Verdrahtung ohne DB (Service überschrieben).

Die DB-gestützte ``FormsService`` wird per ``dependency_overrides`` durch ein
Fake ersetzt; Auth über ``get_current_principal``. Echte DB-Pfade: Integration.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.forms.router import get_forms_service
from app.modules.forms.schemas import (
    EffectiveFormOut,
    FormSectionOut,
    FormVersionCreate,
    FormVersionOut,
)
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError


class _FakeService:
    def __init__(self) -> None:
        self.created: tuple[object, FormVersionCreate] | None = None

    async def get_effective_form(self, type_id, budget_pot_id=None):  # noqa: ANN001
        if budget_pot_id is not None and str(budget_pot_id).startswith("00000000"):
            raise NotFoundError("budget pot not found")
        sections = [
            FormSectionOut(
                key="main",
                label={"de": "Antrag"},
                fields=[FormFieldDef(key="title", type="text", label={"de": "Titel"})],
            )
        ]
        if budget_pot_id is not None:
            sections.append(
                FormSectionOut(
                    key="budget",
                    label={"de": "Topf"},
                    fields=[FormFieldDef(key="cost", type="currency", label={"de": "Kosten"})],
                )
            )
        return EffectiveFormOut(
            applicationTypeId=type_id,
            formVersionId=uuid4(),
            budgetPotId=budget_pot_id,
            sections=sections,
        )

    async def create_form_version(self, type_id, payload: FormVersionCreate):  # noqa: ANN001
        self.created = (type_id, payload)
        return FormVersionOut(
            id=uuid4(),
            applicationTypeId=type_id,
            version=1,
            active=payload.activate,
            fields=payload.fields,
        )


@pytest.fixture
def fake_service() -> _FakeService:
    return _FakeService()


@pytest.fixture
def app(fake_service: _FakeService) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_forms_service] = lambda: fake_service
    return application


@pytest.fixture
def app_client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as_admin(app: FastAPI) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions={"form.configure"}
    )


# --------------------------------------------------------------------------- #
# GET effective form
# --------------------------------------------------------------------------- #
def test_get_effective_form_main_only(app_client: TestClient) -> None:
    type_id = uuid4()
    r = app_client.get(f"/api/application-types/{type_id}/form")
    assert r.status_code == 200
    body = r.json()
    assert body["applicationTypeId"] == str(type_id)
    assert [s["key"] for s in body["sections"]] == ["main"]
    assert body["sections"][0]["fields"][0]["key"] == "title"


def test_get_effective_form_with_budget_pot(app_client: TestClient) -> None:
    type_id, pot_id = uuid4(), uuid4()
    r = app_client.get(f"/api/application-types/{type_id}/form?budgetPotId={pot_id}")
    assert r.status_code == 200
    body = r.json()
    assert [s["key"] for s in body["sections"]] == ["main", "budget"]
    assert body["budgetPotId"] == str(pot_id)


def test_get_effective_form_unknown_pot_404(app_client: TestClient) -> None:
    type_id = uuid4()
    pot_id = "00000000-0000-0000-0000-000000000000"
    r = app_client.get(f"/api/application-types/{type_id}/form?budgetPotId={pot_id}")
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_get_effective_form_bad_uuid_422(app_client: TestClient) -> None:
    r = app_client.get("/api/application-types/not-a-uuid/form")
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# POST form version (auth)
# --------------------------------------------------------------------------- #
def _payload() -> dict:
    return {
        "fields": [
            {"key": "title", "type": "text", "label": {"de": "Titel"}, "required": True}
        ],
        "activate": True,
    }


def test_create_form_version_requires_auth(app_client: TestClient) -> None:
    type_id = uuid4()
    r = app_client.post(
        f"/api/admin/application-types/{type_id}/form-versions", json=_payload()
    )
    assert r.status_code == 401


def test_create_form_version_forbidden_without_perm(
    app: FastAPI, app_client: TestClient
) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="u", permissions=set()
    )
    type_id = uuid4()
    r = app_client.post(
        f"/api/admin/application-types/{type_id}/form-versions", json=_payload()
    )
    assert r.status_code == 403


def test_create_form_version_ok(
    app: FastAPI, app_client: TestClient, fake_service: _FakeService
) -> None:
    _as_admin(app)
    type_id = uuid4()
    r = app_client.post(
        f"/api/admin/application-types/{type_id}/form-versions", json=_payload()
    )
    assert r.status_code == 201
    body = r.json()
    assert body["version"] == 1
    assert body["active"] is True
    assert body["fields"][0]["key"] == "title"
    assert fake_service.created is not None


def test_create_form_version_rejects_empty_fields(
    app: FastAPI, app_client: TestClient
) -> None:
    _as_admin(app)
    type_id = uuid4()
    r = app_client.post(
        f"/api/admin/application-types/{type_id}/form-versions",
        json={"fields": [], "activate": True},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# OpenAPI-Contract: Fehler-Status deklariert (für Schemathesis-Conformance)
# --------------------------------------------------------------------------- #
def test_openapi_declares_error_responses(app_client: TestClient) -> None:
    spec = app_client.get("/openapi.json").json()
    get_form = spec["paths"]["/api/application-types/{type_id}/form"]["get"]
    assert "404" in get_form["responses"]
    post = spec["paths"]["/api/admin/application-types/{type_id}/form-versions"]["post"]
    assert {"400", "401", "403", "404", "422"} <= set(post["responses"])
    # T-10s Hook schreibt 4xx auf problem+json um
    assert "application/problem+json" in get_form["responses"]["404"]["content"]
