"""Router tests for the draft uploads of the wizard (Z4) with faked draft operations.

They cover the ALTCHA gate of the first anonymous upload, the token header, the actor
and the body cap. `test_files_drafts` covers the service, the integration test
`test_draft_upload` the whole path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.files.router import get_draft_attachments
from app.modules.files.schemas import DraftAttachmentOut
from app.settings import get_settings, load_settings
from app.shared.altcha import AltchaError
from app.shared.antiabuse import get_altcha_verifier

ATT_ID = uuid4()


class _Files:
    max_bytes = 10 * 1024 * 1024


class _FakeDrafts:
    def __init__(self) -> None:
        self.files = _Files()
        self.uploads: list[dict[str, object]] = []
        self.deletes: list[tuple[UUID, str, str]] = []
        self.valid_tokens = {"tok"}
        self.checked: list[str] = []

    async def token_is_valid(self, token: str) -> bool:
        self.checked.append(token)
        return token in self.valid_tokens

    async def upload(self, **kw: object) -> DraftAttachmentOut:
        self.uploads.append(kw)
        return DraftAttachmentOut(
            id=ATT_ID,
            filename="a.pdf",
            mime="application/pdf",
            size=4,
            scanned=False,
            is_comparison_offer=bool(kw["is_comparison_offer"]),
            draftToken=str(kw["token"] or "new-token"),
            draftExpiresAt=datetime(2026, 10, 8, tzinfo=UTC),
        )

    async def delete(self, attachment_id: UUID, *, token: str, actor: str) -> None:
        self.deletes.append((attachment_id, token, actor))


class _Verifier:
    def __init__(self) -> None:
        self.seen: list[str | None] = []

    async def verify(self, payload_b64: str | None) -> None:
        self.seen.append(payload_b64)
        if payload_b64 != "solved":
            raise AltchaError("bad")


@pytest.fixture
def drafts() -> _FakeDrafts:
    return _FakeDrafts()


@pytest.fixture
def verifier() -> _Verifier:
    return _Verifier()


@pytest.fixture
def app(drafts: _FakeDrafts, verifier: _Verifier) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_draft_attachments] = lambda: drafts
    application.dependency_overrides[get_altcha_verifier] = lambda: verifier
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_anonymous_first_upload_needs_altcha(
    client: TestClient, drafts: _FakeDrafts, verifier: _Verifier
) -> None:
    r = client.post(
        "/api/apply/attachments", files={"file": ("a.pdf", b"%PDF", "application/pdf")}
    )
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "altcha_failed"
    assert drafts.uploads == []
    assert verifier.seen == [None]


def test_anonymous_first_upload_with_altcha(
    client: TestClient, drafts: _FakeDrafts
) -> None:
    r = client.post(
        "/api/apply/attachments",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
        data={"altcha": "solved", "field_key": "f", "is_comparison_offer": "true"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["draftToken"] == "new-token"
    assert body["is_comparison_offer"] is True
    assert "draftExpiresAt" in body
    assert drafts.uploads[0]["token"] is None
    assert drafts.uploads[0]["by"] == "applicant"
    assert drafts.uploads[0]["field_key"] == "f"


def test_later_upload_with_token_needs_no_altcha(
    client: TestClient, drafts: _FakeDrafts, verifier: _Verifier
) -> None:
    r = client.post(
        "/api/apply/attachments",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
        headers={"X-Draft-Token": "tok"},
    )
    assert r.status_code == 201, r.text
    assert drafts.uploads[0]["token"] == "tok"
    assert drafts.checked == ["tok"]
    assert verifier.seen == []


class _NoRead:
    """Fail the test when the route reads the file."""

    @property
    def max_bytes(self) -> int:
        raise AssertionError("the route read the file before the token check")


@pytest.mark.parametrize("logged_in", [False, True])
def test_unknown_token_gives_422_before_the_file_read(
    app: FastAPI,
    client: TestClient,
    drafts: _FakeDrafts,
    verifier: _Verifier,
    logged_in: bool,
) -> None:
    if logged_in:
        app.dependency_overrides[get_current_principal] = lambda: Principal(sub="p-1")
    drafts.files = _NoRead()  # type: ignore[assignment]
    r = client.post(
        "/api/apply/attachments",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
        data={"altcha": "solved"},
        headers={"X-Draft-Token": "random"},
    )
    assert r.status_code == 422, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "draft_token_invalid"
    assert drafts.checked == ["random"]
    assert drafts.uploads == []
    assert verifier.seen == []


def test_logged_in_first_upload_needs_no_altcha(
    app: FastAPI, client: TestClient, drafts: _FakeDrafts, verifier: _Verifier
) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="p-1")
    r = client.post(
        "/api/apply/attachments", files={"file": ("a.pdf", b"%PDF", "application/pdf")}
    )
    assert r.status_code == 201, r.text
    assert drafts.uploads[0]["by"] == "p-1"
    assert verifier.seen == []


def test_body_cap_rejects_a_large_content_length(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: load_settings(attachment_max_bytes=1)
    r = client.post(
        "/api/apply/attachments",
        files={"file": ("a.pdf", b"x" * (70 * 1024), "application/pdf")},
        headers={"X-Draft-Token": "tok"},
    )
    assert r.status_code == 413


def test_upload_reads_under_the_cap(client: TestClient, drafts: _FakeDrafts) -> None:
    drafts.files.max_bytes = 2
    r = client.post(
        "/api/apply/attachments",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
        headers={"X-Draft-Token": "tok"},
    )
    assert r.status_code == 413
    assert drafts.uploads == []


def test_delete_passes_token_and_actor(
    app: FastAPI, client: TestClient, drafts: _FakeDrafts
) -> None:
    r = client.delete(f"/api/apply/attachments/{ATT_ID}", headers={"X-Draft-Token": "tok"})
    assert r.status_code == 204
    assert drafts.deletes == [(ATT_ID, "tok", "applicant")]
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="p-2")
    client.delete(f"/api/apply/attachments/{ATT_ID}", headers={"X-Draft-Token": "tok"})
    assert drafts.deletes[-1] == (ATT_ID, "tok", "p-2")


def test_delete_without_token_gives_422(client: TestClient, drafts: _FakeDrafts) -> None:
    r = client.delete(f"/api/apply/attachments/{ATT_ID}")
    assert r.status_code == 422
    assert drafts.deletes == []
