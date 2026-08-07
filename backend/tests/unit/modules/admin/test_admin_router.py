"""Router tests for admin and config (T-24): endpoint wiring and RBAC with a faked service.

These tests prove four things.

1. Each area keeps its own permission gate: admin.config, admin.roles, webhook.manage.
2. The DTOs serialize to camelCase.
3. The site-config read returns ``{version, active, draft, hasDraftChanges}`` for the
   frontend, and the public read needs no auth.
4. Every mutation with a body declares ``400`` as problem+json (be-contract).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.admin.branding import Branding
from app.modules.admin.router import (
    get_config_service,
    get_gremium_role_service,
    get_site_config_service,
)
from app.modules.admin.schemas import (
    ApplicationTypeOut,
    FlowVersionOut,
    GremiumMailRecipients,
    GremiumMembershipOut,
    GremiumOut,
    GremiumRoleOut,
    GroupMappingOut,
    PrincipalOut,
    PublicSiteConfigOut,
    RoleAssignmentOut,
    RoleOut,
    SiteConfigOut,
    WebhookOut,
)
from app.shared.errors import ConflictError, NotFoundError

_ALL_PERMS = {
    "admin.site",
    "admin.gremien",
    "admin.types",
    "admin.types_delete",
    "admin.roles",
    "admin.users",
    "admin.group_mappings",
    "admin.gremium_roles",
    "admin.delegations",
    "admin.deadlines",
    "webhook.manage",
}


class _FakeConfig:
    async def list_gremien(self):
        return [
            GremiumOut(
                id=uuid4(),
                name="StuPa",
                slug="stupa",
                cd_variant_id=None,
                default_lang="de",
                allow_vote_delegation=False,
            )
        ]

    async def create_gremium(self, payload, actor):  # noqa: ANN001
        return GremiumOut(
            id=uuid4(),
            name=payload.name,
            slug=payload.slug,
            cd_variant_id=payload.cd_variant_id,
            default_lang=payload.default_lang,
            allow_vote_delegation=payload.allow_vote_delegation,
        )

    async def update_gremium(self, gremium_id, payload, actor):  # noqa: ANN001
        if str(gremium_id).startswith("00000000"):
            raise NotFoundError("nope")
        return GremiumOut(
            id=gremium_id,
            name=payload.name or "X",
            slug="stupa",
            cd_variant_id=None,
            default_lang="de",
            allow_vote_delegation=False,
        )

    async def get_gremium_mail_recipients(self, gremium_id):  # noqa: ANN001
        return GremiumMailRecipients(recipients=["list@x.de"])

    async def set_gremium_mail_recipients(self, gremium_id, payload, actor):  # noqa: ANN001
        self.mail_recipients = list(payload.recipients)
        return payload

    async def list_application_types(self):
        return [
            ApplicationTypeOut(
                id=uuid4(),
                gremium_id=None,
                key="grant",
                name_i18n={"de": "Antrag"},
                has_budget=False,
                comparison_offers=None,
                active_form_version_id=None,
            )
        ]

    async def create_application_type(self, payload, actor):  # noqa: ANN001
        return ApplicationTypeOut(
            id=uuid4(),
            gremium_id=payload.gremium_id,
            key=payload.key,
            name_i18n=payload.name_i18n,
            has_budget=payload.has_budget,
            comparison_offers=None,
            active_form_version_id=None,
        )

    async def update_application_type(self, type_id, payload, actor):  # noqa: ANN001
        return ApplicationTypeOut(
            id=type_id,
            gremium_id=None,
            key="grant",
            name_i18n={"de": "x"},
            has_budget=True,
            comparison_offers=None,
            active_form_version_id=None,
        )

    async def delete_application_type(self, type_id, actor):  # noqa: ANN001
        return None

    async def list_roles(self):
        return [
            RoleOut(
                id=uuid4(),
                key="admin",
                label={"de": "Admin"},
                permissions=["admin.gremien"],
            )
        ]

    async def get_active_global_flow(self):
        return None  # an empty flow is enough for the gate tests (#5-2)

    async def create_global_flow_version(self, payload, actor):  # noqa: ANN001
        return FlowVersionOut(id=uuid4(), version=2, active=True)

    async def create_role(self, payload, actor):  # noqa: ANN001
        return RoleOut(
            id=uuid4(),
            key=payload.key,
            label=payload.label,
            permissions=payload.permissions,
        )

    async def update_role(self, role_id, payload, actor):  # noqa: ANN001
        return RoleOut(
            id=role_id,
            key="admin",
            label={"de": "A"},
            permissions=payload.permissions or [],
        )

    async def list_role_assignments(self):
        return []

    async def create_role_assignment(self, payload, actor):  # noqa: ANN001
        return RoleAssignmentOut(
            id=uuid4(),
            principal_id=payload.principal_id,
            role_id=payload.role_id,
            gremium_id=payload.gremium_id,
            granted_by=actor,
            valid_from=payload.valid_from,
            valid_until=payload.valid_until,
            delegate_voting=payload.delegate_voting,
        )

    async def update_role_assignment(self, assignment_id, payload, actor):  # noqa: ANN001
        return RoleAssignmentOut(
            id=assignment_id,
            principal_id=uuid4(),
            role_id=uuid4(),
            gremium_id=None,
            granted_by=actor,
            valid_from=None,
            valid_until=None,
            delegate_voting=True,
        )

    async def delete_role_assignment(self, assignment_id, actor):  # noqa: ANN001
        if str(assignment_id).startswith("00000000"):
            raise NotFoundError("nope")

    async def search_principals(self, query, limit=50):  # noqa: ANN001
        return [
            PrincipalOut(
                id=uuid4(),
                sub="kc|max",
                email="max@x.de",
                display_name="Max",
                last_login="2026-06-07T09:00:00+00:00",
                assignments=[
                    RoleAssignmentOut(
                        id=uuid4(),
                        principal_id=uuid4(),
                        role_id=uuid4(),
                        gremium_id=None,
                        granted_by="admin",
                        valid_from=None,
                        valid_until=None,
                        delegate_voting=False,
                    )
                ]
                if query != "none"
                else [],
            )
        ]

    def list_permissions(self):
        return ["flow.configure", "admin.roles"]

    async def list_group_mappings(self):
        return []

    async def create_group_mapping(self, payload, actor):  # noqa: ANN001
        return GroupMappingOut(
            id=uuid4(),
            oidc_group=payload.oidc_group,
            role_id=payload.role_id,
            gremium_id=payload.gremium_id,
        )

    async def update_group_mapping(self, mapping_id, payload, actor):  # noqa: ANN001
        return GroupMappingOut(id=mapping_id, oidc_group="g", role_id=uuid4(), gremium_id=None)

    async def delete_group_mapping(self, mapping_id, actor):  # noqa: ANN001
        self.deleted_mapping = mapping_id

    async def list_webhooks(self):
        return [
            WebhookOut(
                id=uuid4(),
                name="n8n",
                url="https://h/x",
                events=["status_changed"],
                active=True,
            )
        ]

    async def create_webhook(self, payload, actor):  # noqa: ANN001
        if payload.name == "dup":
            raise ConflictError("exists")
        return WebhookOut(
            id=uuid4(),
            name=payload.name,
            url=payload.url,
            events=payload.events,
            active=payload.active,
        )

    async def update_webhook(self, webhook_id, payload, actor):  # noqa: ANN001
        if str(webhook_id).startswith("00000000"):
            raise NotFoundError("nope")
        return WebhookOut(
            id=webhook_id,
            name="n8n",
            url="https://h/x",
            events=["status_changed"],
            active=False,
        )

    async def delete_webhook(self, webhook_id, actor):  # noqa: ANN001
        if str(webhook_id).startswith("00000000"):
            raise NotFoundError("nope")
        self.deleted_webhook = webhook_id


class _FakeSite:
    def __init__(self) -> None:
        self._active = Branding()
        self._draft = Branding()
        self._has = False
        self._version = 1

    async def get(self):
        return SiteConfigOut(
            version=self._version,
            active=self._active,
            draft=self._draft,
            has_draft_changes=self._has,
        )

    async def put_draft(self, branding, actor):  # noqa: ANN001
        self._draft = branding
        self._has = True
        return await self.get()

    async def activate(self, actor):  # noqa: ANN001
        if not self._has:
            raise ConflictError("no draft")
        self._active = self._draft
        self._version += 1
        self._has = False
        return await self.get()

    async def public(self):
        return PublicSiteConfigOut(version=self._version, branding=self._active)


class _FakeGremiumRoles:
    """Minimal fake for the Gremium roles and memberships (#5-3 gate tests)."""

    async def list_roles(self, gremium_id):  # noqa: ANN001
        return [
            GremiumRoleOut(
                id=uuid4(),
                gremium_id=gremium_id,
                key="member",
                name={"de": "Mitglied"},
                forced=True,
                permissions=[],
            )
        ]

    async def list_memberships(self, gremium_id):  # noqa: ANN001
        return [
            GremiumMembershipOut(
                id=uuid4(),
                principal_id=uuid4(),
                gremium_id=gremium_id,
                gremium_role_id=uuid4(),
                valid_from=None,
                valid_until=None,
            )
        ]

    async def update_membership(self, membership_id, payload, actor):  # noqa: ANN001
        if str(membership_id).startswith("00000000"):
            raise NotFoundError("nope")
        return GremiumMembershipOut(
            id=membership_id,
            principal_id=uuid4(),
            gremium_id=uuid4(),
            gremium_role_id=payload.gremium_role_id or uuid4(),
            valid_from=payload.valid_from,
            valid_until=payload.valid_until,
        )


@pytest.fixture
def app() -> FastAPI:
    application = create_app()
    config, site = _FakeConfig(), _FakeSite()  # one instance per app, so the state survives
    application.dependency_overrides[get_config_service] = lambda: config
    application.dependency_overrides[get_site_config_service] = lambda: site
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as(app: FastAPI, perms: set[str]) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions=perms
    )


def _as_admin(app: FastAPI) -> None:
    _as(app, set(_ALL_PERMS))


def test_requires_auth_401(client: TestClient) -> None:
    assert client.get("/api/admin/gremien").status_code == 401


def test_forbidden_without_permission(app: FastAPI, client: TestClient) -> None:
    _as(app, set())
    r = client.get("/api/admin/gremien")
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


def test_roles_write_needs_admin_roles_not_just_config(app: FastAPI, client: TestClient) -> None:
    _as(app, {"admin.types"})  # may read config areas, but must not write roles
    assert client.get("/api/admin/roles").status_code == 200
    r = client.post("/api/admin/roles", json={"key": "x", "label": {}, "permissions": []})
    assert r.status_code == 403


def test_webhooks_need_webhook_manage(app: FastAPI, client: TestClient) -> None:
    _as(app, {"admin.site", "admin.gremien", "admin.types", "admin.roles"})
    assert client.get("/api/admin/webhooks").status_code == 403


def test_config_schemas_includes_branding(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.get("/api/admin/config-schemas")
    assert r.status_code == 200
    body = r.json()
    assert "Branding" in body and "FlowGraph" in body


def test_list_create_update_gremium(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    assert client.get("/api/admin/gremien").json()[0]["cdVariantId"] is None
    r = client.post("/api/admin/gremien", json={"name": "AStA", "slug": "asta"})
    assert r.status_code == 201 and r.json()["defaultLang"] == "de"
    patched = client.patch(f"/api/admin/gremien/{uuid4()}", json={"name": "Neu"})
    assert patched.status_code == 200


def test_update_gremium_404(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.patch("/api/admin/gremien/00000000-0000-0000-0000-000000000000", json={"name": "x"})
    assert r.status_code == 404


def test_gremium_mail_recipients_roundtrip(app: FastAPI, client: TestClient) -> None:
    """#protocol-recipients: GET returns the list. PUT replaces it with validated addresses."""
    _as_admin(app)
    gid = uuid4()
    r = client.get(f"/api/admin/gremien/{gid}/mail-recipients")
    assert r.status_code == 200 and r.json() == {"recipients": ["list@x.de"]}
    r = client.put(
        f"/api/admin/gremien/{gid}/mail-recipients",
        json={"recipients": ["a@x.de", " a@X.de ", "b@y.org"]},
    )
    assert r.status_code == 200
    # The server drops case-insensitive duplicates and keeps the order.
    assert r.json() == {"recipients": ["a@x.de", "b@y.org"]}


def test_gremium_mail_recipients_rejects_implausible_address(
    app: FastAPI, client: TestClient
) -> None:
    _as_admin(app)
    r = client.put(
        f"/api/admin/gremien/{uuid4()}/mail-recipients",
        json={"recipients": ["not-an-email"]},
    )
    assert r.status_code == 422


def test_gremien_authed_list_without_admin_perm(app: FastAPI, client: TestClient) -> None:
    """#68: every logged-in principal may read `GET /api/gremien`.

    The endpoint feeds a dropdown, so it also works without ``admin.config``.
    """
    _as(app, set())  # logged in, but without any permission
    r = client.get("/api/gremien")
    assert r.status_code == 200
    assert r.json()[0]["cdVariantId"] is None


def test_gremien_authed_requires_auth_401(client: TestClient) -> None:
    assert client.get("/api/gremien").status_code == 401


def test_application_types_crud(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    assert client.get("/api/admin/application-types").json()[0]["key"] == "grant"
    r = client.post(
        "/api/admin/application-types",
        json={"key": "grant", "nameI18n": {"de": "Antrag"}},
    )
    assert r.status_code == 201 and r.json()["hasBudget"] is False
    patched = client.patch(f"/api/admin/application-types/{uuid4()}", json={"hasBudget": True})
    assert patched.status_code == 200


def test_application_type_delete_requires_own_permission(
    app: FastAPI, client: TestClient
) -> None:
    """The delete needs the separate permission admin.types_delete, not admin.types."""
    type_id = uuid4()
    # admin.types alone covers create and update. It does NOT allow the delete.
    _as(app, {"admin.types"})
    assert client.delete(f"/api/admin/application-types/{type_id}").status_code == 403
    # With the separate delete permission the call returns 204.
    _as(app, {"admin.types_delete"})
    assert client.delete(f"/api/admin/application-types/{type_id}").status_code == 204


def test_roles_and_assignments_and_mappings(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    assert client.get("/api/admin/roles").json()[0]["permissions"] == ["admin.gremien"]
    created = client.post(
        "/api/admin/roles",
        json={"key": "r", "label": {"de": "R"}, "permissions": ["vote.cast"]},
    )
    assert created.status_code == 201
    patched = client.patch(f"/api/admin/roles/{uuid4()}", json={"permissions": ["audit.read"]})
    assert patched.status_code == 200
    pid, rid = str(uuid4()), str(uuid4())
    r = client.post(
        "/api/admin/role-assignments",
        json={"principalId": pid, "roleId": rid, "delegateVoting": True},
    )
    assert r.status_code == 201 and r.json()["delegateVoting"] is True
    upd = client.patch(f"/api/admin/role-assignments/{uuid4()}", json={"delegateVoting": True})
    assert upd.status_code == 200
    assert client.get("/api/admin/role-assignments").status_code == 200
    gm = client.post("/api/admin/group-mappings", json={"oidcGroup": "fsr", "roleId": rid})
    assert gm.status_code == 201 and gm.json()["oidcGroup"] == "fsr"
    gmu = client.patch(f"/api/admin/group-mappings/{uuid4()}", json={"oidcGroup": "x"})
    assert gmu.status_code == 200
    assert client.get("/api/admin/group-mappings").status_code == 200


def test_list_principals_camelcase(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.get("/api/admin/principals?q=max")
    assert r.status_code == 200
    body = r.json()[0]
    assert body["sub"] == "kc|max"
    assert body["displayName"] == "Max"
    assert body["lastLogin"] == "2026-06-07T09:00:00+00:00"
    assert len(body["assignments"]) == 1


def test_list_principals_needs_admin_roles(app: FastAPI, client: TestClient) -> None:
    _as(app, {"admin.types"})  # an area admin without gremien or roles must not read this
    assert client.get("/api/admin/principals").status_code == 403


def test_gremien_admin_can_manage_members_without_admin_roles(
    app: FastAPI, client: TestClient
) -> None:
    """#5-3: the members subpage runs under admin.gremien.

    A principal without admin.roles must still read the memberships, the Gremium roles for
    the role dropdown and the principals for the name typeahead. Without these reads the
    table stays empty.
    """
    app.dependency_overrides[get_gremium_role_service] = lambda: _FakeGremiumRoles()
    _as(app, {"admin.gremien"})  # deliberately WITHOUT admin.roles
    gid = uuid4()
    assert client.get(f"/api/admin/gremien/{gid}/memberships").status_code == 200
    assert client.get(f"/api/admin/gremien/{gid}/roles").status_code == 200
    assert client.get("/api/admin/principals").status_code == 200


def test_members_endpoints_forbidden_for_unrelated_area(app: FastAPI, client: TestClient) -> None:
    """admin.types is neither gremien nor roles, so the member reads stay forbidden."""
    app.dependency_overrides[get_gremium_role_service] = lambda: _FakeGremiumRoles()
    _as(app, {"admin.types"})
    gid = uuid4()
    assert client.get(f"/api/admin/gremien/{gid}/memberships").status_code == 403
    assert client.get(f"/api/admin/gremien/{gid}/roles").status_code == 403


def test_flow_editor_can_read_its_sources_without_admin_types(
    app: FastAPI, client: TestClient
) -> None:
    """#5-2: the flow editor runs under flow.configure.

    The editor reads the global flow, the roles and the webhooks as option sources. These
    reads must work without admin.types, admin.roles and webhook.manage. Otherwise the
    editor starts empty.
    """
    _as(app, {"flow.configure"})
    assert client.get("/api/admin/flow-versions/global").status_code == 200
    assert client.get("/api/admin/roles").status_code == 200
    assert client.get("/api/admin/webhooks").status_code == 200


_FLOW_GRAPH = {"graph": {"states": [], "transitions": [], "layout": None}}


def test_flow_save_refuses_flow_configure(app: FastAPI, client: TestClient) -> None:
    """A transition action mails an arbitrary address, so the save stays on admin.types."""
    _as(app, {"flow.configure"})
    r = client.post("/api/admin/flow-versions/global", json=_FLOW_GRAPH)
    assert r.status_code == 403


def test_flow_save_accepts_admin_types(app: FastAPI, client: TestClient) -> None:
    _as(app, {"admin.types"})
    r = client.post("/api/admin/flow-versions/global", json=_FLOW_GRAPH)
    assert r.status_code == 201


def test_flow_save_forbidden_without_either(app: FastAPI, client: TestClient) -> None:
    """#g7: neither key means 403 as problem+json. A read-only key is not enough."""
    _as(app, {"budget.structure"})
    r = client.post("/api/admin/flow-versions/global", json=_FLOW_GRAPH)
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "forbidden"


def test_global_flow_readable_by_budget_structure(app: FastAPI, client: TestClient) -> None:
    """#5-2: the budget tree (budget.structure) reads the global flow.

    The tree needs the flow for the status dropdowns (accepted and denied).
    """
    _as(app, {"budget.structure"})
    assert client.get("/api/admin/flow-versions/global").status_code == 200


def test_application_types_readable_by_form_configure(app: FastAPI, client: TestClient) -> None:
    """#5-2: the form editor (form.configure) reads the application-type list."""
    _as(app, {"form.configure"})
    assert client.get("/api/admin/application-types").status_code == 200


def test_editor_source_reads_still_gated_for_unrelated_area(
    app: FastAPI, client: TestClient
) -> None:
    """admin.notifications covers none of these areas, so each read stays 403."""
    _as(app, {"admin.notifications"})
    assert client.get("/api/admin/flow-versions/global").status_code == 403
    assert client.get("/api/admin/webhooks").status_code == 403
    assert client.get("/api/admin/application-types").status_code == 403
    assert client.get("/api/admin/roles").status_code == 403


def test_list_permissions_catalogue(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.get("/api/admin/permissions")
    assert r.status_code == 200
    assert "flow.configure" in r.json()


def test_permissions_need_admin_roles(app: FastAPI, client: TestClient) -> None:
    _as(app, {"admin.types"})
    assert client.get("/api/admin/permissions").status_code == 403


def test_revoke_role_assignment_204_and_404(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    ok = client.delete(f"/api/admin/role-assignments/{uuid4()}")
    assert ok.status_code == 204
    missing = client.delete("/api/admin/role-assignments/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404


def test_revoke_needs_admin_roles(app: FastAPI, client: TestClient) -> None:
    _as(app, {"admin.types"})
    assert client.delete(f"/api/admin/role-assignments/{uuid4()}").status_code == 403


def test_group_mapping_delete_204_and_gate(app: FastAPI, client: TestClient) -> None:
    """#5-4: admin.roles may now delete a group mapping."""
    _as_admin(app)
    assert client.delete(f"/api/admin/group-mappings/{uuid4()}").status_code == 204
    _as(app, {"admin.types"})  # the wrong area permission, so 403
    assert client.delete(f"/api/admin/group-mappings/{uuid4()}").status_code == 403


def test_webhooks_crud_and_validation(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    assert client.get("/api/admin/webhooks").json()[0]["name"] == "n8n"
    ok = client.post(
        "/api/admin/webhooks",
        json={"name": "h", "url": "https://h/x", "events": ["status_changed"]},
    )
    assert ok.status_code == 201
    # A non-http URL fails the schema with 422.
    bad = client.post(
        "/api/admin/webhooks",
        json={"name": "h", "url": "ftp://h/x", "events": ["status_changed"]},
    )
    assert bad.status_code == 422
    # The frontend posts the full object with an empty id. The server ignores that id.
    withid = client.post(
        "/api/admin/webhooks",
        json={
            "id": "",
            "name": "h",
            "url": "https://h/y",
            "events": ["vote_closed"],
            "active": True,
        },
    )
    assert withid.status_code == 201
    patched = client.patch(f"/api/admin/webhooks/{uuid4()}", json={"active": False})
    assert patched.status_code == 200


def test_webhook_delete_204_404_and_gate(app: FastAPI, client: TestClient) -> None:
    """DELETE /admin/webhooks/{id}: 204 happy path, 404 unknown, 403 without the gate."""
    assert client.delete(f"/api/admin/webhooks/{uuid4()}").status_code == 401
    _as_admin(app)
    assert client.delete(f"/api/admin/webhooks/{uuid4()}").status_code == 204
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.delete(f"/api/admin/webhooks/{missing}").status_code == 404
    _as(app, {"admin.gremien"})  # the wrong area permission, so 403
    assert client.delete(f"/api/admin/webhooks/{uuid4()}").status_code == 403


def test_gremium_membership_patch_and_gate(app: FastAPI, client: TestClient) -> None:
    """PATCH /admin/gremium-memberships/{id}: 200, 404, 422 empty body, 403 gate."""
    app.dependency_overrides[get_gremium_role_service] = lambda: _FakeGremiumRoles()
    mid = uuid4()
    assert client.patch(f"/api/admin/gremium-memberships/{mid}", json={}).status_code == 401
    _as_admin(app)
    role_id = uuid4()
    ok = client.patch(
        f"/api/admin/gremium-memberships/{mid}",
        json={"gremiumRoleId": str(role_id), "validUntil": "2027-01-01T00:00:00+00:00"},
    )
    assert ok.status_code == 200
    assert ok.json()["gremiumRoleId"] == str(role_id)
    assert ok.json()["validUntil"] == "2027-01-01T00:00:00+00:00"
    # An empty body sets no field and fails the schema with 422.
    assert client.patch(f"/api/admin/gremium-memberships/{mid}", json={}).status_code == 422
    missing = "00000000-0000-0000-0000-000000000000"
    gone = client.patch(
        f"/api/admin/gremium-memberships/{missing}", json={"validFrom": None}
    )
    assert gone.status_code == 404
    _as(app, {"admin.gremium_roles"})  # the neighbouring area permission is not enough
    assert (
        client.patch(
            f"/api/admin/gremium-memberships/{mid}", json={"validFrom": None}
        ).status_code
        == 403
    )


def test_site_config_draft_activate_cycle(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.get("/api/admin/site-config")
    assert r.status_code == 200
    empty = Branding().model_dump(by_alias=True)
    assert r.json() == {"version": 1, "active": empty, "draft": empty, "hasDraftChanges": False}
    put = client.put("/api/admin/site-config/draft", json={"copyright": {"de": "© 2026"}})
    assert put.status_code == 200 and put.json()["hasDraftChanges"] is True
    act = client.post("/api/admin/site-config/activate")
    assert act.status_code == 200
    body = act.json()
    assert body["version"] == 2 and body["hasDraftChanges"] is False
    assert body["active"]["copyright"] == {"de": "© 2026"}


def test_site_config_draft_rejects_inline_svg_422(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    draft = {
        "logos": {
            "favicon": {
                "url": "data:image/svg+xml;base64,PHN2Zz4=",
                "filename": "f.svg",
                "mime": "image/png",
                "size": 10,
            }
        }
    }
    r = client.put("/api/admin/site-config/draft", json=draft)
    assert r.status_code == 422


def test_activate_without_draft_409(app: FastAPI, client: TestClient) -> None:
    _as_admin(app)
    r = client.post("/api/admin/site-config/activate")
    assert r.status_code == 409


def test_public_site_config_no_auth_and_cache_header(client: TestClient) -> None:
    r = client.get("/api/site-config")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=300"
    assert "branding" in r.json()


def test_mutating_endpoints_declare_400(app: FastAPI) -> None:
    spec = app.openapi()
    cases = [
        ("/api/admin/gremien", "post"),
        ("/api/admin/gremien/{gremium_id}", "patch"),
        ("/api/admin/application-types", "post"),
        ("/api/admin/application-types/{type_id}", "patch"),
        ("/api/admin/roles", "post"),
        ("/api/admin/roles/{role_id}", "patch"),
        ("/api/admin/role-assignments", "post"),
        ("/api/admin/role-assignments/{assignment_id}", "patch"),
        ("/api/admin/group-mappings", "post"),
        ("/api/admin/group-mappings/{mapping_id}", "patch"),
        ("/api/admin/webhooks", "post"),
        ("/api/admin/webhooks/{webhook_id}", "patch"),
        ("/api/admin/site-config/draft", "put"),
        ("/api/admin/site-config/activate", "post"),
    ]
    for path, method in cases:
        responses = spec["paths"][path][method]["responses"]
        assert "400" in responses, f"{method.upper()} {path} missing 400"
        assert list(responses["400"]["content"]) == ["application/problem+json"]
