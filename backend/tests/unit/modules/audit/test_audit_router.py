"""Audit router tests (T-23, api.md `/admin/audit`): wiring and RBAC without a database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from app.deps import get_current_principal
from app.main import create_app
from app.modules.audit.models import AuditEntry, AuditVerification
from app.modules.audit.router import get_audit_service
from app.modules.audit.service import ChainVerification
from app.modules.auth.principal import Principal
from app.shared.errors import ConflictError, RateLimitedError

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
        self.cursor_kwargs: dict[str, Any] | None = None
        self.items: list[AuditEntry] = []
        self.has_more = False
        self.names: dict[str, str | None] = {}
        self.target_labels: dict[tuple[str, str], str] = {}
        self.data_ids: dict[str, str] = {}
        self.actors: list[tuple[str, str | None]] = []
        self.verification = ChainVerification(valid=True, checked=0)
        self.revertable: dict[int, bool] = {}
        self.latest: AuditVerification | None = None
        self.stored: list[tuple[str, str | None]] = []
        self.refuse: Exception | None = None

    async def query_cursor(self, **kwargs: Any) -> tuple[list[AuditEntry], bool]:
        self.cursor_kwargs = kwargs
        return self.items, self.has_more

    async def revertable_flags(self, entries: list[AuditEntry]) -> dict[int, bool]:
        return self.revertable

    async def resolve_actor_names(
        self, subs: list[str | None]
    ) -> dict[str, str | None]:
        return self.names

    async def resolve_target_labels(
        self, targets: list[tuple[str | None, str | None]]
    ) -> dict[tuple[str, str], str]:
        return self.target_labels

    async def resolve_data_ids(
        self, data_dicts: list[dict[str, Any] | None]
    ) -> dict[str, str]:
        return self.data_ids

    async def list_actors(self) -> list[tuple[str, str | None]]:
        return self.actors

    async def verify_chain(self) -> ChainVerification:
        return self.verification

    async def run_manual_verification(self, *, triggered_by: str) -> AuditVerification:
        if self.refuse is not None:
            raise self.refuse
        trigger = "manual"
        self.stored.append((trigger, triggered_by))
        return AuditVerification(
            id=uuid.UUID(int=1),
            started_at=_AT,
            finished_at=_AT,
            valid=self.verification.valid,
            checked=self.verification.checked,
            broken_at=self.verification.broken_at,
            reason=self.verification.reason,
            trigger=trigger,
            triggered_by=triggered_by,
        )

    async def latest_verification(self) -> AuditVerification | None:
        return self.latest


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


def test_list_returns_entries_with_hex_hashes_and_cursor() -> None:
    service = _FakeService()
    service.items = [_entry(2, prev=bytes([1]) * 32), _entry(1, prev=None)]
    service.has_more = True
    service.names = {"admin-1": "Admin One"}
    service.revertable = {2: True, 1: False}
    client = _client(service, _principal("audit.read"))
    resp = client.get("/api/admin/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["hasMore"] is True
    assert body["nextCursor"] == 1  # id of last item
    first, second = body["items"]
    assert first["hash"] == "02" * 32
    assert first["prevHash"] == "01" * 32
    assert first["targetType"] == "application"
    assert first["actorName"] == "Admin One"  # the sub resolves to a display name
    assert first["revertable"] is True  # passed through by the router
    assert second["prevHash"] is None  # Genesis
    assert second["revertable"] is False


def test_list_no_more_has_null_cursor() -> None:
    service = _FakeService()
    service.items = [_entry(1, prev=None)]
    service.has_more = False
    client = _client(service, _principal("audit.read"))
    body = client.get("/api/admin/audit").json()
    assert body["hasMore"] is False
    assert body["nextCursor"] is None


def test_list_passes_cursor_filters_to_service() -> None:
    service = _FakeService()
    client = _client(service, _principal("audit.read"))
    resp = client.get(
        "/api/admin/audit",
        params={
            "action": "login",
            "actor": "u-1",
            "before": 42,
            "limit": 10,
        },
    )
    assert resp.status_code == 200
    assert service.cursor_kwargs is not None
    assert service.cursor_kwargs["action"] == "login"
    assert service.cursor_kwargs["actor"] == "u-1"
    assert service.cursor_kwargs["before"] == 42
    assert service.cursor_kwargs["limit"] == 10


def test_list_rejects_naive_since_with_422() -> None:
    # #AUD-034: a naive since or until value must not reach the timestamptz query.
    # The asyncpg driver raises a DataError there, which gives 500. AwareDatetime
    # rejects the value with 422 instead.
    service = _FakeService()
    client = _client(service, _principal("audit.read"))
    resp = client.get("/api/admin/audit", params={"since": "2026-06-01T00:00:00"})
    assert resp.status_code == 422
    assert service.cursor_kwargs is None  # the query is never reached


def test_list_rejects_naive_until_with_422() -> None:
    service = _FakeService()
    client = _client(service, _principal("audit.read"))
    resp = client.get("/api/admin/audit", params={"until": "2026-06-01T00:00:00"})
    assert resp.status_code == 422
    assert service.cursor_kwargs is None


def test_list_accepts_aware_since_until() -> None:
    service = _FakeService()
    client = _client(service, _principal("audit.read"))
    resp = client.get(
        "/api/admin/audit",
        params={
            "since": "2026-06-01T00:00:00+00:00",
            "until": "2026-06-30T23:59:59Z",
        },
    )
    assert resp.status_code == 200
    assert service.cursor_kwargs is not None
    assert service.cursor_kwargs["since"].tzinfo is not None
    assert service.cursor_kwargs["until"].tzinfo is not None


def test_actors_endpoint_lists_distinct_actors() -> None:
    service = _FakeService()
    service.actors = [("u-1", "User One"), ("sys", None)]
    client = _client(service, _principal("audit.read"))
    resp = client.get("/api/admin/audit/actors")
    assert resp.status_code == 200
    assert resp.json() == [
        {"sub": "u-1", "name": "User One"},
        {"sub": "sys", "name": None},
    ]


def test_actors_requires_permission() -> None:
    client = _client(_FakeService(), _principal())
    assert client.get("/api/admin/audit/actors").status_code == 403


def test_verify_endpoint_ok() -> None:
    service = _FakeService()
    service.verification = ChainVerification(valid=True, checked=3)
    client = _client(service, _principal("audit.verify"))
    resp = client.get("/api/admin/audit/verify")
    assert resp.status_code == 200
    assert resp.json() == {"valid": True, "checked": 3, "brokenAt": None, "reason": None}


def test_verify_endpoint_reports_break() -> None:
    service = _FakeService()
    service.verification = ChainVerification(
        valid=False, checked=1, broken_at=2, reason="hash_mismatch"
    )
    client = _client(service, _principal("audit.verify"))
    resp = client.get("/api/admin/audit/verify")
    body = resp.json()
    assert body["valid"] is False
    assert body["brokenAt"] == 2
    assert body["reason"] == "hash_mismatch"


def test_verify_requires_permission() -> None:
    client = _client(_FakeService(), _principal())
    assert client.get("/api/admin/audit/verify").status_code == 403


def test_post_verify_stores_a_manual_check() -> None:
    service = _FakeService()
    service.verification = ChainVerification(
        valid=False, checked=4, broken_at=5, reason="hash_mismatch"
    )
    client = _client(service, _principal("audit.verify"))
    resp = client.post("/api/admin/audit/verify")
    assert resp.status_code == 200
    assert service.stored == [("manual", "admin-1")]
    assert resp.json() == {
        "id": str(uuid.UUID(int=1)),
        "startedAt": "2026-06-06T12:00:00Z",
        "finishedAt": "2026-06-06T12:00:00Z",
        "valid": False,
        "checked": 4,
        "brokenAt": 5,
        "reason": "hash_mismatch",
        "trigger": "manual",
        "triggeredBy": "admin-1",
    }


def test_post_verify_requires_audit_verify() -> None:
    service = _FakeService()
    client = _client(service, _principal("audit.read"))
    resp = client.post("/api/admin/audit/verify")
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert service.stored == []


def test_post_verify_requires_authentication() -> None:
    assert _client(_FakeService(), None).post("/api/admin/audit/verify").status_code == 401


def test_post_verify_while_a_check_runs_is_409() -> None:
    service = _FakeService()
    service.refuse = ConflictError("busy", code="audit_verify_running")
    resp = _client(service, _principal("audit.verify")).post("/api/admin/audit/verify")
    assert resp.status_code == 409
    assert resp.json()["code"] == "audit_verify_running"
    assert service.stored == []


def test_post_verify_inside_the_cooldown_is_429() -> None:
    service = _FakeService()
    service.refuse = RateLimitedError(
        "too soon", retry_after=120, code="audit_verify_cooldown"
    )
    resp = _client(service, _principal("audit.verify")).post("/api/admin/audit/verify")
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "120"
    assert resp.json()["code"] == "audit_verify_cooldown"
    assert service.stored == []


def test_latest_verification_returns_the_stored_row() -> None:
    service = _FakeService()
    service.latest = AuditVerification(
        id=uuid.UUID(int=2),
        started_at=_AT,
        finished_at=_AT,
        valid=True,
        checked=12,
        trigger="cron",
    )
    client = _client(service, _principal("audit.read"))
    resp = client.get("/api/admin/audit/verify/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["checked"] == 12
    assert body["trigger"] == "cron"
    assert body["triggeredBy"] is None


def test_latest_verification_is_null_before_the_first_check() -> None:
    client = _client(_FakeService(), _principal("audit.read"))
    resp = client.get("/api/admin/audit/verify/latest")
    assert resp.status_code == 200
    assert resp.json() is None


def test_latest_verification_requires_audit_read() -> None:
    # audit.verify alone does not open the stored result; the tile reads with audit.read.
    client = _client(_FakeService(), _principal("audit.verify"))
    assert client.get("/api/admin/audit/verify/latest").status_code == 403
