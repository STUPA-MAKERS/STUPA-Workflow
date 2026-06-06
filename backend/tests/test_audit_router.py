"""TDD: audit-Router (T-23, api.md ``/admin/audit``) — Verdrahtung + RBAC ohne DB."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from app.deps import get_current_principal
from app.main import create_app
from app.modules.audit.models import AuditEntry
from app.modules.audit.router import get_audit_service
from app.modules.audit.service import ChainVerification
from app.modules.auth.principal import Principal
from app.shared.paging import Page

_AT = datetime(2026, 6, 6, 12, 0, 0, tzinfo=UTC)


def _entry(entry_id: int, *, prev: bytes | None) -> AuditEntry:
    return AuditEntry(
        id=entry_id,
        actor="admin-1",
        action="status_change",
        target_type="application",
        target_id="app-1",
        at=_AT,
        data={"toStateId": "s-2"},
        prev_hash=prev,
        hash=bytes([entry_id]) * 32,
    )


class _FakeService:
    def __init__(self) -> None:
        self.query_kwargs: dict[str, Any] | None = None
        self.page: Page[AuditEntry] = Page(items=[], total=0, limit=50, offset=0)
        self.verification = ChainVerification(valid=True, checked=0)

    async def query(self, **kwargs: Any) -> Page[AuditEntry]:
        self.query_kwargs = kwargs
        return self.page

    async def verify_chain(self) -> ChainVerification:
        return self.verification


def _principal(*perms: str) -> Principal:
    return Principal(sub="admin-1", permissions=set(perms))


def _client(service: _FakeService, principal: Principal | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_audit_service] = lambda: service
    app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app)


def test_list_requires_authentication() -> None:
    client = _client(_FakeService(), None)
    resp = client.get("/api/admin/audit")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_list_requires_audit_read_permission() -> None:
    client = _client(_FakeService(), _principal("application.read"))
    assert client.get("/api/admin/audit").status_code == 403


def test_list_returns_entries_with_hex_hashes() -> None:
    service = _FakeService()
    service.page = Page(
        items=[_entry(2, prev=bytes([1]) * 32), _entry(1, prev=None)],
        total=2,
        limit=50,
        offset=0,
    )
    client = _client(service, _principal("audit.read"))
    resp = client.get("/api/admin/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    first, second = body["items"]
    assert first["hash"] == "02" * 32
    assert first["prevHash"] == "01" * 32
    assert first["targetType"] == "application"
    assert second["prevHash"] is None  # Genesis


def test_list_passes_filters_to_service() -> None:
    service = _FakeService()
    client = _client(service, _principal("audit.read"))
    resp = client.get(
        "/api/admin/audit",
        params={
            "action": "login",
            "actor": "u-1",
            "targetType": "application",
            "targetId": "a-1",
            "limit": 10,
            "offset": 5,
        },
    )
    assert resp.status_code == 200
    assert service.query_kwargs is not None
    assert service.query_kwargs["action"] == "login"
    assert service.query_kwargs["actor"] == "u-1"
    assert service.query_kwargs["target_type"] == "application"
    assert service.query_kwargs["target_id"] == "a-1"
    assert service.query_kwargs["limit"] == 10
    assert service.query_kwargs["offset"] == 5


def test_verify_endpoint_ok() -> None:
    service = _FakeService()
    service.verification = ChainVerification(valid=True, checked=3)
    client = _client(service, _principal("audit.read"))
    resp = client.get("/api/admin/audit/verify")
    assert resp.status_code == 200
    assert resp.json() == {"valid": True, "checked": 3, "brokenAt": None, "reason": None}


def test_verify_endpoint_reports_break() -> None:
    service = _FakeService()
    service.verification = ChainVerification(
        valid=False, checked=1, broken_at=2, reason="hash_mismatch"
    )
    client = _client(service, _principal("audit.read"))
    resp = client.get("/api/admin/audit/verify")
    body = resp.json()
    assert body["valid"] is False
    assert body["brokenAt"] == 2
    assert body["reason"] == "hash_mismatch"


def test_verify_requires_permission() -> None:
    client = _client(_FakeService(), _principal())
    assert client.get("/api/admin/audit/verify").status_code == 403
