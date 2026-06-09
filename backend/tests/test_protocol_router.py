"""Router-Tests protocol (T-22): Endpunkt-Verdrahtung + RBAC (protocol.write), Service gefaked."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.notifications.queue import ArqMailQueue
from app.modules.protocol.router import _mail_queue, get_protocol_service
from app.modules.protocol.schemas import ProtocolOut
from app.settings import get_settings

MEETING_ID = uuid4()
PROTOCOL_ID = uuid4()
VOTE_ID = uuid4()


class _FakeSession:
    async def commit(self) -> None: ...


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _out(self, *, status: str = "draft", markdown: str = "# md") -> ProtocolOut:
        return ProtocolOut(
            id=PROTOCOL_ID,
            meetingId=MEETING_ID,
            markdown=markdown,
            status=status,  # type: ignore[arg-type]
            pdfUrl="https://minio.local/p" if status == "final" else None,
            sentAt=datetime(2026, 6, 12, tzinfo=UTC) if status == "final" else None,
        )

    async def get_or_create(self, meeting_id: UUID, *, author: str | None = None) -> ProtocolOut:
        self.calls.append(f"get_or_create:{meeting_id}:{author}")
        return self._out()

    async def update_markdown(self, protocol_id: UUID, markdown: str) -> ProtocolOut:
        self.calls.append(f"update:{protocol_id}")
        return self._out(markdown=markdown)

    async def embed_votes(self, protocol_id: UUID, vote_ids: list[UUID]) -> ProtocolOut:
        self.calls.append(f"embed:{protocol_id}:{len(vote_ids)}")
        return self._out()

    async def finalize(self, protocol_id: UUID, *, now: datetime) -> ProtocolOut:
        self.calls.append(f"finalize:{protocol_id}")
        return self._out(status="final")


@pytest.fixture
def fake_service() -> _FakeService:
    return _FakeService()


@pytest.fixture
def app(fake_service: _FakeService) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_protocol_service] = lambda: fake_service

    def _session() -> Iterator[_FakeSession]:
        yield _FakeSession()

    application.dependency_overrides[get_session] = _session
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _writer(app: FastAPI, *perms: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="p", permissions=set(perms)
    )


# ----------------------------------------------------------------- RBAC fail-closed
def test_create_protocol_requires_auth_401(client: TestClient) -> None:
    assert client.post(f"/api/meetings/{MEETING_ID}/protocol").status_code == 401


def test_create_protocol_forbidden_without_perm(app: FastAPI, client: TestClient) -> None:
    _writer(app, "vote.cast")  # falsche Permission
    assert client.post(f"/api/meetings/{MEETING_ID}/protocol").status_code == 403


def test_patch_protocol_requires_auth_401(client: TestClient) -> None:
    assert client.patch(f"/api/protocols/{PROTOCOL_ID}", json={"markdown": "x"}).status_code == 401


def test_votes_requires_auth_401(client: TestClient) -> None:
    body = {"voteIds": [str(VOTE_ID)]}
    assert client.post(f"/api/protocols/{PROTOCOL_ID}/votes", json=body).status_code == 401


def test_finalize_requires_auth_401(client: TestClient) -> None:
    assert client.post(f"/api/protocols/{PROTOCOL_ID}/finalize").status_code == 401


# ------------------------------------------------------------------- happy paths
def test_create_or_load_protocol(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _writer(app, "meeting.manage")
    r = client.post(f"/api/meetings/{MEETING_ID}/protocol")
    assert r.status_code == 200
    assert r.json()["meetingId"] == str(MEETING_ID)
    assert fake_service.calls == [f"get_or_create:{MEETING_ID}:p"]


def test_update_protocol(app: FastAPI, client: TestClient, fake_service: _FakeService) -> None:
    _writer(app, "meeting.manage")
    r = client.patch(f"/api/protocols/{PROTOCOL_ID}", json={"markdown": "# Neu"})
    assert r.status_code == 200
    assert r.json()["markdown"] == "# Neu"
    assert fake_service.calls == [f"update:{PROTOCOL_ID}"]


def test_update_protocol_rejects_empty_body_422(app: FastAPI, client: TestClient) -> None:
    _writer(app, "meeting.manage")
    assert client.patch(f"/api/protocols/{PROTOCOL_ID}", json={}).status_code == 422


def test_embed_votes(app: FastAPI, client: TestClient, fake_service: _FakeService) -> None:
    _writer(app, "meeting.manage")
    body = {"voteIds": [str(VOTE_ID), str(uuid4())]}
    r = client.post(f"/api/protocols/{PROTOCOL_ID}/votes", json=body)
    assert r.status_code == 200
    assert fake_service.calls == [f"embed:{PROTOCOL_ID}:2"]


def test_embed_votes_rejects_empty_list_422(app: FastAPI, client: TestClient) -> None:
    _writer(app, "meeting.manage")
    r = client.post(f"/api/protocols/{PROTOCOL_ID}/votes", json={"voteIds": []})
    assert r.status_code == 422


def test_finalize_protocol(app: FastAPI, client: TestClient, fake_service: _FakeService) -> None:
    _writer(app, "meeting.manage")
    r = client.post(f"/api/protocols/{PROTOCOL_ID}/finalize")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "final"
    assert body["pdfUrl"] == "https://minio.local/p"
    assert body["sentAt"] is not None
    assert fake_service.calls == [f"finalize:{PROTOCOL_ID}"]


# ------------------------------------------------------------- service wiring
def test_get_protocol_service_wires_state_infra() -> None:
    """Storage + Mail-Queue stammen aus dem App-State (T-20-Infra), nicht dupliziert."""
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        object_storage="STORE", arq_pool=object()
    )))
    service = get_protocol_service(_FakeSession(), request, get_settings())  # type: ignore[arg-type]
    assert service.storage == "STORE"
    assert isinstance(service.mail_queue, ArqMailQueue)
    assert service.pytex is not None


def test_mail_queue_none_without_pool() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq_pool=None)))
    assert _mail_queue(request) is None  # type: ignore[arg-type]
