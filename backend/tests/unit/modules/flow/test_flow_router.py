"""Tests for the flow router wiring (T-14) — fail-closed auth and problem+json.

`dependency_overrides` replaces the service. The integration suite covers the DB paths.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.applications.access import require_app_applicant
from app.modules.auth.principal import Principal
from app.modules.flow import router as flow_router
from app.modules.flow.dispatch import NullActionDispatcher
from app.modules.flow.router import (
    get_action_dispatcher,
    get_flow_service,
)
from app.modules.flow.schemas import TransitionOut, TransitionResult
from app.modules.flow.service import FlowService
from app.shared.errors import ForbiddenError


class _FakeService:
    def __init__(self) -> None:
        self.fired: dict[str, object] | None = None
        # The `allow_unconfirmed` value of each call. Every route passes False (F15).
        self.allow_unconfirmed: list[bool] = []

    async def available_transitions(  # noqa: ANN201
        self,
        application_id,  # noqa: ANN001
        principal,  # noqa: ANN001
        *,
        allow_unconfirmed=True,  # noqa: ANN001
    ):
        self.allow_unconfirmed.append(allow_unconfirmed)
        return [
            TransitionOut(
                id=uuid4(),
                fromStateId=uuid4(),
                toStateId=uuid4(),
                label={"de": "Einreichen"},
            )
        ]

    async def fire(  # noqa: ANN201
        self,
        application_id,  # noqa: ANN001
        transition_id,  # noqa: ANN001
        principal,  # noqa: ANN001
        *,
        note=None,  # noqa: ANN001
        meeting_id=None,  # noqa: ANN001
        non_public=False,  # noqa: ANN001
        allow_unconfirmed=True,  # noqa: ANN001
        decision=None,  # noqa: ANN001
    ):
        self.allow_unconfirmed.append(allow_unconfirmed)
        self.fired = {
            "application_id": application_id,
            "transition_id": transition_id,
            "principal": principal,
            "note": note,
            "meeting_id": meeting_id,
            "non_public": non_public,
            "decision": decision,
        }
        return TransitionResult(
            newStateId=uuid4(), statusEventId=uuid4(), dispatchedActions=["notify"]
        )

    async def available_applicant_transitions(  # noqa: ANN201
        self,
        application_id,  # noqa: ANN001
        *,
        allow_unconfirmed=True,  # noqa: ANN001
    ):
        self.allow_unconfirmed.append(allow_unconfirmed)
        return [
            TransitionOut(
                id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={"de": "OK"}
            )
        ]

    async def fire_as_applicant(  # noqa: ANN201
        self,
        application_id,  # noqa: ANN001
        transition_id,  # noqa: ANN001
        *,
        note=None,  # noqa: ANN001
        allow_unconfirmed=True,  # noqa: ANN001
    ):
        self.allow_unconfirmed.append(allow_unconfirmed)
        self.fired = {
            "application_id": application_id,
            "transition_id": transition_id,
            "note": note,
        }
        return TransitionResult(
            newStateId=uuid4(), statusEventId=uuid4(), dispatchedActions=[]
        )


    async def list_states(self, application_id, *, allow_unconfirmed=True):  # noqa: ANN001, ANN201
        self.allow_unconfirmed.append(allow_unconfirmed)
        return []

    async def force_status(  # noqa: ANN201
        self,
        application_id,  # noqa: ANN001
        target_state_id,  # noqa: ANN001
        principal,  # noqa: ANN001
        *,
        note,  # noqa: ANN001
        allow_unconfirmed=True,  # noqa: ANN001
    ):
        self.allow_unconfirmed.append(allow_unconfirmed)
        return TransitionResult(
            newStateId=target_state_id, statusEventId=uuid4(), dispatchedActions=[]
        )


@pytest.fixture
def fake_service() -> _FakeService:
    return _FakeService()


class _ReadGate:
    """Stand-in for `resolve_app_read` in the flow router.

    It records each checked application and raises 403 when `deny` is set.
    """

    def __init__(self) -> None:
        self.checked: list[object] = []
        self.deny = False

    async def __call__(self, _db, application_id, principal, applicant):  # noqa: ANN001, ANN204
        assert principal is not None
        assert applicant is None
        self.checked.append(application_id)
        if self.deny:
            raise ForbiddenError("no read access")


@pytest.fixture
def read_gate(monkeypatch: pytest.MonkeyPatch) -> _ReadGate:
    gate = _ReadGate()
    monkeypatch.setattr(flow_router, "resolve_app_read", gate)
    return gate


@pytest.fixture
def app(fake_service: _FakeService, read_gate: _ReadGate) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_flow_service] = lambda: fake_service
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as_principal(app: FastAPI, *perms: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="mgr", permissions=set(perms)
    )
    app.dependency_overrides[get_current_applicant] = lambda: None


def test_list_transitions_requires_auth_401(client: TestClient) -> None:
    assert client.get(f"/api/applications/{uuid4()}/transitions").status_code == 401


def test_list_transitions_missing_perm_403(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "application.read")  # not .manage
    r = client.get(f"/api/applications/{uuid4()}/transitions")
    assert r.status_code == 403
    assert r.headers["content-type"] == "application/problem+json"


def test_list_transitions_ok(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "application.transition")
    r = client.get(f"/api/applications/{uuid4()}/transitions")
    assert r.status_code == 200
    assert len(r.json()) == 1
    # F15: the route hides an unconfirmed guest application.
    assert fake_service.allow_unconfirmed == [False]


def test_fire_requires_auth_401(client: TestClient) -> None:
    r = client.post(
        f"/api/applications/{uuid4()}/transition", json={"transitionId": str(uuid4())}
    )
    assert r.status_code == 401


def test_fire_ok_passes_note(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "application.transition")
    app_id, transition_id = uuid4(), uuid4()
    r = client.post(
        f"/api/applications/{app_id}/transition",
        json={"transitionId": str(transition_id), "note": "freigegeben"},
    )
    assert r.status_code == 200
    assert r.json()["dispatchedActions"] == ["notify"]
    assert fake_service.fired is not None
    assert fake_service.fired["application_id"] == app_id
    assert fake_service.fired["transition_id"] == transition_id
    assert fake_service.fired["note"] == "freigegeben"
    assert fake_service.allow_unconfirmed == [False]


def test_fire_passes_meeting_and_visibility(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "application.transition")
    meeting_id = uuid4()
    r = client.post(
        f"/api/applications/{uuid4()}/transition",
        json={
            "transitionId": str(uuid4()),
            "meetingId": str(meeting_id),
            "nonPublic": True,
        },
    )
    assert r.status_code == 200
    assert fake_service.fired is not None
    assert fake_service.fired["meeting_id"] == meeting_id
    assert fake_service.fired["non_public"] is True


def test_fire_without_meeting_defaults(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "application.transition")
    r = client.post(
        f"/api/applications/{uuid4()}/transition",
        json={"transitionId": str(uuid4())},
    )
    assert r.status_code == 200
    assert fake_service.fired is not None
    assert fake_service.fired["meeting_id"] is None
    assert fake_service.fired["non_public"] is False


def test_fire_passes_the_decision(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """F1: the route hands the decision of the body to the engine."""
    _as_principal(app, "application.transition")
    r = client.post(
        f"/api/applications/{uuid4()}/transition",
        json={
            "transitionId": str(uuid4()),
            "decision": {"approvedAmount": "900.00", "conditions": ["  Belege  "]},
        },
    )
    assert r.status_code == 200
    assert fake_service.fired is not None
    decision = fake_service.fired["decision"]
    assert str(decision.approved_amount) == "900.00"  # type: ignore[attr-defined]
    assert decision.conditions == ["Belege"]  # type: ignore[attr-defined]


def test_fire_refuses_a_bad_decision_422(app: FastAPI, client: TestClient) -> None:
    """F1: an empty condition or an unknown key is a 422 before the engine runs."""
    _as_principal(app, "application.transition")
    for decision in ({"conditions": ["  "]}, {"approvedAmount": "1", "extra": 1}):
        r = client.post(
            f"/api/applications/{uuid4()}/transition",
            json={"transitionId": str(uuid4()), "decision": decision},
        )
        assert r.status_code == 422


def test_fire_rejects_bad_body_422(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "application.transition")
    r = client.post(
        f"/api/applications/{uuid4()}/transition", json={"transitionId": "not-a-uuid"}
    )
    assert r.status_code == 422


# Applicant transitions: access through a magic link.
def test_list_applicant_transitions_ok(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    app_id = uuid4()
    app.dependency_overrides[require_app_applicant] = lambda: SimpleNamespace(
        application_id=app_id
    )
    r = client.get(f"/api/applications/{app_id}/applicant-transitions")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert fake_service.allow_unconfirmed == [False]


def test_fire_applicant_transition_ok(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    app_id, transition_id = uuid4(), uuid4()
    app.dependency_overrides[require_app_applicant] = lambda: SimpleNamespace(
        application_id=app_id
    )
    r = client.post(
        f"/api/applications/{app_id}/applicant-transition",
        json={"transitionId": str(transition_id), "note": "los"},
    )
    assert r.status_code == 200
    assert fake_service.fired is not None
    assert fake_service.fired["application_id"] == app_id
    assert fake_service.fired["note"] == "los"
    assert fake_service.allow_unconfirmed == [False]


def test_fire_applicant_transition_refuses_a_decision(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """F1: the applicant never sets a decision (422 `decision_not_allowed`)."""
    app_id = uuid4()
    app.dependency_overrides[require_app_applicant] = lambda: SimpleNamespace(
        application_id=app_id
    )
    r = client.post(
        f"/api/applications/{app_id}/applicant-transition",
        json={"transitionId": str(uuid4()), "decision": {"conditions": ["x"]}},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "decision_not_allowed"
    assert fake_service.fired is None


def test_force_routes_hide_unconfirmed(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """F15: the force-status picker and the force call pass `allow_unconfirmed=False`."""
    _as_principal(app, "application.force_status")
    app_id = uuid4()
    assert client.get(f"/api/applications/{app_id}/flow-states").status_code == 200
    r = client.post(
        f"/api/applications/{app_id}/force-status",
        json={"stateId": str(uuid4()), "note": "Korrektur"},
    )
    assert r.status_code == 200
    assert fake_service.allow_unconfirmed == [False, False]


def test_di_factories_build_real_objects() -> None:
    assert isinstance(get_action_dispatcher(), NullActionDispatcher)
    dispatcher = NullActionDispatcher()
    publisher = object()
    service = get_flow_service(
        session=object(),  # type: ignore[arg-type]
        dispatcher=dispatcher,
        publisher=publisher,  # type: ignore[arg-type]
    )
    assert isinstance(service, FlowService)
    assert service.dispatcher is dispatcher
    assert service.publisher is publisher


def test_openapi_declares_flow_error_responses(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    get = spec["paths"]["/api/applications/{application_id}/transitions"]["get"]
    assert {"401", "403", "404"} <= set(get["responses"])
    post = spec["paths"]["/api/applications/{application_id}/transition"]["post"]
    assert {"400", "401", "403", "404", "409", "422"} <= set(post["responses"])
    assert "application/problem+json" in post["responses"]["409"]["content"]


def test_transition_routes_check_read_access(
    app: FastAPI, client: TestClient, fake_service: _FakeService, read_gate: _ReadGate
) -> None:
    """A holder of `application.transition` lists and fires only on a readable application."""
    _as_principal(app, "application.transition")
    app_id = uuid4()
    assert client.get(f"/api/applications/{app_id}/transitions").status_code == 200
    assert read_gate.checked == [app_id]

    read_gate.deny = True
    r = client.get(f"/api/applications/{app_id}/transitions")
    assert r.status_code == 403
    assert r.headers["content-type"] == "application/problem+json"
    r = client.post(
        f"/api/applications/{app_id}/transition", json={"transitionId": str(uuid4())}
    )
    assert r.status_code == 403
    assert fake_service.fired is None


def test_force_routes_check_read_access(
    app: FastAPI, client: TestClient, fake_service: _FakeService, read_gate: _ReadGate
) -> None:
    _as_principal(app, "application.force_status")
    read_gate.deny = True
    app_id = uuid4()
    assert client.get(f"/api/applications/{app_id}/flow-states").status_code == 403
    r = client.post(
        f"/api/applications/{app_id}/force-status",
        json={"stateId": str(uuid4()), "note": "Korrektur"},
    )
    assert r.status_code == 403
    assert fake_service.allow_unconfirmed == []
