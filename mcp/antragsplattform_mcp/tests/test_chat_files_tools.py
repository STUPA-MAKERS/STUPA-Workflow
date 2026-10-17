"""Tests for the chat-file helper and the sender-block tools.

A fake API records every request. The helper must check all files before the first
upload, send the draft token of the first upload as `X-Draft-Token` on every later one,
post the message with `attachmentIds` and `draftToken`, and delete the uploaded drafts
when an upload or the post fails. `test_chat_files_contract.py` runs the same tools
against the real routers.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from antragsplattform_mcp.client import ApiError
from antragsplattform_mcp.tools import (
    _chat_files,
    _common,
    applications,
    tickets,
    todos,
)

PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class _FakeApi:
    """Answer the draft upload with a new id and one token; record everything."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.fail_post: str | None = None
        self.fail_upload_at: int | None = None
        self.fail_delete = False
        self._uploads = 0

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(("POST", path, kw))
        if path == "/apply/attachments":
            self._uploads += 1
            if self._uploads == self.fail_upload_at:
                raise ApiError(415, "File type not allowed")
            return {"id": f"a{self._uploads}", "draftToken": "tok", "scanned": False}
        if path == self.fail_post:
            raise ApiError(422, "draft_attachments_missing")
        return {"id": "m1", "attachments": []}

    async def get(self, path: str, **kw: Any) -> list[Any]:
        self.calls.append(("GET", path, kw))
        return []

    async def delete(self, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(("DELETE", path, kw))
        if self.fail_delete:
            raise ApiError(404, "gone")
        return {"status": "ok"}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


@pytest.fixture
def pdfs(tmp_path: Path) -> list[str]:
    out = []
    for i in range(6):
        p = tmp_path / f"f{i}.pdf"
        p.write_bytes(PDF)
        out.append(str(p))
    return out


def _uploads(fake: _FakeApi) -> list[dict[str, Any]]:
    return [
        kw for m, path, kw in fake.calls if (m, path) == ("POST", "/apply/attachments")
    ]


def test_note_with_files_uploads_then_binds(
    fake_api: _FakeApi, pdfs: list[str]
) -> None:
    asyncio.run(tickets.tickets_note("t1", "", pdfs[:2]))
    ups = _uploads(fake_api)
    assert [u["files"]["file"] for u in ups] == [
        ("f0.pdf", PDF, "application/pdf"),
        ("f1.pdf", PDF, "application/pdf"),
    ]
    assert [u["headers"] for u in ups] == [{}, {"X-Draft-Token": "tok"}]
    assert fake_api.calls[-1] == (
        "POST",
        "/tickets/t1/notes",
        {"json": {"body": "", "attachmentIds": ["a1", "a2"], "draftToken": "tok"}},
    )


def test_note_without_files_is_one_plain_post(fake_api: _FakeApi) -> None:
    asyncio.run(tickets.tickets_note("t1", "Text"))
    asyncio.run(tickets.tickets_note("t1", "Text", []))
    assert fake_api.calls == [
        ("POST", "/tickets/t1/notes", {"json": {"body": "Text"}}),
        ("POST", "/tickets/t1/notes", {"json": {"body": "Text"}}),
    ]


def test_todo_comment_keeps_mentions(fake_api: _FakeApi, pdfs: list[str]) -> None:
    asyncio.run(todos.todo_comment("c1", "hi", ["p1"], pdfs[:1]))
    assert fake_api.calls[-1] == (
        "POST",
        "/todos/cards/c1/comments",
        {
            "json": {
                "body": "hi",
                "mentions": ["p1"],
                "attachmentIds": ["a1"],
                "draftToken": "tok",
            }
        },
    )


def test_application_comment_keeps_visibility(
    fake_api: _FakeApi, pdfs: list[str]
) -> None:
    asyncio.run(applications.comment_application("app1", "x", "internal", pdfs[:1]))
    assert fake_api.calls[-1][2]["json"] == {
        "body": "x",
        "visibility": "internal",
        "attachmentIds": ["a1"],
        "draftToken": "tok",
    }


def test_application_comment_without_files(fake_api: _FakeApi) -> None:
    asyncio.run(applications.comment_application("app1", "x"))
    assert fake_api.calls == [
        (
            "POST",
            "/applications/app1/comments",
            {"json": {"body": "x", "visibility": "public"}},
        )
    ]


def test_application_comment_passes_the_mentions(fake_api: _FakeApi) -> None:
    asyncio.run(applications.comment_application("app1", "@Anna", "internal", mentions=["p1"]))
    assert fake_api.calls == [
        (
            "POST",
            "/applications/app1/comments",
            {"json": {"body": "@Anna", "visibility": "internal", "mentions": ["p1"]}},
        )
    ]


def test_application_comment_with_mentions_is_internal_by_default(fake_api: _FakeApi) -> None:
    asyncio.run(applications.comment_application("app1", "@Anna", mentions=["p1"]))
    asyncio.run(applications.comment_application("app1", "Hallo"))
    assert [c[2]["json"]["visibility"] for c in fake_api.calls] == ["internal", "public"]


def test_more_than_five_files_sends_nothing(
    fake_api: _FakeApi, pdfs: list[str]
) -> None:
    with pytest.raises(ApiError) as err:
        asyncio.run(tickets.tickets_note("t1", "", pdfs))
    assert err.value.status == 400
    assert "at most 5" in err.value.message
    assert fake_api.calls == []


def test_a_bad_file_sends_nothing(
    fake_api: _FakeApi, pdfs: list[str], tmp_path: Path
) -> None:
    bad = tmp_path / "x.exe"
    bad.write_bytes(b"MZ")
    with pytest.raises(ApiError, match="is not allowed"):
        asyncio.run(todos.todo_comment("c1", "", None, [pdfs[0], str(bad)]))
    with pytest.raises(ApiError, match="file not found"):
        asyncio.run(todos.todo_comment("c1", "", None, [str(tmp_path / "nope.pdf")]))
    assert fake_api.calls == []


def test_failed_post_deletes_the_drafts(fake_api: _FakeApi, pdfs: list[str]) -> None:
    fake_api.fail_post = "/tickets/t1/notes"
    with pytest.raises(ApiError) as err:
        asyncio.run(tickets.tickets_note("t1", "", pdfs[:2]))
    assert err.value.status == 422
    deletes = [(path, kw) for m, path, kw in fake_api.calls if m == "DELETE"]
    assert deletes == [
        ("/apply/attachments/a1", {"headers": {"X-Draft-Token": "tok"}}),
        ("/apply/attachments/a2", {"headers": {"X-Draft-Token": "tok"}}),
    ]


def test_failed_upload_deletes_the_earlier_drafts(
    fake_api: _FakeApi, pdfs: list[str]
) -> None:
    fake_api.fail_upload_at = 2
    with pytest.raises(ApiError) as err:
        asyncio.run(tickets.tickets_note("t1", "", pdfs[:3]))
    assert err.value.status == 415
    assert len(_uploads(fake_api)) == 2
    assert [path for m, path, _ in fake_api.calls if m == "DELETE"] == [
        "/apply/attachments/a1"
    ]
    assert not any(path == "/tickets/t1/notes" for _, path, _ in fake_api.calls)


def test_failed_first_upload_has_no_token_to_clean(
    fake_api: _FakeApi, pdfs: list[str]
) -> None:
    fake_api.fail_upload_at = 1
    with pytest.raises(ApiError):
        asyncio.run(tickets.tickets_note("t1", "", pdfs[:2]))
    assert [m for m, _, _ in fake_api.calls] == ["POST"]


def test_a_failed_cleanup_keeps_the_original_error(
    fake_api: _FakeApi, pdfs: list[str]
) -> None:
    fake_api.fail_post = "/tickets/t1/notes"
    fake_api.fail_delete = True
    with pytest.raises(ApiError) as err:
        asyncio.run(tickets.tickets_note("t1", "", pdfs[:2]))
    assert err.value.status == 422
    assert len([m for m, _, _ in fake_api.calls if m == "DELETE"]) == 2


def test_sender_block_tools(fake_api: _FakeApi) -> None:
    asyncio.run(tickets.tickets_block_sender("t1"))
    asyncio.run(tickets.tickets_unblock_sender("t1"))
    asyncio.run(tickets.tickets_blocked_senders())
    asyncio.run(tickets.tickets_delete_blocked_sender("b1"))
    assert [(m, p) for m, p, _ in fake_api.calls] == [
        ("POST", "/tickets/t1/block-sender"),
        ("DELETE", "/tickets/t1/block-sender"),
        ("GET", "/tickets/blocked-senders"),
        ("DELETE", "/tickets/blocked-senders/b1"),
    ]


def test_cap_constant() -> None:
    assert _chat_files.MAX_MESSAGE_FILES == 5
