"""Router-Tests application-types (T-25): Endpunkt-Verdrahtung ohne DB.

Die DB-gestützte ``ApplicationTypesService`` wird per ``dependency_overrides`` durch
ein Fake ersetzt; Auth über ``get_current_principal``. Echte DB-Pfade: Integration.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.application_types.router import get_application_types_service
from app.modules.application_types.schemas import ApplicationTypeListItem
from app.shared.paging import Page


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def list_types(
        self,
        *,
        lang: str,
        limit: int,
        offset: int,
        include_inactive: bool,
        admin: bool,
    ) -> Page[ApplicationTypeListItem]:
        self.calls.append(
            {
                "lang": lang,
                "limit": limit,
                "offset": offset,
                "include_inactive": include_inactive,
                "admin": admin,
            }
        )
        item = ApplicationTypeListItem(
            id=uuid4(),
            name="Finanzantrag",
            hasBudget=True,
            active=True,
            activeFormVersionId=uuid4(),
            key="finanz" if admin else None,
            gremiumId=uuid4() if admin else None,
        )
        return Page(items=[item], total=1, limit=limit, offset=offset)


@pytest.fixture
def fake_service() -> _FakeService:
    return _FakeService()


@pytest.fixture
def app(fake_service: _FakeService) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_application_types_service] = lambda: fake_service
    return application


@pytest.fixture
def app_client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as_admin(app: FastAPI) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions={"form.configure"}
    )


def _as_user(app: FastAPI) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="u", permissions=set())


# --------------------------------------------------------------------------- #
# Public list
# --------------------------------------------------------------------------- #
def test_list_public_ok_camel_case(app_client: TestClient, fake_service: _FakeService) -> None:
    r = app_client.get("/api/application-types")
    assert r.status_code == 200
    body = r.json()
    assert {"items", "total", "limit", "offset"} <= set(body)
    item = body["items"][0]
    assert item["name"] == "Finanzantrag"
    assert item["hasBudget"] is True
    assert item["active"] is True
    assert "activeFormVersionId" in item
    # Anonymer Aufruf: keine Admin-Sicht.
    call = fake_service.calls[0]
    assert call["admin"] is False
    assert call["include_inactive"] is False
    assert item["key"] is None
    assert item["gremiumId"] is None


def test_list_default_paging_passed_through(
    app_client: TestClient, fake_service: _FakeService
) -> None:
    app_client.get("/api/application-types")
    call = fake_service.calls[0]
    assert call["limit"] == 50  # paging.DEFAULT_LIMIT
    assert call["offset"] == 0
    assert call["lang"] == "de"


def test_list_query_params_passed_through(
    app_client: TestClient, fake_service: _FakeService
) -> None:
    app_client.get("/api/application-types?limit=10&offset=5&lang=en")
    call = fake_service.calls[0]
    assert call["limit"] == 10
    assert call["offset"] == 5
    assert call["lang"] == "en"


def test_list_user_without_permission_is_public_view(
    app: FastAPI, app_client: TestClient, fake_service: _FakeService
) -> None:
    _as_user(app)
    r = app_client.get("/api/application-types")
    assert r.status_code == 200
    assert fake_service.calls[0]["admin"] is False


# --------------------------------------------------------------------------- #
# Admin view
# --------------------------------------------------------------------------- #
def test_list_admin_sees_extra_fields(
    app: FastAPI, app_client: TestClient, fake_service: _FakeService
) -> None:
    _as_admin(app)
    r = app_client.get("/api/application-types")
    assert r.status_code == 200
    call = fake_service.calls[0]
    assert call["admin"] is True
    assert call["include_inactive"] is True
    item = r.json()["items"][0]
    assert item["key"] == "finanz"
    assert item["gremiumId"] is not None


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("limit", [0, 201])
def test_list_rejects_out_of_range_limit_422(app_client: TestClient, limit: int) -> None:
    r = app_client.get(f"/api/application-types?limit={limit}")
    assert r.status_code == 422


def test_list_rejects_negative_offset_422(app_client: TestClient) -> None:
    r = app_client.get("/api/application-types?offset=-1")
    assert r.status_code == 422


def test_list_rejects_overflow_offset_422(app_client: TestClient) -> None:
    # > int4 würde das DB-OFFSET overflowen → muss als 422 abgewehrt werden, nicht 500.
    r = app_client.get("/api/application-types?offset=10000000000000000000")
    assert r.status_code == 422


def test_list_rejects_unknown_query_param_422(app_client: TestClient) -> None:
    # extra="forbid": unbekannte Query-Parameter → 422 (negative_data_rejection).
    r = app_client.get("/api/application-types?bogus=1")
    assert r.status_code == 422


@pytest.mark.parametrize("lang", ["null", "xx", "EN", "de-DE", ""])
def test_list_rejects_invalid_lang_422(app_client: TestClient, lang: str) -> None:
    # `lang`-Enum: ungültige Werte (inkl. `lang=null`) → 422 statt still 200.
    # Schließt den be-contract-Coverage-Flake (schemathesis injiziert Müll, erwartet 4xx; PR #63).
    r = app_client.get(f"/api/application-types?lang={lang}")
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("lang", ["de", "en"])
def test_list_accepts_valid_lang_200(
    app_client: TestClient, fake_service: _FakeService, lang: str
) -> None:
    r = app_client.get(f"/api/application-types?lang={lang}")
    assert r.status_code == 200
    assert fake_service.calls[0]["lang"] == lang


def test_list_default_lang_is_de(app_client: TestClient, fake_service: _FakeService) -> None:
    # Default ohne Param → 200/de.
    r = app_client.get("/api/application-types")
    assert r.status_code == 200
    assert fake_service.calls[0]["lang"] == "de"


# --------------------------------------------------------------------------- #
# OpenAPI-Contract
# --------------------------------------------------------------------------- #
def test_openapi_declares_error_responses(app_client: TestClient) -> None:
    spec = app_client.get("/openapi.json").json()
    get_list = spec["paths"]["/api/application-types"]["get"]
    assert "422" in get_list["responses"]
    # T-10s Hook schreibt 4xx auf problem+json um.
    assert "application/problem+json" in get_list["responses"]["422"]["content"]
    # Erfolg bleibt application/json.
    assert "application/json" in get_list["responses"]["200"]["content"]


def test_openapi_lang_param_is_enum(app_client: TestClient) -> None:
    # `lang` als Enum dokumentiert (de|en) statt freier String.
    spec = app_client.get("/openapi.json").json()
    params = spec["paths"]["/api/application-types"]["get"]["parameters"]
    lang_param = next(p for p in params if p["name"] == "lang")
    assert lang_param["schema"]["enum"] == ["de", "en"]
    assert lang_param["schema"]["default"] == "de"
