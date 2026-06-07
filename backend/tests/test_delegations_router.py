"""Router-Tests Delegationen (T-45): Verdrahtung, RBAC-Gate (401), camelCase, Fehler.

Service ist gefaked (Endpunkt-Verhalten, nicht DB). Beweist: 401 ohne Session, 201/
200/204-Statuscodes, camelCase-Serialisierung der DTOs und problem+json bei 403/404.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.delegations.router import get_delegation_service
from app.modules.delegations.schemas import DelegationOut
from app.shared.errors import ForbiddenError, NotFoundError, ValidationProblem


def _out(**over) -> DelegationOut:  # noqa: ANN003
    base = dict(
        id=uuid4(),
        principal_id=uuid4(),
        role_id=uuid4(),
        gremium_id=None,
        delegated_by="deleg",
        granted_by="deleg",
        valid_from=None,
        valid_until=None,
        delegate_voting=True,
        active=True,
    )
    base.update(over)
    return DelegationOut(**base)  # type: ignore[arg-type]


class _FakeService:
    async def list(self, actor):  # noqa: ANN001
        return [_out()]

    async def create(self, payload, actor):  # noqa: ANN001
        return _out(
            principal_id=payload.principal_id,
            role_id=payload.role_id,
            delegate_voting=payload.delegate_voting,
        )

    async def revoke(self, delegation_id, actor):  # noqa: ANN001
        if str(delegation_id).startswith("00000000"):
            raise NotFoundError("nope")
        if str(delegation_id).startswith("11111111"):
            raise ForbiddenError("not yours")
        return None


class _RaisingService(_FakeService):
    async def create(self, payload, actor):  # noqa: ANN001
        raise ValidationProblem(
            "disabled", errors=[{"field": "delegateVoting", "msg": "disabled"}]
        )


def _client(principal: Principal | None, service: object | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_delegation_service] = lambda: service or _FakeService()
    if principal is not None:
        app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app, raise_server_exceptions=False)


_MEMBER = Principal(sub="deleg", roles=["member"], permissions=set())


def test_list_requires_session_401() -> None:
    r = _client(None).get("/api/delegations")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")


def test_list_returns_camelcase() -> None:
    r = _client(_MEMBER).get("/api/delegations")
    assert r.status_code == 200
    item = r.json()[0]
    expected = {"principalId", "roleId", "delegatedBy", "grantedBy", "delegateVoting", "active"}
    assert expected <= item.keys()


def test_create_returns_201_camelcase() -> None:
    pid, rid = str(uuid4()), str(uuid4())
    body = {
        "principalId": pid,
        "roleId": rid,
        "validUntil": "2099-01-01T00:00:00Z",
        "delegateVoting": True,
    }
    r = _client(_MEMBER).post("/api/delegations", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["principalId"] == pid
    assert data["delegateVoting"] is True


def test_create_validation_problem_is_problem_json() -> None:
    body = {
        "principalId": str(uuid4()),
        "roleId": str(uuid4()),
        "validUntil": "2099-01-01T00:00:00Z",
    }
    r = _client(_MEMBER, _RaisingService()).post("/api/delegations", json=body)
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")


def test_create_malformed_body_is_422() -> None:
    r = _client(_MEMBER).post("/api/delegations", json={"roleId": "not-a-uuid"})
    assert r.status_code == 422


def test_revoke_returns_204() -> None:
    r = _client(_MEMBER).delete(f"/api/delegations/{uuid4()}")
    assert r.status_code == 204


def test_revoke_unknown_404_problem_json() -> None:
    r = _client(_MEMBER).delete("/api/delegations/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


def test_revoke_foreign_403_problem_json() -> None:
    r = _client(_MEMBER).delete("/api/delegations/11111111-1111-1111-1111-111111111111")
    assert r.status_code == 403
