"""§ NF/compatibility/links/000592: an old German API path answers like its English path."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware import LegacyPathMiddleware, english_api_path


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("/api/gremien", "/api/committees"),
        ("/api/gremien/overview", "/api/committees/overview"),
        ("/api/gremien/g1/meeting-members", "/api/committees/g1/meeting-members"),
        ("/api/admin/gremien/g1/roles", "/api/admin/committees/g1/roles"),
        ("/api/meetings/gremien", "/api/meetings/committees"),
        ("/api/public/gremien", "/api/public/committees"),
        ("/api/admin/privacy/auskunft", "/api/admin/privacy/export"),
        ("/api/admin/gremium-roles/r1", "/api/admin/committee-roles/r1"),
        ("/api/admin/gremium-membership-mappings", "/api/admin/committee-membership-mappings"),
        ("/api/admin/gremium-role-mappings/m1", "/api/admin/committee-role-mappings/m1"),
        ("/api/meetings/m1/protokollant-handover", "/api/meetings/m1/minute-taker-handover"),
        ("/api/ws/meetings/m1/beamer", "/api/ws/meetings/m1/projector"),
    ],
)
def test_an_old_api_path_maps_to_its_english_path(old: str, new: str) -> None:
    """Every old prefix maps to its English prefix and keeps the rest of the path."""
    assert english_api_path(old) == new


@pytest.mark.parametrize(
    "path",
    [
        "/api/committees",
        "/api/gremienx",
        "/api/meetings/m1",
        "/gremien",
        "/api/admin/privacy/auskunftx",
        "/api/meetings/m1/protokollant-handoverx",
    ],
)
def test_other_paths_stay(path: str) -> None:
    """A prefix matches a whole segment only, and an English path stays as it is."""
    assert english_api_path(path) == path


def test_the_old_path_answers_like_the_new_path() -> None:
    """The route of the English path answers a request to the old path, with the query."""
    app = FastAPI()

    @app.get("/api/committees/{gid}/logo")
    def logo(gid: str, size: int = 0) -> dict[str, object]:
        return {"gid": gid, "size": size}

    app.add_middleware(LegacyPathMiddleware)
    client = TestClient(app)
    old = client.get("/api/gremien/g1/logo?size=2")
    new = client.get("/api/committees/g1/logo?size=2")
    assert old.status_code == 200
    assert old.json() == new.json() == {"gid": "g1", "size": 2}
