"""§ 002922: the link tools name a Paperless end by its document number.

§ 002920: the default scope of the package asks for the opt-in scope `paperless:use`.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.config import DEFAULT_SCOPE
from antragsplattform_mcp.tools import _common, links

_REF_41 = str(uuid.UUID(int=(int.from_bytes(b"paperles") << 64) | 41))
_CARD = "7b0c1d2e-0000-4000-8000-000000000001"


class _FakeApi:
    """Record each request and answer with one Paperless row."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def get(self, path: str, **kw: Any) -> Any:
        self.calls.append(("GET", path, kw.get("params")))
        row = {"kind": "paperless", "targetId": _REF_41, "title": "Angebot"}
        return [row] if path == "/links/targets" else {"links": [row]}

    async def post(self, path: str, **kw: Any) -> Any:
        self.calls.append(("POST", path, kw.get("json")))
        return {"links": [{"kind": "paperless", "targetId": _REF_41}, {"kind": "todo"}]}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_a_paperless_end_goes_by_its_number(fake_api: _FakeApi) -> None:
    """The tools send the row id of the number and answer with `documentNumber`."""
    out = asyncio.run(
        links.link_add(S.LinkEndIn(kind="todo", id=_CARD), S.LinkEndIn(kind="paperless", id="41"))
    )
    assert fake_api.calls[-1] == (
        "POST",
        "/links",
        {"a": {"kind": "todo", "id": _CARD}, "b": {"kind": "paperless", "id": _REF_41}},
    )
    assert out["links"][0]["documentNumber"] == 41
    assert "documentNumber" not in out["links"][1]

    listed = asyncio.run(links.link_list("paperless", "41"))
    assert fake_api.calls[-1] == ("GET", "/links", {"kind": "paperless", "id": _REF_41})
    assert listed["links"][0]["documentNumber"] == 41

    hits = asyncio.run(links.link_targets(q="Angebot", kind="paperless"))
    assert hits[0]["documentNumber"] == 41
    asyncio.run(links.link_targets(exclude_kind="paperless", exclude_id="41"))
    assert fake_api.calls[-1][2]["excludeId"] == _REF_41

    asyncio.run(links.paperless_document_address("protocol", _CARD))
    assert fake_api.calls[-1] == ("GET", f"/paperless/documents/protocol/{_CARD}", None)


def test_a_paperless_end_refuses_an_id_that_is_no_number(fake_api: _FakeApi) -> None:
    """A UUID or a number below 1 is no document number."""
    for bad in (_REF_41, "0", "-3"):
        with pytest.raises(ValueError, match="document number"):
            asyncio.run(
                links.link_add(
                    S.LinkEndIn(kind="todo", id=_CARD), S.LinkEndIn(kind="paperless", id=bad)
                )
            )
    assert fake_api.calls == []
    assert links.document_number("not-a-uuid") is None
    assert links.document_number(_CARD) is None
    assert links.document_number(_REF_41) == 41


def test_the_default_scope_asks_for_paperless() -> None:
    """The package asks for `paperless:use` without a setting; the consent page gates it."""
    assert "paperless:use" in DEFAULT_SCOPE.split()
