"""Router tests of the comment mentions (fake service, no database).

The routes pass the mentions and ``may_mention`` (``Access.can_see_internal``) to the
service, queue ``comment_mentioned`` for the added mentions only, and answer the
mentionable persons to a member only (403 in the applicant view).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.applications.router import get_mention_mail_sender
from tests.unit.modules.applications.test_applications_router import (
    _as_applicant,
    _as_principal,
    _FakeService,
    app,
    client,
    fake_service,
    sent,
)

__all__ = ["app", "client", "fake_service", "sent"]


@pytest.fixture
def mention_mails(app: FastAPI) -> list[tuple[object, ...]]:
    calls: list[tuple[object, ...]] = []

    async def _record(*args: object) -> None:
        calls.append(args)

    app.dependency_overrides[get_mention_mail_sender] = lambda: _record
    return calls


def test_a_member_comment_passes_the_mentions_and_mails_them(
    app: FastAPI,
    client: TestClient,
    fake_service: _FakeService,
    mention_mails: list[tuple[object, ...]],
) -> None:
    _as_principal(app, "application.read")
    ada = uuid4()
    r = client.post(
        f"/api/applications/{uuid4()}/comments",
        json={"body": "@Ada", "visibility": "internal", "mentions": [str(ada)]},
    )
    assert r.status_code == 201, r.text
    assert fake_service.comment_mentions == ([ada], True)
    assert r.json()["mentions"] == []
    ((_settings, comment_id, recipients, actor, _pool),) = mention_mails
    assert comment_id == UUID(r.json()["id"])
    assert (recipients, actor) == ([ada], "admin")


def test_a_comment_without_mentions_queues_no_mention_mail(
    app: FastAPI,
    client: TestClient,
    fake_service: _FakeService,
    mention_mails: list[tuple[object, ...]],
) -> None:
    _as_principal(app, "application.read")
    r = client.post(f"/api/applications/{uuid4()}/comments", json={"body": "x"})
    assert r.status_code == 201
    assert fake_service.comment_mentions == ([], True)
    assert mention_mails == []


def test_the_applicant_may_not_mention(
    app: FastAPI,
    client: TestClient,
    fake_service: _FakeService,
    mention_mails: list[tuple[object, ...]],
) -> None:
    app_id = uuid4()
    _as_applicant(app, app_id, "view")
    r = client.post(f"/api/applications/{app_id}/comments", json={"body": "x", "mentions": []})
    assert r.status_code == 201
    # The service refuses a non-empty list without ``may_mention`` (422).
    assert fake_service.comment_mentions == ([], False)
    assert mention_mails == []


def test_more_than_fifty_mentions_are_422(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "application.read")
    r = client.post(
        f"/api/applications/{uuid4()}/comments",
        json={"body": "x", "mentions": [str(uuid4()) for _ in range(51)]},
    )
    assert r.status_code == 422


def test_the_patch_keeps_or_replaces_the_mentions(
    app: FastAPI,
    client: TestClient,
    fake_service: _FakeService,
    mention_mails: list[tuple[object, ...]],
) -> None:
    _as_principal(app, "application.read")
    app_id, cid, ada = uuid4(), uuid4(), uuid4()
    r = client.patch(f"/api/applications/{app_id}/comments/{cid}", json={"body": "neu"})
    assert r.status_code == 200
    assert fake_service.comment_write_mentions == (None, True)
    assert mention_mails == []
    r = client.patch(
        f"/api/applications/{app_id}/comments/{cid}",
        json={"body": "neu", "mentions": [str(ada)]},
    )
    assert r.status_code == 200
    assert fake_service.comment_write_mentions == ([ada], True)
    ((_settings, comment_id, recipients, actor, _pool),) = mention_mails
    assert (comment_id, recipients, actor) == (cid, [ada], "admin")


def test_the_mentionable_route_is_for_members_only(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    app_id = uuid4()
    _as_applicant(app, app_id, "view")
    r = client.get(f"/api/applications/{app_id}/mentionable")
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")
    _as_principal(app, "application.read")
    r = client.get(f"/api/applications/{app_id}/mentionable")
    assert r.status_code == 200
    assert [p["displayName"] for p in r.json()] == ["Ada"]
    assert set(r.json()[0]) == {"principalId", "displayName"}
    assert fake_service.mentionable_for == app_id
