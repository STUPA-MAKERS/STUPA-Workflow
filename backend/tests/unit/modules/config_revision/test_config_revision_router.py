"""Unit-Verdrahtung + RBAC der config_revision-/Revert-Router (ohne DB).

``get_current_principal`` + die Service-Dependency werden überschrieben; die schweren
Pfade (``reapply_snapshot`` / ``RevertService``) sind gemockt — getestet wird die
Router-Logik (Permission-Gating, 404, Response-Mapping), nicht die DB-Mutation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.config_revision.models import ConfigRevision
from app.modules.config_revision.revert import RevertResult
from app.modules.config_revision.router import get_service


def _principal(*perms: str, admin: bool = False) -> Principal:
    return Principal(
        sub="kc|admin",
        roles=["admin"] if admin else [],
        permissions=set(perms),
    )


def _rev(entity_type: str = "flow", version: int = 2, **kw: Any) -> ConfigRevision:
    row = ConfigRevision(entity_type=entity_type, entity_id="global", version=version, **kw)
    row.id = uuid.uuid4()
    row.at = datetime(2026, 6, 10, tzinfo=UTC)
    return row


class _FakeService:
    def __init__(
        self, *, revisions: list[ConfigRevision] | None = None, get: Any = None,
        diff: dict[str, Any] | None = None,
    ) -> None:
        # ``session`` wird vom List-Handler an AuditService.resolve_actor_names gereicht;
        # bei ``created_by=None`` macht das keinen DB-Zugriff (Kurzschluss).
        from tests._support.auth_fakes import fake_session

        self.session = fake_session()
        self._revisions = revisions or []
        self._get = get
        self._diff = diff or {"added": {}, "removed": {}, "changed": {}}

    async def list_for(self, _et: str, _eid: str) -> list[ConfigRevision]:
        return self._revisions

    async def get(self, _rid: Any) -> Any:
        return self._get

    async def diff(self, _rev: ConfigRevision) -> dict[str, Any]:
        return self._diff


def _client(principal: Principal, service: _FakeService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_service] = lambda: service
    return TestClient(app)


# --------------------------------------------------------------------------- #
# GET /admin/config-revisions  (Sidebar-Feed)
# --------------------------------------------------------------------------- #
def test_list_requires_a_readable_permission() -> None:
    client = _client(_principal(), _FakeService())
    r = client.get(
        "/api/admin/config-revisions",
        params={"entityType": "flow", "entityId": "global"},
    )
    assert r.status_code == 403


def test_list_returns_revisions_marking_head_current() -> None:
    revs = [_rev(version=3, created_by=None), _rev(version=2, created_by=None)]
    client = _client(_principal("audit.read"), _FakeService(revisions=revs))
    r = client.get(
        "/api/admin/config-revisions",
        params={"entityType": "flow", "entityId": "global"},
    )
    assert r.status_code == 200
    body = r.json()
    assert [x["version"] for x in body] == [3, 2]
    assert body[0]["isCurrent"] is True
    assert body[1]["isCurrent"] is False


# --------------------------------------------------------------------------- #
# GET /admin/config-revisions/{id}/diff
# --------------------------------------------------------------------------- #
def test_diff_404_when_revision_missing() -> None:
    client = _client(_principal("audit.read"), _FakeService(get=None))
    r = client.get(f"/api/admin/config-revisions/{uuid.uuid4()}/diff")
    assert r.status_code == 404


def test_diff_returns_field_diff() -> None:
    rev = _rev(created_by=None)
    diff = {"added": {}, "removed": {}, "changed": {"state:s": {"old": "a", "new": "b"}}}
    client = _client(_principal("flow.configure"), _FakeService(get=rev, diff=diff))
    r = client.get(f"/api/admin/config-revisions/{rev.id}/diff")
    assert r.status_code == 200
    assert r.json()["diff"]["changed"]["state:s"]["new"] == "b"


# --------------------------------------------------------------------------- #
# POST /admin/config-revisions/{id}/restore
# --------------------------------------------------------------------------- #
def test_restore_404_when_revision_missing() -> None:
    client = _client(_principal(admin=True), _FakeService(get=None))
    r = client.post(f"/api/admin/config-revisions/{uuid.uuid4()}/restore")
    assert r.status_code == 404


def test_restore_403_without_entity_permission() -> None:
    rev = _rev(entity_type="flow", created_by=None)
    # Hat audit.read, aber NICHT flow.configure → Restore verweigert.
    client = _client(_principal("audit.read"), _FakeService(get=rev))
    r = client.post(f"/api/admin/config-revisions/{rev.id}/restore")
    assert r.status_code == 403


def test_restore_calls_reapply_with_entity_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    rev = _rev(entity_type="flow", created_by=None)
    calls: list[dict[str, Any]] = []

    async def _fake_reapply(_session: Any, **kw: Any) -> None:
        calls.append(kw)

    monkeypatch.setattr(
        "app.modules.config_revision.router.reapply_snapshot", _fake_reapply
    )
    client = _client(_principal("flow.configure"), _FakeService(get=rev))
    r = client.post(f"/api/admin/config-revisions/{rev.id}/restore")
    assert r.status_code == 204
    assert calls and calls[0]["entity_type"] == "flow"


# --------------------------------------------------------------------------- #
# POST /admin/audit/{id}/revert
# --------------------------------------------------------------------------- #
def test_audit_revert_requires_audit_revert_permission() -> None:
    app = create_app()
    app.dependency_overrides[get_current_principal] = lambda: _principal("audit.read")
    client = TestClient(app)
    r = client.post("/api/admin/audit/7/revert")
    assert r.status_code == 403


def test_audit_revert_delegates_to_revert_service(monkeypatch: pytest.MonkeyPatch) -> None:
    # #AUD-018: der Router reicht den Principal als 3. Argument durch, damit der
    # RevertService die *granulare* Permission des Original-Vorgangs re-asserten kann.
    seen: list[Principal | None] = []

    class _FakeRevert:
        def __init__(self, _session: Any) -> None: ...

        async def revert(
            self, entry_id: int, _actor: str, principal: Principal | None = None
        ) -> RevertResult:
            seen.append(principal)
            return RevertResult(entity_type="flow", entity_id="global", reverted_audit_id=entry_id)

    monkeypatch.setattr("app.modules.audit.router.RevertService", _FakeRevert)
    app = create_app()
    # Happy-Path: audit.revert (Router-Gate) + die granulare flow.configure (AUD-018).
    app.dependency_overrides[get_current_principal] = lambda: _principal(
        "audit.revert", "flow.configure"
    )
    client = TestClient(app)
    r = client.post("/api/admin/audit/7/revert")
    assert r.status_code == 200
    body = r.json()
    assert body["revertedAuditId"] == 7
    assert body["entityType"] == "flow"
    # delegiert an den RevertService UND reicht den Principal für die Re-Assertion durch.
    assert seen and seen[0] is not None
    assert seen[0].has("flow.configure")
