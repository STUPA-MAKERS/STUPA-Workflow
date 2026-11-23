"""Integration: the web push API of the own account (real Postgres).

§F/collaboration/notifications/002500: one subscription per device, a list, a remove.
§F/collaboration/notifications/002501: the push switches do not touch the mail switches.
§F/collaboration/notifications/002502: only the urgent kinds push by default.
§F/collaboration/notifications/002505: the platform makes its key once and keeps it.
§F/collaboration/notifications/002507: only accounts reach the routes.
§F/collaboration/notifications/002510: only endpoints of known push services.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from tests.integration.modules.tickets.conftest import Api, add_principal

pytestmark = pytest.mark.integration

PIA = Principal(sub="pia-sub", email="pia@example.org")
OLE = Principal(sub="ole-sub", email="ole@example.org")
ENDPOINT = "https://fcm.googleapis.com/fcm/send/device-1"
DEVICE = {"endpoint": ENDPOINT, "keys": {"p256dh": "BKey", "auth": "auth"}, "label": "Pixel"}


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


async def _people(maker: async_sessionmaker[AsyncSession]) -> None:
    await add_principal(maker, sub=PIA.sub, email=PIA.email)
    await add_principal(maker, sub=OLE.sub, email=OLE.email)


async def test_routes_need_an_account(api: Api, maker: async_sessionmaker[AsyncSession]) -> None:
    with TestClient(api.app) as client:
        for path in ("/api/push/key", "/api/push/devices", "/api/push/preferences"):
            _ok(client.get(path), 401)


async def test_key_is_made_once(api: Api, maker: async_sessionmaker[AsyncSession]) -> None:
    await _people(maker)
    with TestClient(api.app) as client:
        api.login(PIA)
        first = _ok(client.get("/api/push/key"))["publicKey"]
        api.login(OLE)
        assert _ok(client.get("/api/push/key"))["publicKey"] == first
        assert len(first) == 87


async def test_devices_add_list_move_remove(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """A second subscribe of a device updates it; a device of another person is 404."""
    await _people(maker)
    with TestClient(api.app) as client:
        api.login(PIA)
        added = _ok(client.post("/api/push/devices", json=DEVICE), 201)
        assert added["label"] == "Pixel" and added["lastSuccessAt"] is None
        again = _ok(client.post("/api/push/devices", json={**DEVICE, "label": "Pixel 9"}), 201)
        assert again["id"] == added["id"]
        assert [d["label"] for d in _ok(client.get("/api/push/devices"))] == ["Pixel 9"]
        api.login(OLE)
        _ok(client.delete(f"/api/push/devices/{added['id']}"), 404)
        moved = _ok(client.post("/api/push/devices", json=DEVICE), 201)
        assert moved["id"] == added["id"]
        api.login(PIA)
        assert _ok(client.get("/api/push/devices")) == []
        api.login(OLE)
        _ok(client.delete(f"/api/push/devices/{added['id']}"), 204)
        assert _ok(client.get("/api/push/devices")) == []


async def test_device_endpoint_must_be_a_push_service(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await _people(maker)
    with TestClient(api.app) as client:
        api.login(PIA)
        for endpoint in ("http://fcm.googleapis.com/x", "https://intranet.example.org/x"):
            _ok(client.post("/api/push/devices", json={**DEVICE, "endpoint": endpoint}), 422)
        _ok(client.post("/api/push/devices", json={**DEVICE, "extra": 1}), 422)


async def test_preferences_default_and_save(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Urgent kinds start on; a save changes push only, the mail switches stay."""
    await _people(maker)
    with TestClient(api.app) as client:
        api.login(PIA)
        prefs = dict((p["kind"], p["enabled"]) for p in _ok(client.get("/api/push/preferences")))
        assert prefs["mention"] is True and prefs["status_update"] is False
        mails = _ok(client.get("/api/notifications/preferences"))
        saved = _ok(
            client.put(
                "/api/push/preferences",
                json={
                    "preferences": [
                        {"kind": "mention", "enabled": False},
                        {"kind": "status_update", "enabled": True},
                    ]
                },
            )
        )
        after = {p["kind"]: p["enabled"] for p in saved}
        assert after["mention"] is False and after["status_update"] is True
        assert _ok(client.get("/api/notifications/preferences")) == mails
        reset = _ok(
            client.put(
                "/api/push/preferences",
                json={"preferences": [{"kind": "mention", "enabled": True}]},
            )
        )
        assert {p["kind"]: p["enabled"] for p in reset}["mention"] is True
        _ok(
            client.put(
                "/api/push/preferences",
                json={"preferences": [{"kind": "magic_link", "enabled": True}]},
            ),
            422,
        )
