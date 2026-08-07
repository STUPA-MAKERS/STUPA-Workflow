"""Router wiring and RBAC of the corporate-design routes, with a faked service."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.admin.router import get_cd_variant_service
from app.modules.admin.schemas import (
    CdVariantLogoOut,
    CdVariantOptionOut,
    CdVariantOut,
)
from app.shared.errors import ConflictError, NotFoundError

VARIANT_ID = uuid4()
LOGO_ID = uuid4()
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"/>'


class _FakeCdVariants:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _out(self) -> CdVariantOut:
        return CdVariantOut(
            id=VARIANT_ID,
            key="stupa",
            name="StuPa",
            base_variant="protocol",
            logos=[
                CdVariantLogoOut(
                    id=LOGO_ID, slot="title", position=0, vendored_name="STUPA"
                )
            ],
        )

    def _logo(self) -> CdVariantLogoOut:
        return CdVariantLogoOut(
            id=LOGO_ID, slot="title", position=0, file_name="x.svg",
            mime="image/svg+xml", size=len(SVG),
        )

    async def list_variants(self) -> list[CdVariantOut]:
        return [self._out()]

    async def list_variant_options(self) -> list[CdVariantOptionOut]:
        return [CdVariantOptionOut(id=VARIANT_ID, key="stupa", name="StuPa")]

    async def create_variant(self, payload: Any, actor: str) -> CdVariantOut:
        self.calls.append(f"create:{payload.key}")
        return self._out()

    async def update_variant(self, variant_id: UUID, payload: Any, actor: str) -> CdVariantOut:
        if payload.key is not None:
            raise ConflictError("cd variant key is immutable")
        return self._out()

    async def delete_variant(self, variant_id: UUID, actor: str) -> None:
        raise ConflictError("cd variant is still referenced by a gremium")

    async def add_vendored_logo(
        self, variant_id: UUID, payload: Any, actor: str
    ) -> CdVariantLogoOut:
        return CdVariantLogoOut(
            id=LOGO_ID, slot=payload.slot, position=0, vendored_name=payload.vendored_name
        )

    async def upload_logo(
        self, variant_id: UUID, data: bytes, *, slot: str, filename: str | None, actor: str
    ) -> CdVariantLogoOut:
        self.calls.append(f"upload:{slot}:{len(data)}")
        return self._logo()

    async def reorder_logos(
        self, variant_id: UUID, payload: Any, actor: str
    ) -> list[CdVariantLogoOut]:
        return [self._logo()]

    async def update_logo(self, logo_id: UUID, payload: Any, actor: str) -> CdVariantLogoOut:
        if str(logo_id).startswith("00000000"):
            raise NotFoundError("nope")
        return CdVariantLogoOut(
            id=logo_id, slot=payload.slot or "title", position=payload.position or 0
        )

    async def delete_logo(self, logo_id: UUID, actor: str) -> None:
        if str(logo_id).startswith("00000000"):
            raise NotFoundError("nope")

    async def logo_file_bytes(self, logo_id: UUID) -> tuple[bytes, str]:
        return SVG, 'wap"pen\n.svg'


@pytest.fixture
def service() -> _FakeCdVariants:
    return _FakeCdVariants()


@pytest.fixture
def app(service: _FakeCdVariants) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_cd_variant_service] = lambda: service
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as(app: FastAPI, *perms: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions=set(perms)
    )


_WRITE_CALLS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("get", "/api/admin/cd-variants", {}),
    ("post", "/api/admin/cd-variants", {"json": {"key": "senat", "name": "Senat"}}),
    ("patch", f"/api/admin/cd-variants/{VARIANT_ID}", {"json": {"name": "x"}}),
    ("delete", f"/api/admin/cd-variants/{VARIANT_ID}", {}),
    (
        "post",
        f"/api/admin/cd-variants/{VARIANT_ID}/logos/vendored",
        {"json": {"slot": "title", "vendoredName": "INF"}},
    ),
    (
        "put",
        f"/api/admin/cd-variants/{VARIANT_ID}/logos/order",
        {"json": {"slot": "title", "logoIds": []}},
    ),
    ("get", f"/api/admin/cd-variant-logos/{LOGO_ID}/file", {}),
    ("delete", f"/api/admin/cd-variant-logos/{LOGO_ID}", {}),
    ("patch", f"/api/admin/cd-variant-logos/{LOGO_ID}", {"json": {"slot": "footer"}}),
)


@pytest.mark.parametrize(("method", "path", "kwargs"), _WRITE_CALLS)
def test_requires_auth_401(
    client: TestClient, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    assert getattr(client, method)(path, **kwargs).status_code == 401


@pytest.mark.parametrize(("method", "path", "kwargs"), _WRITE_CALLS)
def test_forbidden_without_the_permission(
    app: FastAPI, client: TestClient, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    """Another admin key is not enough. The routes gate on `admin.cd_variants`."""
    _as(app, "admin.gremien", "admin.site", "admin.roles")
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert response.headers["content-type"].startswith("application/problem+json")


def test_upload_logo_requires_the_permission(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.gremien")
    response = client.post(
        f"/api/admin/cd-variants/{VARIANT_ID}/logos",
        data={"slot": "title"},
        files={"file": ("x.svg", SVG, "image/svg+xml")},
    )
    assert response.status_code == 403


def test_list_variants_camel_case(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.cd_variants")
    body = client.get("/api/admin/cd-variants").json()
    assert body[0]["baseVariant"] == "protocol"
    assert body[0]["logos"][0]["vendoredName"] == "STUPA"
    assert body[0]["logos"][0]["fileName"] is None


def test_create_variant_201(app: FastAPI, client: TestClient, service: _FakeCdVariants) -> None:
    _as(app, "admin.cd_variants")
    response = client.post("/api/admin/cd-variants", json={"key": "senat", "name": "Senat"})
    assert response.status_code == 201 and service.calls == ["create:senat"]


@pytest.mark.parametrize("key", ["Senat", "mit leerzeichen", "-lead", "trail-", ""])
def test_create_variant_rejects_a_non_slug_key(
    app: FastAPI, client: TestClient, key: str
) -> None:
    _as(app, "admin.cd_variants")
    response = client.post("/api/admin/cd-variants", json={"key": key, "name": "X"})
    assert response.status_code == 422


def test_patch_variant_key_conflicts(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.cd_variants")
    response = client.patch(f"/api/admin/cd-variants/{VARIANT_ID}", json={"key": "asta"})
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


def test_delete_variant_in_use_conflicts(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.cd_variants")
    response = client.delete(f"/api/admin/cd-variants/{VARIANT_ID}")
    assert response.status_code == 409 and response.json()["code"] == "conflict"


def test_add_vendored_logo_rejects_an_unknown_name(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.cd_variants")
    response = client.post(
        f"/api/admin/cd-variants/{VARIANT_ID}/logos/vendored",
        json={"slot": "title", "vendoredName": "NOT-A-LOGO"},
    )
    assert response.status_code == 422


def test_add_vendored_logo_rejects_an_unknown_slot(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.cd_variants")
    response = client.post(
        f"/api/admin/cd-variants/{VARIANT_ID}/logos/vendored",
        json={"slot": "sidebar", "vendoredName": "INF"},
    )
    assert response.status_code == 422


def test_add_vendored_logo_201(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.cd_variants")
    response = client.post(
        f"/api/admin/cd-variants/{VARIANT_ID}/logos/vendored",
        json={"slot": "footer", "vendoredName": "MAKERS-RAlign"},
    )
    assert response.status_code == 201
    assert response.json()["vendoredName"] == "MAKERS-RAlign"


def test_upload_logo_passes_the_bytes_and_slot(
    app: FastAPI, client: TestClient, service: _FakeCdVariants
) -> None:
    _as(app, "admin.cd_variants")
    response = client.post(
        f"/api/admin/cd-variants/{VARIANT_ID}/logos",
        data={"slot": "title"},
        files={"file": ("x.svg", SVG, "image/svg+xml")},
    )
    assert response.status_code == 201
    assert service.calls == [f"upload:title:{len(SVG)}"]


def test_reorder_logos_200(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.cd_variants")
    response = client.put(
        f"/api/admin/cd-variants/{VARIANT_ID}/logos/order",
        json={"slot": "title", "logoIds": [str(LOGO_ID)]},
    )
    assert response.status_code == 200 and response.json()[0]["fileName"] == "x.svg"


def test_delete_logo_204_and_404(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.cd_variants")
    assert client.delete(f"/api/admin/cd-variant-logos/{LOGO_ID}").status_code == 204
    missing = "00000000-0000-0000-0000-000000000001"
    assert client.delete(f"/api/admin/cd-variant-logos/{missing}").status_code == 404


def test_logo_download_is_always_an_attachment(app: FastAPI, client: TestClient) -> None:
    """A stored SVG must never come back inline — that would be XSS in the app origin."""
    _as(app, "admin.cd_variants")
    response = client.get(f"/api/admin/cd-variant-logos/{LOGO_ID}/file")
    assert response.status_code == 200
    assert response.content == SVG
    assert response.headers["content-type"] == "application/octet-stream"
    # The quote and the newline of the stored name are stripped from the header.
    assert response.headers["content-disposition"] == 'attachment; filename="wappen.svg"'


def test_options_list_open_to_the_gremien_page(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.gremien")
    response = client.get("/api/cd-variants")
    assert response.status_code == 200
    assert response.json() == [{"id": str(VARIANT_ID), "key": "stupa", "name": "StuPa"}]


def test_options_list_open_to_the_cd_page(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.cd_variants")
    assert client.get("/api/cd-variants").status_code == 200


def test_options_list_forbidden_without_either_key(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.site")
    assert client.get("/api/cd-variants").status_code == 403


def test_options_list_requires_auth_401(client: TestClient) -> None:
    assert client.get("/api/cd-variants").status_code == 401


def test_update_logo_moves_a_slot_200(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.cd_variants")
    r = client.patch(
        f"/api/admin/cd-variant-logos/{LOGO_ID}", json={"slot": "footer", "position": 2}
    )
    assert r.status_code == 200
    assert r.json()["slot"] == "footer"
    assert r.json()["position"] == 2


def test_update_logo_unknown_404(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.cd_variants")
    r = client.patch(
        "/api/admin/cd-variant-logos/00000000-0000-0000-0000-000000000000",
        json={"slot": "footer"},
    )
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


def test_update_logo_rejects_an_unknown_slot_422(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin.cd_variants")
    r = client.patch(f"/api/admin/cd-variant-logos/{LOGO_ID}", json={"slot": "middle"})
    assert r.status_code == 422
