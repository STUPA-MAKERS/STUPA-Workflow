"""Router tests for applications (T-12): endpoint wiring without a database.

A `dependency_overrides` entry replaces the auth dependencies for principal and
applicant and the `ApplicationsService` with fakes. The integration suite covers the
real database paths.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.applications.router import (
    get_applications_service,
    get_comment_mail_sender,
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
        id=uuid4(), key="draft", label={"de": "Entwurf"}, color="#4a90d9", editAllowed=True
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


class _FakeAuditResult:
    def scalar_one_or_none(self) -> None:
        return None


class _FakeAuditSession:
    """Minimal session for the audit hook of the export endpoints, without database access."""

    def __init__(self) -> None:
        self.entries: list[Any] = []
        self.committed = False

    async def execute(self, _stmt: object) -> _FakeAuditResult:
        return _FakeAuditResult()

    def add(self, obj: object) -> None:
        self.entries.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True


class _FakeService:
    def __init__(self) -> None:
        self.created: object | None = None
        self.created_actor: str | None = None
        self.last_include_pii: bool | None = None
        self.comment_args: dict[str, object] | None = None
        self.comment_write_args: dict[str, object] | None = None
        self.session = _FakeAuditSession()

    async def create(self, payload, *, actor="applicant"):  # noqa: ANN001
        self.created = payload
        self.created_actor = actor
        return _FakeApp(uuid4()), str(payload.applicant_email)

    async def get(  # noqa: ANN001
        self,
        application_id,
        *,
        include_pii,
        requester_sub=None,
        requester_can_manage=False,
        allow_unconfirmed=True,
    ):
        self.last_include_pii = include_pii
        self.last_allow_unconfirmed = allow_unconfirmed
        return _out(application_id, with_pii=include_pii)

    async def patch(  # noqa: ANN001
        self, application_id, data, *, changed_by, bypass_state_lock=False, allow_unconfirmed=True
    ):
        self.last_bypass_state_lock = bypass_state_lock
        return _out(application_id, with_pii=False)

    async def update_applicant(self, application_id, payload, *, actor):  # noqa: ANN001
        from app.modules.applications.schemas import ApplicantOut

        self.applicant_args = (application_id, payload.email, payload.name, actor)
        return ApplicantOut(email=payload.email, name=payload.name, anonymized=False)

    async def delete(self, application_id, *, actor=None):  # noqa: ANN001
        self.deleted = application_id
        self.deleted_actor = actor

    async def timeline(self, application_id, *, allow_unconfirmed=True):  # noqa: ANN001
        return [
            TimelineEventOut(
                fromStateId=None, toStateId=uuid4(), actor="applicant", at=_NOW, note=None
            )
        ]

    async def versions(self, application_id, *, allow_unconfirmed=True):  # noqa: ANN001
        self.versions_allow_unconfirmed = allow_unconfirmed
        return [VersionOut(version=1, data={"title": "X"}, diff=None, changedBy="x", at=_NOW)]

    async def list_applications(self, **kwargs):  # noqa: ANN003
        self.list_kwargs = kwargs
        item = ApplicationListItem(
            id=uuid4(), typeId=uuid4(), state=_state(), createdAt=_NOW, updatedAt=_NOW
        )
        return Page(items=[item], total=1, limit=kwargs["limit"], offset=kwargs["offset"])

    async def name_maps(self, locale="de"):  # noqa: ANN001
        self.name_maps_called = True
        return {}, {}

    async def add_comment(  # noqa: ANN001
        self, application_id, *, author, author_kind, body, visibility, allow_unconfirmed=True
    ):
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

    async def list_comments(  # noqa: ANN001
        self,
        application_id,
        *,
        include_internal,
        allow_unconfirmed=True,
        viewer_sub=None,
        viewer_is_applicant=False,
    ):
        self.last_include_internal = include_internal
        self.last_viewer_sub = viewer_sub
        self.last_viewer_is_applicant = viewer_is_applicant
        return []

    async def update_comment(  # noqa: ANN001
        self,
        application_id,
        comment_id,
        *,
        body,
        actor,
        viewer_sub,
        viewer_is_applicant,
        can_manage,
        allow_unconfirmed=True,
    ):
        self.comment_write_args = {
            "comment_id": comment_id,
            "actor": actor,
            "viewer_sub": viewer_sub,
            "viewer_is_applicant": viewer_is_applicant,
            "can_manage": can_manage,
        }
        return CommentOut(
            id=comment_id,
            author=viewer_sub,
            authorKind="principal" if viewer_sub else "applicant",
            body=body,
            visibility="internal",
            at=_NOW,
        )

    async def delete_comment(  # noqa: ANN001
        self,
        application_id,
        comment_id,
        *,
        actor,
        viewer_sub,
        viewer_is_applicant,
        can_manage,
        allow_unconfirmed=True,
    ):
        self.comment_write_args = {
            "comment_id": comment_id,
            "actor": actor,
            "viewer_sub": viewer_sub,
            "viewer_is_applicant": viewer_is_applicant,
            "can_manage": can_manage,
        }


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

    async def _no_mail(settings, email, application_id, pool):  # noqa: ANN001, ANN202
        sent.append((email, application_id))

    async def _no_comment_mail(*args):  # noqa: ANN002, ANN202 — background task without a DB
        pass

    application.dependency_overrides[get_magic_link_sender] = lambda: _no_mail
    application.dependency_overrides[get_comment_mail_sender] = lambda: _no_comment_mail
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
        application_id=str(application_id),
        scope=scope,  # type: ignore[arg-type]
    )


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
    # A background task enqueues the magic-link mail to the applicant address.
    assert sent and sent[0][0] == "a@example.org"


def test_create_application_rejects_bad_email_422(client: TestClient) -> None:
    body = _create_body() | {"applicantEmail": "not-an-email"}
    r = client.post("/api/applications", json=body)
    assert r.status_code == 422


def _login(app: FastAPI, **kw: object) -> None:
    """Set a logged-in principal for the ALTCHA exemption and identity derivation (#24)."""
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
    # A logged-in user may omit applicantEmail and ALTCHA (#24).
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
    # The explicit value wins over the account derivation (creation for another person).
    assert fake_service.created.applicant_email == "applicant@example.org"  # type: ignore[union-attr]
    assert fake_service.created_actor == "verwalter"


def test_create_application_oversize_payload_413(
    client: TestClient, fake_service: _FakeService
) -> None:
    body = _create_body() | {"data": {"blob": "x" * 200_000}}
    r = client.post("/api/applications", json=body)
    assert r.status_code == 413
    assert r.headers["content-type"] == "application/problem+json"
    assert fake_service.created is None  # never passed on to the service


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


def test_read_all_reads_any_application(app: FastAPI, client: TestClient) -> None:
    """#app-read-all: `application.read_all` reads any application without owner or manage."""
    _as_principal(app, "application.read_all")
    r = client.get(f"/api/applications/{uuid4()}")
    assert r.status_code == 200


def test_edit_any_bypasses_state_lock(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """#app-edit-any: `application.edit_any` may write and lifts the state lock."""
    _as_principal(app, "application.edit_any")
    r = client.patch(f"/api/applications/{uuid4()}", json={"data": {"title": "X"}})
    assert r.status_code == 200
    assert fake_service.last_bypass_state_lock is True


def test_delete_application_admin(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    app_id = uuid4()
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="a", roles=["admin"], permissions={"application.manage"}
    )
    app.dependency_overrides[get_current_applicant] = lambda: None
    r = client.delete(f"/api/applications/{app_id}")
    assert r.status_code == 204
    assert fake_service.deleted == app_id


def test_delete_application_permission_holder(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """#g9: a non-admin role that holds ``application.delete`` may delete."""
    app_id = uuid4()
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="office", roles=["office"], permissions={"application.delete"}
    )
    app.dependency_overrides[get_current_applicant] = lambda: None
    r = client.delete(f"/api/applications/{app_id}")
    assert r.status_code == 204
    assert fake_service.deleted == app_id


def test_delete_application_manager_forbidden(app: FastAPI, client: TestClient) -> None:
    """#g9: ``application.manage`` alone must NOT delete."""
    _as_principal(app, "application.manage")
    r = client.delete(f"/api/applications/{uuid4()}")
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "forbidden"


def test_delete_application_applicant_unauthorized(app: FastAPI, client: TestClient) -> None:
    app_id = uuid4()
    _as_applicant(app, app_id, "edit")
    r = client.delete(f"/api/applications/{app_id}")
    assert r.status_code == 401  # no principal, so require_principal answers 401


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
    # With application.read there is no owner filter. All applications stay visible.
    assert fake_service.list_kwargs["owner_sub"] is None


def test_list_applications_without_read_scopes_to_own(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    # Without application.read and without admin the list shows only own applications (#24).
    _as_principal(app)  # authenticated but without any permission
    r = client.get("/api/applications")
    assert r.status_code == 200
    assert fake_service.list_kwargs["owner_sub"] == "admin"  # principal.sub of the fake


def test_list_applications_mine_forces_owner_filter(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    # "My applications" on the dashboard: mine=true forces the owner filter EVEN for a
    # principal with application.read. Without it a permitted user sees other applications.
    _as_principal(app, "application.read")
    r = client.get("/api/applications?mine=true")
    assert r.status_code == 200
    assert fake_service.list_kwargs["owner_sub"] == "admin"


def test_list_applications_amount_date_sort_passed(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    from datetime import date
    from decimal import Decimal

    _as_principal(app, "application.read")
    r = client.get(
        "/api/applications"
        "?amountMin=100&amountMax=500&createdFrom=2026-01-01&createdTo=2026-02-01"
        "&sort=amount&order=asc"
    )
    assert r.status_code == 200
    kw = fake_service.list_kwargs
    assert kw["amount_min"] == Decimal("100") and kw["amount_max"] == Decimal("500")
    assert kw["created_from"] == date(2026, 1, 1) and kw["created_to"] == date(2026, 2, 1)
    assert kw["sort"] == "amount" and kw["order"] == "asc"


def test_list_applications_rejects_bad_sort_422(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "application.read")
    assert client.get("/api/applications?sort=bogus").status_code == 422


def test_list_applications_requires_auth(client: TestClient) -> None:
    assert client.get("/api/applications").status_code == 401


_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_applications_export_requires_permission(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "application.read")
    assert client.get("/api/applications/export.xlsx").status_code == 403


def test_applications_export_xlsx(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "application.export")
    gremium = uuid4()
    r = client.get(f"/api/applications/export.xlsx?gremium={gremium}&q=foo")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(_XLSX)
    assert "applications.xlsx" in r.headers["content-disposition"]
    assert r.content[:2] == b"PK"
    assert fake_service.list_kwargs["gremium_id"] == gremium
    assert fake_service.list_kwargs["q"] == "foo"
    assert fake_service.name_maps_called is True
    # The router audits the export (#1). It writes the entry and commits in one transaction.
    (entry,) = fake_service.session.entries
    assert entry.action == "export"
    assert entry.actor == "admin"
    assert entry.target_id == "applications.xlsx"
    assert fake_service.session.committed is True


def test_applications_export_caps_rows(app: FastAPI, client: TestClient) -> None:
    """A hit count above EXPORT_MAX_ROWS gives 413, not a huge workbook (anti-DoS, FIX 6)."""
    from app.modules.applications.router import EXPORT_MAX_ROWS

    class _BigService:
        def __init__(self) -> None:
            self.name_maps_called = False

        async def list_applications(self, **kwargs: object) -> Page[ApplicationListItem]:
            # A `total` above the cap signals "too large".
            item = ApplicationListItem(
                id=uuid4(), typeId=uuid4(), state=_state(), createdAt=_NOW, updatedAt=_NOW
            )
            return Page(
                items=[item],
                total=EXPORT_MAX_ROWS + 1,
                limit=int(kwargs["limit"]),  # type: ignore[call-overload]
                offset=0,
            )

        async def name_maps(self, locale: str = "de") -> tuple[dict, dict]:
            self.name_maps_called = True
            return {}, {}

    big = _BigService()
    app.dependency_overrides[get_applications_service] = lambda: big
    _as_principal(app, "application.export")
    r = client.get("/api/applications/export.xlsx")
    assert r.status_code == 413
    # The router never reaches name_maps or the workbook build.
    assert big.name_maps_called is False


def test_applications_export_caps_rows_by_item_count(app: FastAPI, client: TestClient) -> None:
    """Even when `total` does not count: more rows than the cap gives 413 (FIX 6)."""
    from app.modules.applications.router import EXPORT_MAX_ROWS

    class _ManyItemsService:
        async def list_applications(self, **kwargs: object) -> Page[ApplicationListItem]:
            items = [
                ApplicationListItem(
                    id=uuid4(),
                    typeId=uuid4(),
                    state=_state(),
                    createdAt=_NOW,
                    updatedAt=_NOW,
                )
                for _ in range(EXPORT_MAX_ROWS + 1)
            ]
            return Page(items=items, total=0, limit=int(kwargs["limit"]), offset=0)  # type: ignore[call-overload]

        async def name_maps(self, locale: str = "de") -> tuple[dict, dict]:
            return {}, {}

    app.dependency_overrides[get_applications_service] = lambda: _ManyItemsService()
    _as_principal(app, "application.export")
    r = client.get("/api/applications/export.xlsx")
    assert r.status_code == 413


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


def test_comment_body_too_long_422(app: FastAPI, client: TestClient) -> None:
    """Free-text cap (FIX 5): a body above 10 000 characters gives 422."""
    _as_principal(app, "application.read")
    r = client.post(
        f"/api/applications/{uuid4()}/comments",
        json={"body": "x" * 10_001, "visibility": "public"},
    )
    assert r.status_code == 422


def test_comment_body_at_cap_ok(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """A body exactly at the cap of 10 000 characters stays valid (FIX 5)."""
    _as_principal(app, "application.read")
    r = client.post(
        f"/api/applications/{uuid4()}/comments",
        json={"body": "x" * 10_000, "visibility": "public"},
    )
    assert r.status_code == 201


def test_create_application_long_name_rejected_422(client: TestClient) -> None:
    """Cap on `applicantName` (FIX 5): more than 256 characters gives 422."""
    body = _create_body() | {"applicantName": "n" * 257}
    r = client.post("/api/applications", json=body)
    assert r.status_code == 422


def test_openapi_declares_error_responses(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    post = spec["paths"]["/api/applications"]["post"]
    assert {"400", "404", "413", "422"} <= set(post["responses"])
    patch = spec["paths"]["/api/applications/{application_id}"]["patch"]
    assert {"400", "401", "403", "404", "409", "422"} <= set(patch["responses"])
    assert "application/problem+json" in patch["responses"]["409"]["content"]
    comments = spec["paths"]["/api/applications/{application_id}/comments"]["post"]
    assert {"400", "401", "403", "404", "422"} <= set(comments["responses"])


# PATCH/DELETE on one comment: the author or a principal with application.manage.


def test_patch_comment_passes_session_identity(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """The author and the manage flag come from the session, never from the body."""
    _as_principal(app, "application.read")
    cid = uuid4()
    r = client.patch(
        f"/api/applications/{uuid4()}/comments/{cid}",
        # The body carries a foreign author on purpose. The server ignores it.
        json={"body": "korrigiert", "author": "someone-else"},
    )
    assert r.status_code == 200
    assert r.json()["body"] == "korrigiert"
    assert fake_service.comment_write_args == {
        "comment_id": cid,
        "actor": "admin",
        "viewer_sub": "admin",
        "viewer_is_applicant": False,
        "can_manage": False,
    }


def test_patch_comment_sets_can_manage_for_manager(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "application.read", "application.manage")
    r = client.patch(
        f"/api/applications/{uuid4()}/comments/{uuid4()}", json={"body": "x"}
    )
    assert r.status_code == 200
    assert fake_service.comment_write_args is not None
    assert fake_service.comment_write_args["can_manage"] is True


def test_patch_comment_applicant_identity(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    app_id = uuid4()
    _as_applicant(app, app_id, "view")
    r = client.patch(f"/api/applications/{app_id}/comments/{uuid4()}", json={"body": "y"})
    assert r.status_code == 200
    assert fake_service.comment_write_args is not None
    assert fake_service.comment_write_args["viewer_is_applicant"] is True
    assert fake_service.comment_write_args["viewer_sub"] is None
    assert fake_service.comment_write_args["can_manage"] is False


def test_patch_comment_requires_read_access_403(app: FastAPI, client: TestClient) -> None:
    """A magic link for ANOTHER application gives no access to these comments."""
    _as_applicant(app, uuid4(), "view")
    r = client.patch(f"/api/applications/{uuid4()}/comments/{uuid4()}", json={"body": "x"})
    assert r.status_code == 403


def test_patch_comment_requires_auth_401(client: TestClient) -> None:
    r = client.patch(f"/api/applications/{uuid4()}/comments/{uuid4()}", json={"body": "x"})
    assert r.status_code == 401


def test_patch_comment_empty_body_422(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "application.read")
    r = client.patch(f"/api/applications/{uuid4()}/comments/{uuid4()}", json={"body": ""})
    assert r.status_code == 422


def test_delete_comment_204(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "application.read")
    cid = uuid4()
    r = client.delete(f"/api/applications/{uuid4()}/comments/{cid}")
    assert r.status_code == 204
    assert fake_service.comment_write_args is not None
    assert fake_service.comment_write_args["comment_id"] == cid


def test_delete_comment_requires_read_access_403(app: FastAPI, client: TestClient) -> None:
    _as_applicant(app, uuid4(), "view")
    r = client.delete(f"/api/applications/{uuid4()}/comments/{uuid4()}")
    assert r.status_code == 403


def test_delete_comment_requires_auth_401(client: TestClient) -> None:
    assert (
        client.delete(f"/api/applications/{uuid4()}/comments/{uuid4()}").status_code == 401
    )


# PATCH /applications/{id}/applicant: application.manage, principal only.


def test_patch_applicant_requires_auth_401(client: TestClient) -> None:
    r = client.patch(f"/api/applications/{uuid4()}/applicant", json={"name": "X"})
    assert r.status_code == 401


def test_patch_applicant_rejects_the_magic_link_applicant(
    app: FastAPI, client: TestClient
) -> None:
    """A magic-link holder must not repoint the address the link is delivered to."""
    aid = uuid4()
    _as_applicant(app, aid)
    r = client.patch(f"/api/applications/{aid}/applicant", json={"email": "new@x.de"})
    assert r.status_code == 401
    assert r.headers["content-type"] == "application/problem+json"


def test_patch_applicant_missing_perm_403(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "application.read")
    r = client.patch(f"/api/applications/{uuid4()}/applicant", json={"name": "X"})
    assert r.status_code == 403


def test_patch_applicant_ok(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "application.manage")
    aid = uuid4()
    r = client.patch(
        f"/api/applications/{aid}/applicant",
        json={"email": "alice@x.de", "name": "Alice"},
    )
    assert r.status_code == 200
    assert r.json() == {"email": "alice@x.de", "name": "Alice", "anonymized": False}
    assert fake_service.applicant_args == (aid, "alice@x.de", "Alice", "admin")


def test_patch_applicant_rejects_a_malformed_email_422(
    app: FastAPI, client: TestClient
) -> None:
    _as_principal(app, "application.manage")
    r = client.patch(f"/api/applications/{uuid4()}/applicant", json={"email": "nope"})
    assert r.status_code == 422
    assert r.headers["content-type"] == "application/problem+json"
