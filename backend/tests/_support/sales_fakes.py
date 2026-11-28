"""A fake pretix instance and a fake Mollie API behind an `httpx.MockTransport`.

Each fake keeps its objects in memory and answers the GET routes that the clients of the
platform call, one object per page, so each read also follows the `next` links. A test
reads `requests` to prove what the platform sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.modules.mollie.client import API_ROOT, MollieClient
from app.modules.pretix.client import PretixClient

PRETIX_HOST = "pretix.test"
PRETIX_URL = f"https://{PRETIX_HOST}"
ORGANIZER = "stupa"
PRETIX_TOKEN = "pretix-token-0123456789"
MOLLIE_TOKEN = "live_mollie-token-0123456789"


def _page(rows: list[dict[str, Any]], request: httpx.Request) -> dict[str, Any]:
    """One row per page, with the address of the next page."""
    index = int(request.url.params.get("page", "1"))
    following = (
        str(request.url.copy_merge_params({"page": str(index + 1)})) if index < len(rows) else None
    )
    return {"results": rows[index - 1 : index], "next": following}


@dataclass
class FakePretix:
    """One pretix organizer in memory.

    Attributes:
        events: The events of the organizer.
        items: The products of each event by slug.
        quotas: The quotas of each event by slug.
        orders: The orders of each event by slug.
        status: Each request gets this error status.
        down: Each request fails with a connect error.
    """

    events: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    items: dict[str, list[dict[str, Any]]] = field(default_factory=dict[str, list[dict[str, Any]]])
    quotas: dict[str, list[dict[str, Any]]] = field(default_factory=dict[str, list[dict[str, Any]]])
    orders: dict[str, list[dict[str, Any]]] = field(default_factory=dict[str, list[dict[str, Any]]])
    status: int | None = None
    down: bool = False
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("down")
        if self.status is not None:
            return httpx.Response(self.status)
        if request.method != "GET":
            return httpx.Response(405)
        root = f"/api/v1/organizers/{ORGANIZER}/events/"
        path = request.url.path
        if not path.startswith(root):
            return httpx.Response(404)
        parts = [part for part in path[len(root) :].split("/") if part]
        if not parts:
            return httpx.Response(200, json=_page(self.events, request))
        found = next((e for e in self.events if e["slug"] == parts[0]), None)
        if found is None:
            return httpx.Response(404)
        if len(parts) == 1:
            return httpx.Response(200, json=found)
        lists = {"items": self.items, "quotas": self.quotas, "orders": self.orders}
        return httpx.Response(200, json=_page(lists[parts[1]].get(parts[0], []), request))

    def client(
        self, base_url: str, organizer: str, token: str, allowlist: tuple[str, ...]
    ) -> PretixClient:
        """The client factory of the connection, bound to this fake."""
        return PretixClient(
            base_url=base_url,
            organizer=organizer,
            token=token,
            allowlist=allowlist,
            client_factory=lambda _t: httpx.AsyncClient(
                transport=httpx.MockTransport(self._answer)
            ),
        )


@dataclass
class FakeMollie:
    """One Mollie organization in memory.

    Attributes:
        payments, refunds, chargebacks, settlements: The objects of each list.
        transactions: The balance transactions of the one balance `bal_1`.
        status: Each request gets this error status.
    """

    name: str = "Studierendenschaft"
    payments: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    refunds: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    chargebacks: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    settlements: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    transactions: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    status: int | None = None
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])

    def _list(self, embedded: str, rows: list[dict[str, Any]], request: httpx.Request) -> Any:
        page = _page(rows, request)
        following = page["next"]
        return {
            "_embedded": {embedded: page["results"]},
            "_links": {"next": {"href": following} if following else None},
        }

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status is not None:
            return httpx.Response(self.status)
        if request.method != "GET":
            return httpx.Response(405)
        path = request.url.path.removeprefix("/v2")
        lists = {
            "/payments": ("payments", self.payments),
            "/refunds": ("refunds", self.refunds),
            "/chargebacks": ("chargebacks", self.chargebacks),
            "/settlements": ("settlements", self.settlements),
            "/balances": ("balances", [{"id": "bal_1"}]),
            "/balances/bal_1/transactions": ("balance_transactions", self.transactions),
        }
        if path == "/organizations/me":
            return httpx.Response(200, json={"name": self.name})
        if path not in lists:
            return httpx.Response(404)
        embedded, rows = lists[path]
        return httpx.Response(200, json=self._list(embedded, rows, request))

    def client(self, token: str) -> MollieClient:
        """The client factory of the connection, bound to this fake."""
        return MollieClient(
            token=token,
            client_factory=lambda _t: httpx.AsyncClient(
                transport=httpx.MockTransport(self._answer)
            ),
        )


def money(value: str) -> dict[str, str]:
    """An amount object of Mollie."""
    return {"value": value, "currency": "EUR"}


__all__ = [
    "API_ROOT",
    "MOLLIE_TOKEN",
    "ORGANIZER",
    "PRETIX_HOST",
    "PRETIX_TOKEN",
    "PRETIX_URL",
    "FakeMollie",
    "FakePretix",
    "money",
]
