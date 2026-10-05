"""Tests for the capture tools (#11): `create_application_on_behalf` and its search.

The tools send camelCase keys and leave out the arguments that the agent did not
give, so the server applies its defaults (for example `receivedOn` = today).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp.tools import _common, applications


class _FakeApi:
    """Record each call and answer with a fixed body."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def get(self, path: str, **kw: Any) -> list[dict[str, Any]]:
        self.calls.append(("GET", path, kw.get("params")))
        return []

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(("POST", path, kw.get("json")))
        return {"applicationId": "a1"}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_create_for_an_account(fake_api: _FakeApi) -> None:
    out = asyncio.run(
        applications.create_application_on_behalf(
            type_id="t1", data={"title": "X"}, applicant_principal_id="p1", intake="per PDF"
        )
    )
    assert out == {"applicationId": "a1"}
    assert fake_api.calls == [
        (
            "POST",
            "/applications/on-behalf",
            {
                "typeId": "t1",
                "data": {"title": "X"},
                "applicantPrincipalId": "p1",
                "intake": "per PDF",
            },
        )
    ]


def test_create_for_a_guest(fake_api: _FakeApi) -> None:
    asyncio.run(
        applications.create_application_on_behalf(
            type_id="t1",
            data={},
            applicant_name="Gisela",
            applicant_email="g@example.org",
            received_on="2026-10-01",
        )
    )
    body = fake_api.calls[0][2]
    assert body["applicantName"] == "Gisela"
    assert body["applicantEmail"] == "g@example.org"
    assert body["receivedOn"] == "2026-10-01"
    assert "applicantPrincipalId" not in body


def test_search(fake_api: _FakeApi) -> None:
    asyncio.run(applications.search_on_behalf_applicants("an"))
    assert fake_api.calls == [("GET", "/applications/on-behalf/applicants", {"q": "an"})]
