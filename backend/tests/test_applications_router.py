"""Router-Tests applications (T-12): Endpunkt-Verdrahtung ohne DB (Service-Fake).

Auth (Principal/Applicant) und der ``ApplicationsService`` werden per
``dependency_overrides`` ersetzt; echte DB-Pfade liegen in der Integration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.applications.router import (
    get_applications_service,
    get_magic_link_sender,
)
from app.modules.applications.schemas import (
    ApplicationListItem,
    ApplicationOut,
    CommentOut,
    StateOut,
    TimelineEventOut,
    VersionOut,
)
from app.modules.auth.principal import Applicant, Principal
from app.shared.paging import Page

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


class _FakeApp:
    def __init__(self, app_id: UUID) -> None:
        self.id = app_id


def _state() -> StateOut:
    return StateOut(
        id=uuid4(), key="draft", label={"de": "Entwurf"}, category="open", editAllowed=True
    )


def _out(app_id: UUID, *, with_pii: bool) -> ApplicationOut:
    return ApplicationOut(
        id=app_id,
        typeId=uuid4(),
        state=_state(),
        gremiumId=None,
        budgetPotId=None,
        amount=Decimal("10.00"),
        currency="EUR",
        data={"title": "X"},
        version=1,
        lang="de",
        createdAt=_NOW,
        updatedAt=_NOW,
        applicant=None,
    )


class _FakeService:
    def __init__(self) -> None:
        self.created: object | None = None
        self.created_actor: str | None = None
        self.last_include_pii: bool | None = None
        self.comment_args: dict[str, object] | None = None

    async def create(self, payload, *, actor="applicant"):  # noqa: ANN001
        self.created = payload
        self.created_actor = actor
        return _FakeApp(uuid4()), str(payload.applicant_email)

    async def get(self, application_id, *, include_pii):  # noqa: ANN001
        self.last_include_pii = include_pii
        return _out(application_id, with_pii=include_pii)

    async def patch(self, application_id, data, *, changed_by):  # noqa: ANN001
        return _out(application_id, with_pii=False)

    async def timeline(self, application_id):  # noqa: ANN001
        return [
            TimelineEventOut(
                fromStateId=None, toStateId=uuid4(), actor="applicant", at=_NOW, note=None
            )
        ]

    async def versions(self, application_id):  # noqa: ANN001
        return [VersionOut(version=1, data={"title": "X"}, diff=None, changedBy="x", at=_NOW)]

    async def list_applications(self, **kwargs):  # noqa: ANN003
        self.list_kwargs = kwargs
        item = ApplicationListItem(
            id=uuid4(), typeId=uuid4(), state=_state(), createdAt=_NOW, updatedAt=_NOW
        )
        return Page(items=[item], total=1, limit=kwargs["limit"], offset=kwargs["offset"])

    async def add_comment(self, application_id, *, author, author_kind, body, visibility):  # noqa: ANN001
        self.comment_args = {
            "author": author,
            "author_kind": author_kind,
            "visibility": visibility,
        }
        return CommentOut(
            id=uuid4(),
            author=author,
            authorKind=author_kind,
            body=body,
            visibility=visibility,
            at=_NOW,
        )

    async def list_comments(self, application_id, *, include_internal):  # noqa: ANN001
        self.last_include_internal = include_internal
        return []


@pytest.fixture
def fake_service() -> _FakeService:
    return _FakeService()


@pytest.fixture
def sent() -> list[tuple[str, UUID]]:
    return []


@pytest.fixture
def app(fake_service: _FakeService, sent: list[tuple[str, UUID]]) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_applications_service] = lambda: fake_service

    async def _no_mail(settings, email, application_id):  # noqa: ANN001, ANN202
        sent.append((email, application_id))

    application.dependency_overrides[get_magic_link_sender] = lambda: _no_mail
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as_principal(app: FastAPI, *perms: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions=set(perms)
    )
    app.dependency_overrides[get_current_applicant] = lambda: None


def _as_applicant(app: FastAPI, application_id: UUID, scope: str = "edit") -> None:
    app.dependency_overrides[get_current_principal] = lambda: None
    app.dependency_overrides[get_current_applicant] = lambda: Applicant(
        application_id=str(application_id), scope=scope  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# POST /applications (public)
# --------------------------------------------------------------------------- #
def _create_body() -> dict:
    return {
        "typeId": str(uuid4()),
        "data": {"title": "Mein Antrag"},
        "applicantEmail": "a@example.org",
        "lang": "de",
    }


def test_create_application_201_and_enqueues_mail(
    client: TestClient, fake_service: _FakeService, sent: list[tuple[str, UUID]]
) -> None:
    r = client.post("/api/applications", json=_create_body())
    assert r.status_code == 201
    body = r.json()
    assert UUID(body["applicationId"])
    assert fake_service.created is not None
    # Magic-Link-Mail wurde (per Background-Task) für die Antragsteller-Mail enqueued.
    assert sent and sent[0][0] == "a@example.org"


def test_create_application_rejects_bad_email_422(client: TestClient) -> None:
    body = _create_body() | {"applicantEmail": "not-an-email"}
    r = client.post("/api/applications", json=body)
    assert r.status_code == 422


def _login(app: FastAPI, **kw: object) -> None:
    """Eingeloggten Principal setzen (für die Altcha-Befreiung/Identitäts-Ableitung, #24)."""
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub=str(kw.get("sub", "u-1")),
        email=kw.get("email"),  # type: ignore[arg-type]
        display_name=kw.get("display_name"),  # type: ignore[arg-type]
        permissions=set(),
    )
    app.dependency_overrides[get_current_applicant] = lambda: None


def test_create_application_logged_in_skips_altcha_and_derives_identity(
    app: FastAPI, client: TestClient, fake_service: _FakeService, sent: list[tuple[str, UUID]]
) -> None:
    _login(app, sub="u-7", email="user@example.org", display_name="Userin")
    # Kein applicantEmail, kein Altcha — als eingeloggte:r Nutzer:in erlaubt (#24).
    body = {"typeId": str(uuid4()), "data": {"title": "Mein Antrag"}, "lang": "de"}
    r = client.post("/api/applications", json=body)
    assert r.status_code == 201
    assert fake_service.created.applicant_email == "user@example.org"  # type: ignore[union-attr]
    assert fake_service.created.applicant_name == "Userin"  # type: ignore[union-attr]
    assert fake_service.created_actor == "u-7"
    assert sent and sent[0][0] == "user@example.org"


def test_create_application_logged_in_explicit_email_on_behalf(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _login(app, sub="verwalter", email="staff@example.org", display_name="Staff")
    body = _create_body() | {"applicantEmail": "applicant@example.org"}
    r = client.post("/api/applications", json=body)
    assert r.status_code == 201
    # Explizite Angabe gewinnt über die Account-Ableitung (Anlage im Namen).
    assert fake_service.created.applicant_email == "applicant@example.org"  # type: ignore[union-attr]
    assert fake_service.created_actor == "verwalter"


def test_create_application_oversize_payload_413(
    client: TestClient, fake_service: _FakeService
) -> None:
    body = _create_body() | {"data": {"blob": "x" * 200_000}}
    r = client.post("/api/applications", json=body)
    assert r.status_code == 413
    assert r.headers["content-type"] == "application/problem+json"
    assert fake_service.created is None  # nie an den Service durchgereicht


# --------------------------------------------------------------------------- #
# GET /applications/{id} (A/P)
# --------------------------------------------------------------------------- #
def test_get_application_principal_sees_pii(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "application.read")
    app_id = uuid4()
    r = client.get(f"/api/applications/{app_id}")
    assert r.status_code == 200
    assert fake_service.last_include_pii is True


def test_get_application_applicant_no_pii(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    app_id = uuid4()
    _as_applicant(app, app_id, "view")
    r = client.get(f"/api/applications/{app_id}")
    assert r.status_code == 200
    assert fake_service.last_include_pii is False


def test_get_application_requires_auth_401(client: TestClient) -> None:
    r = client.get(f"/api/applications/{uuid4()}")
    assert r.status_code == 401


def test_get_application_applicant_other_app_403(app: FastAPI, client: TestClient) -> None:
    _as_applicant(app, uuid4(), "view")
    r = client.get(f"/api/applications/{uuid4()}")
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# PATCH /applications/{id}
# --------------------------------------------------------------------------- #
def test_patch_application_applicant_edit(app: FastAPI, client: TestClient) -> None:
    app_id = uuid4()
    _as_applicant(app, app_id, "edit")
    r = client.patch(f"/api/applications/{app_id}", json={"data": {"title": "Neu"}})
    assert r.status_code == 200


def test_patch_application_applicant_view_forbidden(app: FastAPI, client: TestClient) -> None:
    app_id = uuid4()
    _as_applicant(app, app_id, "view")
    r = client.patch(f"/api/applications/{app_id}", json={"data": {}})
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# timeline / versions
# --------------------------------------------------------------------------- #
def test_timeline_ap(app: FastAPI, client: TestClient) -> None:
    app_id = uuid4()
    _as_applicant(app, app_id, "view")
    r = client.get(f"/api/applications/{app_id}/timeline")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_versions_principal_only(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "application.read")
    r = client.get(f"/api/applications/{uuid4()}/versions")
    assert r.status_code == 200


def test_versions_applicant_forbidden(app: FastAPI, client: TestClient) -> None:
    app_id = uuid4()
    _as_applicant(app, app_id, "edit")
    r = client.get(f"/api/applications/{app_id}/versions")
    assert r.status_code in (401, 403)


# --------------------------------------------------------------------------- #
# GET /applications (list, principal)
# --------------------------------------------------------------------------- #
def test_list_applications_filters_passed(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "application.read")
    state, gremium = uuid4(), uuid4()
    r = client.get(f"/api/applications?state={state}&gremium={gremium}&q=foo&limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert fake_service.list_kwargs["state_id"] == state
    assert fake_service.list_kwargs["gremium_id"] == gremium
    assert fake_service.list_kwargs["q"] == "foo"
    assert fake_service.list_kwargs["limit"] == 10


def test_list_applications_requires_auth(client: TestClient) -> None:
    assert client.get("/api/applications").status_code == 401


# --------------------------------------------------------------------------- #
# comments
# --------------------------------------------------------------------------- #
def test_comment_principal_internal_ok(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "application.read")
    r = client.post(
        f"/api/applications/{uuid4()}/comments",
        json={"body": "intern", "visibility": "internal"},
    )
    assert r.status_code == 201
    assert fake_service.comment_args == {
        "author": "admin",
        "author_kind": "principal",
        "visibility": "internal",
    }


def test_comment_applicant_internal_forbidden(app: FastAPI, client: TestClient) -> None:
    app_id = uuid4()
    _as_applicant(app, app_id, "view")
    r = client.post(
        f"/api/applications/{app_id}/comments",
        json={"body": "x", "visibility": "internal"},
    )
    assert r.status_code == 403


def test_comment_applicant_public_ok(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    app_id = uuid4()
    _as_applicant(app, app_id, "view")
    r = client.post(
        f"/api/applications/{app_id}/comments",
        json={"body": "hallo", "visibility": "public"},
    )
    assert r.status_code == 201
    assert fake_service.comment_args is not None
    assert fake_service.comment_args["author_kind"] == "applicant"


def test_list_comments_applicant_public_only(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    app_id = uuid4()
    _as_applicant(app, app_id, "view")
    r = client.get(f"/api/applications/{app_id}/comments")
    assert r.status_code == 200
    assert fake_service.last_include_internal is False


def test_list_comments_principal_all(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "application.read")
    r = client.get(f"/api/applications/{uuid4()}/comments")
    assert r.status_code == 200
    assert fake_service.last_include_internal is True


# --------------------------------------------------------------------------- #
# OpenAPI contract
# --------------------------------------------------------------------------- #
def test_openapi_declares_error_responses(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    post = spec["paths"]["/api/applications"]["post"]
    assert {"400", "404", "413", "422"} <= set(post["responses"])
    patch = spec["paths"]["/api/applications/{application_id}"]["patch"]
    assert {"400", "401", "403", "404", "409", "422"} <= set(patch["responses"])
    assert "application/problem+json" in patch["responses"]["409"]["content"]
    comments = spec["paths"]["/api/applications/{application_id}/comments"]["post"]
    assert {"400", "401", "403", "404", "422"} <= set(comments["responses"])
