"""Router tests for the protocol endpoints (T-22).

The tests cover the endpoint wiring and the RBAC gate (protocol.write). The service is
a fake.
"""

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

    async def rollback(self) -> None: ...


class _FakePool:
    """arq pool fake that records the enqueue_job calls."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, str]] = []

    async def enqueue_job(self, name: str, *args: str, **_kw: object) -> object:
        self.jobs.append((name, args[0]))
        return object()


class _FakeService:
    def __init__(self, *, status: str = "draft") -> None:
        self.calls: list[str] = []
        self.status = status
        self.session = _FakeSession()
        # The router delegates the per-Gremium authorization to MeetingService, so this
        # fake is a no-op. test_protocol_service covers the real authz paths.
        self.authz: list[str] = []

    async def authorize_write_meeting(self, meeting_id: UUID, principal: object) -> None:
        self.authz.append(f"write_meeting:{meeting_id}")

    async def authorize_write(self, protocol_id: UUID, principal: object) -> None:
        self.authz.append(f"write:{protocol_id}")

    async def authorize_finalize(self, protocol_id: UUID, principal: object) -> None:
        self.authz.append(f"finalize:{protocol_id}")

    async def authorize_read(self, protocol_id: UUID, principal: object) -> None:
        self.authz.append(f"read:{protocol_id}")

    async def authorize_read_meeting(self, meeting_id: UUID, principal: object) -> None:
        self.authz.append(f"read_meeting:{meeting_id}")

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

    async def get_by_meeting(self, meeting_id: UUID) -> ProtocolOut:
        self.calls.append(f"get_by_meeting:{meeting_id}")
        return self._out(status=self.status)

    async def update_markdown(self, protocol_id: UUID, markdown: str) -> ProtocolOut:
        self.calls.append(f"update:{protocol_id}")
        return self._out(markdown=markdown)

    async def embed_votes(self, protocol_id: UUID, vote_ids: list[UUID]) -> ProtocolOut:
        self.calls.append(f"embed:{protocol_id}:{len(vote_ids)}")
        return self._out()

    async def start_finalize(self, protocol_id: UUID) -> tuple[ProtocolOut, bool]:
        self.calls.append(f"start_finalize:{protocol_id}")
        if self.status in ("rendering", "final"):
            return self._out(status=self.status), False
        self.status = "rendering"
        return self._out(status="rendering"), True

    async def finalize(self, protocol_id: UUID, *, now: datetime) -> ProtocolOut:
        self.calls.append(f"finalize:{protocol_id}")
        self.status = "final"
        return self._out(status="final")

    async def revert_to_draft(self, protocol_id: UUID) -> None:
        self.calls.append(f"revert:{protocol_id}")
        self.status = "draft"

    async def delete_protocol(self, protocol_id: UUID, *, actor: str) -> None:
        from app.shared.errors import ConflictError

        self.calls.append(f"delete:{protocol_id}:{actor}")
        if self.status != "draft":
            raise ConflictError("Protocol is finalized and read-only.")


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


# RBAC fail-closed.
def test_create_protocol_requires_auth_401(client: TestClient) -> None:
    assert client.post(f"/api/meetings/{MEETING_ID}/protocol").status_code == 401


def test_create_protocol_authz_delegated_to_service(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """The router gates authentication only.

    It delegates the per-Gremium permission to the service (AUD-016). The call of the
    authz hook proves the delegation.
    """
    _writer(app)  # logged in only, no global permission
    r = client.post(f"/api/meetings/{MEETING_ID}/protocol")
    assert r.status_code == 200
    assert fake_service.authz == [f"write_meeting:{MEETING_ID}"]


def test_patch_protocol_requires_auth_401(client: TestClient) -> None:
    assert client.patch(f"/api/protocols/{PROTOCOL_ID}", json={"markdown": "x"}).status_code == 401


def test_votes_requires_auth_401(client: TestClient) -> None:
    body = {"voteIds": [str(VOTE_ID)]}
    assert client.post(f"/api/protocols/{PROTOCOL_ID}/votes", json=body).status_code == 401


def test_finalize_requires_auth_401(client: TestClient) -> None:
    assert client.post(f"/api/protocols/{PROTOCOL_ID}/finalize").status_code == 401


# Happy paths.
def test_create_or_load_protocol(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _writer(app, "meeting.manage")
    r = client.post(f"/api/meetings/{MEETING_ID}/protocol")
    assert r.status_code == 200
    assert r.json()["meetingId"] == str(MEETING_ID)
    assert fake_service.calls == [f"get_or_create:{MEETING_ID}:p"]


def test_get_protocol_read_only(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """Reload and poll path (#429): GET reads and creates no protocol."""
    _writer(app, "meeting.manage")
    fake_service.status = "rendering"
    r = client.get(f"/api/meetings/{MEETING_ID}/protocol")
    assert r.status_code == 200
    assert r.json()["status"] == "rendering"
    assert fake_service.calls == [f"get_by_meeting:{MEETING_ID}"]


def test_get_protocol_requires_auth_401(client: TestClient) -> None:
    assert client.get(f"/api/meetings/{MEETING_ID}/protocol").status_code == 401


def test_update_protocol(app: FastAPI, client: TestClient, fake_service: _FakeService) -> None:
    _writer(app, "meeting.manage")
    r = client.patch(f"/api/protocols/{PROTOCOL_ID}", json={"markdown": "# Neu"})
    assert r.status_code == 200
    assert r.json()["markdown"] == "# Neu"
    assert fake_service.calls == [f"update:{PROTOCOL_ID}"]


def test_update_protocol_rejects_empty_body_422(app: FastAPI, client: TestClient) -> None:
    _writer(app, "meeting.manage")
    assert client.patch(f"/api/protocols/{PROTOCOL_ID}", json={}).status_code == 422


def test_update_protocol_rejects_oversized_markdown_422(
    app: FastAPI, client: TestClient
) -> None:
    """AUD-060: the API caps the Markdown at 512 kB and answers 422 in any deployment."""
    _writer(app, "meeting.manage")
    oversized = "x" * (512_000 + 1)
    r = client.patch(f"/api/protocols/{PROTOCOL_ID}", json={"markdown": oversized})
    assert r.status_code == 422
    # Just under the limit stays valid, and the service answers 200.
    ok = client.patch(f"/api/protocols/{PROTOCOL_ID}", json={"markdown": "x" * 512_000})
    assert ok.status_code == 200


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


def test_finalize_protocol_sync_fallback_without_pool(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """Without Redis (no `arq_pool`) finalize renders synchronously, as it did before."""
    _writer(app, "protocol.finalize")
    r = client.post(f"/api/protocols/{PROTOCOL_ID}/finalize")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "final"
    assert body["pdfUrl"] == "https://minio.local/p"
    assert body["sentAt"] is not None
    assert fake_service.calls == [
        f"start_finalize:{PROTOCOL_ID}",
        f"finalize:{PROTOCOL_ID}",
    ]


def test_finalize_protocol_enqueues_with_pool(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """With Redis: return `rendering` and enqueue the `render_protocol` job."""
    _writer(app, "protocol.finalize")
    pool = _FakePool()
    app.state.arq_pool = pool
    r = client.post(f"/api/protocols/{PROTOCOL_ID}/finalize")
    assert r.status_code == 200
    assert r.json()["status"] == "rendering"
    assert pool.jobs == [("render_protocol", str(PROTOCOL_ID))]
    assert fake_service.calls == [f"start_finalize:{PROTOCOL_ID}"]  # no sync render


def test_finalize_protocol_idempotent_while_rendering(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """A second finalize during the render does not enqueue again."""
    _writer(app, "protocol.finalize")
    fake_service.status = "rendering"
    pool = _FakePool()
    app.state.arq_pool = pool
    r = client.post(f"/api/protocols/{PROTOCOL_ID}/finalize")
    assert r.status_code == 200
    assert r.json()["status"] == "rendering"
    assert pool.jobs == []
    assert fake_service.calls == [f"start_finalize:{PROTOCOL_ID}"]


# Service wiring.
def test_get_protocol_service_wires_state_infra() -> None:
    """The storage and the mail queue come from the app state (T-20 infra), not a copy."""
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


# DELETE /protocols/{id}: draft only, gated by the write scope (not protocol.finalize).


def test_delete_protocol_requires_auth_401(client: TestClient) -> None:
    assert client.delete(f"/api/protocols/{PROTOCOL_ID}").status_code == 401


def test_delete_draft_protocol_204(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _writer(app, "meeting.manage")
    r = client.delete(f"/api/protocols/{PROTOCOL_ID}")
    assert r.status_code == 204
    # The gate is the write scope of the PATCH, not the finalize scope.
    assert fake_service.authz == [f"write:{PROTOCOL_ID}"]
    assert fake_service.calls == [f"delete:{PROTOCOL_ID}:p"]


def test_delete_protocol_without_finalize_permission_still_works(
    app: FastAPI, client: TestClient
) -> None:
    """Discarding a draft needs no `protocol.finalize`.

    That permission gates publishing. The same caller can already empty the body
    through the PATCH, so a stricter gate here would protect nothing.
    """
    _writer(app)  # authenticated only; the service holds the per-Gremium check
    assert client.delete(f"/api/protocols/{PROTOCOL_ID}").status_code == 204


def test_delete_final_protocol_409(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_protocol_service] = lambda: _FakeService(status="final")
    _writer(app, "meeting.manage")
    r = client.delete(f"/api/protocols/{PROTOCOL_ID}")
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")
