"""Unit tests of the Paperless client against a fake instance.

§F/integrations/paperless/002513 each call carries the token of the connection.
§F/integrations/paperless/002522 the client has no call with the method DELETE.
§NF/security/network/002514 the client calls only a host of the allowlist and follows no
redirect. §NF/security/network/002515 an error carries a cause code and no text.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.modules.paperless.client import (
    PaperlessClient,
    PaperlessError,
    TaskState,
    Upload,
    document_url,
    host_allowed,
    normalize_url,
)
from tests._support.paperless_fakes import BASE_URL, HOST, TOKEN, FakePaperless

UPLOAD = Upload(
    filename="Protokoll.pdf",
    content=b"%PDF-1.7 x",
    mime="application/pdf",
    title="1. Sitzung",
    created=date(2031, 5, 2),
    document_type=7,
    tags=(3, 4),
)


def _answering(response: httpx.Response) -> PaperlessClient:
    return PaperlessClient(
        base_url=BASE_URL,
        token=TOKEN,
        allowlist=(HOST,),
        client_factory=lambda _t: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: response)
        ),
    )


def _raising(error: Exception) -> PaperlessClient:
    def _raise(request: httpx.Request) -> httpx.Response:
        raise error

    return PaperlessClient(
        base_url=BASE_URL,
        token=TOKEN,
        allowlist=(HOST,),
        client_factory=lambda _t: httpx.AsyncClient(transport=httpx.MockTransport(_raise)),
    )


@pytest.mark.parametrize(
    ("url", "allowlist", "allowed"),
    [
        ("https://paperless.test", ["paperless.test"], True),
        ("http://PAPERLESS.test:8000/dms", [" Paperless.Test "], True),
        ("http://paperless.test:8000", ["paperless.test:8000"], True),
        ("https://other.test", ["paperless.test"], False),
        ("https://paperless.test", [], False),
        ("https://paperless.test", [" "], False),
        ("ftp://paperless.test", ["paperless.test"], False),
        ("https://user@paperless.test", ["paperless.test"], False),
        ("paperless.test", ["paperless.test"], False),
    ],
)
def test_host_allowed(url: str, allowlist: list[str], allowed: bool) -> None:
    assert host_allowed(url, allowlist) is allowed


def test_normalize_url_and_document_url() -> None:
    assert normalize_url(" https://paperless.test/dms/ ") == "https://paperless.test/dms"
    assert document_url(BASE_URL, 12) == "https://paperless.test/documents/12/details"


async def test_each_request_carries_the_token_and_none_deletes() -> None:
    fake = FakePaperless()
    client = fake.client()
    await client.check()
    type_id = await client.ensure("document_types", "Protokoll")
    assert await client.ensure("document_types", "protokoll") == type_id
    tag_id = await client.ensure("tags", "StuPa")
    field_id = await client.ensure("custom_fields", "Plattform")
    task = await client.upload(
        Upload(
            filename="p.pdf",
            content=b"%PDF",
            mime="application/pdf",
            title="1. Sitzung",
            created=date(2031, 5, 2),
            document_type=type_id,
            tags=(tag_id,),
        )
    )
    state = await client.task(task)
    assert state == TaskState(done=True, document_id=100)
    await client.set_link(100, field_id, "https://stupa.example/meetings/1")
    await client.add_tag(100, tag_id)
    replaced = await client.ensure("tags", "Ersetzt")
    await client.add_tag(100, replaced)

    assert fake.documents[100]["custom_fields"] == [
        {"field": field_id, "value": "https://stupa.example/meetings/1"}
    ]
    assert fake.documents[100]["tags"] == [tag_id, replaced]
    assert fake.uploads[0]["title"] == "1. Sitzung"
    assert fake.uploads[0]["created"] == "2031-05-02"
    assert {r.headers["Authorization"] for r in fake.requests} == {f"Token {TOKEN}"}
    assert "DELETE" not in {r.method for r in fake.requests}
    assert {r.url.host for r in fake.requests} == {HOST}


async def test_set_link_keeps_the_other_custom_fields() -> None:
    fake = FakePaperless()
    fake.documents[5] = {
        "id": 5,
        "tags": [],
        "custom_fields": [{"field": 1, "value": "x"}, {"field": 2, "value": "old"}, "junk"],
    }
    await fake.client().set_link(5, 2, "https://stupa.example/a")
    assert fake.documents[5]["custom_fields"] == [
        {"field": 1, "value": "x"},
        {"field": 2, "value": "https://stupa.example/a"},
    ]


async def test_a_host_outside_the_allowlist_gets_no_request() -> None:
    fake = FakePaperless()
    with pytest.raises(PaperlessError) as exc:
        await fake.client(allowlist=("other.test",)).check()
    assert exc.value.code == "blocked"
    assert fake.requests == []


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(302, headers={"location": "https://evil.test"}), "redirect"),
        (httpx.Response(401, json={}), "unauthorized"),
        (httpx.Response(403, json={}), "unauthorized"),
        (httpx.Response(500, json={}), "status"),
        (httpx.Response(200, text="<html>"), "format"),
        (httpx.Response(200, json=[1]), "format"),
    ],
)
async def test_an_error_answer_is_a_cause_code(response: httpx.Response, code: str) -> None:
    with pytest.raises(PaperlessError) as exc:
        await _answering(response).check()
    assert exc.value.code == code
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("refused"), "unreachable"),
    ],
)
async def test_a_transport_error_is_a_cause_code(error: Exception, code: str) -> None:
    with pytest.raises(PaperlessError) as exc:
        await _raising(error).check(1.0)
    assert exc.value.code == code


async def test_ensure_needs_an_id_in_the_answer() -> None:
    with pytest.raises(PaperlessError) as exc:
        await _answering(httpx.Response(200, json={"results": []})).ensure("tags", "StuPa")
    assert exc.value.code == "format"


async def test_upload_needs_a_task_id() -> None:
    with pytest.raises(PaperlessError) as exc:
        await _answering(httpx.Response(200, json={"task": 1})).upload(UPLOAD)
    assert exc.value.code == "format"


@pytest.mark.parametrize(
    ("body", "state"),
    [
        ([], TaskState(done=False)),
        ({"results": ["x"]}, TaskState(done=False)),
        ([{"status": "PENDING"}], TaskState(done=False)),
        ([{"status": "FAILURE"}], TaskState(done=True, failed=True)),
        ([{"status": "SUCCESS", "related_document": 12}], TaskState(done=True, document_id=12)),
        ({"results": [{"status": "SUCCESS", "related_document": "13"}]}, TaskState(True, 13)),
        ([{"status": "SUCCESS", "related_document": None}], TaskState(done=True, failed=True)),
        ([{"status": "SUCCESS", "related_document": True}], TaskState(done=True, failed=True)),
    ],
)
async def test_task_states(body: object, state: TaskState) -> None:
    assert await _answering(httpx.Response(200, json=body)).task("t") == state


async def test_document_read_needs_an_object() -> None:
    with pytest.raises(PaperlessError) as exc:
        await _answering(httpx.Response(200, json=[])).add_tag(1, 2)
    assert exc.value.code == "format"


async def test_add_tag_skips_a_tag_that_is_set() -> None:
    fake = FakePaperless()
    fake.documents[5] = {"id": 5, "tags": [9], "custom_fields": []}
    await fake.client().add_tag(5, 9)
    assert [r.method for r in fake.requests] == ["GET"]
