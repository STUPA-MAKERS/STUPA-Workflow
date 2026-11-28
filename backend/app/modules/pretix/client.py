"""The read-only HTTP client of the pretix REST API.

Each call carries the team token of the connection and uses the method GET only
(§F/integrations/pretix/003089). The client checks the host of the address against the
deploy setting `PRETIX_HOST_ALLOWLIST` before each call and follows no redirect
(§NF/security/network/003100), so a changed list also stops a stored address.

The client reads only the values that the platform keeps (§F/integrations/pretix/003088):
of an event its slug, name, dates and public address; of a product its id and name; of a
quota its name and free places; of an order its code, status, sum, dates, the products of
its positions, and the amounts and dates of its payments and refunds. It never reads a
name, an email address, an address or an answer of an order into a value of its own.

A failure is a `PretixError` with a short cause code and never the text of an exception or
of an answer, because such a text can hold the token or an internal address
(§NF/security/network/003101).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx

from app.shared.ssrf import host_allowed

#: The causes of a failed call. `blocked`: the host is not in the allowlist.
#: `unauthorized`: pretix refuses the token. `not_found`: no organizer or event with this
#: name. `status`: another error answer. `format`: an answer that is not the JSON of the API.
ErrorCode = Literal[
    "blocked", "timeout", "unreachable", "redirect", "unauthorized", "not_found", "status", "format"
]

TIMEOUT_SECONDS = 20.0

#: The most pages of one list, so a broken `next` address never loops.
MAX_PAGES = 500

#: The order statuses of pretix: pending, paid, expired, cancelled.
OrderStatus = Literal["n", "p", "e", "c"]


class PretixError(Exception):
    """A call to pretix failed. ``code`` is the short cause."""

    def __init__(self, code: ErrorCode) -> None:
        """Keep the cause code."""
        super().__init__(code)
        self.code: ErrorCode = code


def normalize_url(url: str) -> str:
    """Trim the address and drop the slash at its end."""
    return url.strip().rstrip("/")


def address_allowed(url: str, allowlist: Sequence[str]) -> bool:
    """Tell whether the address is `http` or `https` and its host is in the allowlist.

    An empty list allows no address (§NF/security/network/003100).
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme.lower() not in ("http", "https") or not host or parts.username:
        return False
    return host_allowed(host, parts.port, allowlist)


@dataclass(frozen=True, slots=True)
class PretixEvent:
    """One event of the organizer: slug, name, first day and public address."""

    slug: str
    name: str
    date_from: date | None = None
    public_url: str | None = None


@dataclass(frozen=True, slots=True)
class Product:
    """One product of an event."""

    id: int
    name: str


@dataclass(frozen=True, slots=True)
class Quota:
    """One quota of an event with its free places, or None for an unlimited quota."""

    name: str
    available: int | None


@dataclass(frozen=True, slots=True)
class Money:
    """One payment or refund of an order that pretix finished: id, amount, day."""

    local_id: int
    amount: Decimal
    on: date | None


@dataclass(frozen=True, slots=True)
class Order:
    """One order without any personal value (§F/integrations/pretix/003088).

    Attributes:
        code: The code of the order.
        status: One of `OrderStatus`.
        total: The sum of the order.
        payment_date: The day pretix took the payment, else None.
        products: The product id of each position.
        payments: The confirmed payments.
        refunds: The finished refunds.
    """

    code: str
    status: OrderStatus
    total: Decimal
    payment_date: date | None
    products: tuple[int, ...]
    payments: tuple[Money, ...]
    refunds: tuple[Money, ...]


def _text(value: object) -> str:
    """Read a name that pretix gives as a text or as a text per language."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        texts = [str(text) for text in value.values() if isinstance(text, str) and text]
        return str(value.get("de") or value.get("en") or (texts[0] if texts else ""))
    return ""


def _day(value: object) -> date | None:
    """Read the day of a date or a timestamp that pretix gives as text."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _amount(value: object) -> Decimal:
    """Read an amount that pretix gives as a decimal text; anything else is zero."""
    try:
        return Decimal(str(value)) if isinstance(value, str | int | float) else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


def _int(value: object) -> int | None:
    """Read a whole number; a bool is none."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def event_of(raw: Mapping[str, object]) -> PretixEvent | None:
    """Read one event of the list, or None without a slug."""
    slug = raw.get("slug")
    if not isinstance(slug, str) or not slug:
        return None
    public = raw.get("public_url")
    return PretixEvent(
        slug=slug,
        name=_text(raw.get("name")) or slug,
        date_from=_day(raw.get("date_from")),
        public_url=public if isinstance(public, str) and public else None,
    )


def _money(rows: object, done: frozenset[str], day_key: str) -> tuple[Money, ...]:
    """Read the payments or refunds of an order whose state is one of `done`."""
    items = rows if isinstance(rows, list) else []
    return tuple(
        Money(
            local_id=local_id,
            amount=_amount(row.get("amount")),
            on=_day(row.get(day_key)) or _day(row.get("created")),
        )
        for row in items
        if isinstance(row, dict)
        and row.get("state") in done
        and (local_id := _int(row.get("local_id"))) is not None
    )


def order_of(raw: Mapping[str, object]) -> Order | None:
    """Read one order, or None without a code or a known status.

    Only the code, the status, the sum, the payment day, the products of the positions
    and the money are read; every other value of the order stays out.
    """
    code = raw.get("code")
    status = raw.get("status")
    if not isinstance(code, str) or not code or status not in ("n", "p", "e", "c"):
        return None
    positions = raw.get("positions")
    return Order(
        code=code,
        status=status,
        total=_amount(raw.get("total")),
        payment_date=_day(raw.get("payment_date")),
        products=tuple(
            item
            for row in (positions if isinstance(positions, list) else [])
            if isinstance(row, dict) and (item := _int(row.get("item"))) is not None
        ),
        payments=_money(raw.get("payments"), frozenset({"confirmed"}), "payment_date"),
        refunds=_money(raw.get("refunds"), frozenset({"done"}), "execution_date"),
    )


def _client(timeout_seconds: float) -> httpx.AsyncClient:  # pragma: no cover - real HTTP
    return httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(timeout_seconds))


@dataclass(frozen=True, slots=True)
class PretixClient:
    """Read from one organizer of a pretix instance with the token of the connection.

    A test injects the HTTP client factory.
    """

    base_url: str
    organizer: str
    token: str
    allowlist: tuple[str, ...]
    timeout_seconds: float = TIMEOUT_SECONDS
    client_factory: Callable[[float], httpx.AsyncClient] = _client

    def _root(self) -> str:
        return f"{self.base_url}/api/v1/organizers/{quote(self.organizer, safe='')}"

    async def _get(self, url: str, params: Mapping[str, str] | None = None) -> object:
        """Send one GET and return the JSON of the answer.

        Raises:
            PretixError: The host is not allowed, pretix does not answer in time, or it
                answers with a redirect, an error or no JSON.
        """
        if not address_allowed(url, self.allowlist) or not url.startswith(self.base_url):
            raise PretixError("blocked")
        try:
            async with self.client_factory(self.timeout_seconds) as client:
                response = await client.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Token {self.token}", "Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise PretixError("timeout") from exc
        except httpx.HTTPError as exc:
            raise PretixError("unreachable") from exc
        if 300 <= response.status_code < 400:
            raise PretixError("redirect")
        if response.status_code in (401, 403):
            raise PretixError("unauthorized")
        if response.status_code == 404:
            raise PretixError("not_found")
        if not 200 <= response.status_code < 300:
            raise PretixError("status")
        try:
            return response.json()
        except ValueError as exc:
            raise PretixError("format") from exc

    async def _pages(
        self, url: str, params: Mapping[str, str] | None, left: int
    ) -> tuple[Mapping[str, object], ...]:
        """Read one page of a list and each page after it.

        Raises:
            PretixError: A call fails or a page is not a list of the API.
        """
        body = await self._get(url, params)
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise PretixError("format")
        rows = tuple(row for row in body["results"] if isinstance(row, dict))
        following = body.get("next")
        rest = (
            await self._pages(following, None, left - 1)
            if isinstance(following, str) and following and left > 1
            else ()
        )
        return rows + rest

    async def _list(
        self, path: str, params: Mapping[str, str] | None = None
    ) -> tuple[Mapping[str, object], ...]:
        """Read every page of a list of the API, at most `MAX_PAGES`."""
        return await self._pages(f"{self._root()}{path}", params, MAX_PAGES)

    async def check(self) -> None:
        """Read one event row, which proves the address, the organizer and the token.

        Raises:
            PretixError: The connection does not work.
        """
        body = await self._get(f"{self._root()}/events/", {"page_size": "1"})
        if not isinstance(body, dict) or "results" not in body:
            raise PretixError("format")

    async def events(self) -> tuple[PretixEvent, ...]:
        """Return each event of the organizer, the newest first."""
        rows = await self._list("/events/", {"ordering": "-date_from"})
        return tuple(event for row in rows if (event := event_of(row)) is not None)

    async def event(self, slug: str) -> PretixEvent:
        """Return one event of the organizer.

        Raises:
            PretixError: `not_found` for an unknown slug, or another failure.
        """
        body = await self._get(f"{self._root()}/events/{quote(slug, safe='')}/")
        found = event_of(body) if isinstance(body, dict) else None
        if found is None:
            raise PretixError("format")
        return found

    async def products(self, slug: str) -> tuple[Product, ...]:
        """Return the products of an event."""
        rows = await self._list(f"/events/{quote(slug, safe='')}/items/")
        return tuple(
            Product(id=item_id, name=_text(row.get("name")) or str(item_id))
            for row in rows
            if (item_id := _int(row.get("id"))) is not None
        )

    async def quotas(self, slug: str) -> tuple[Quota, ...]:
        """Return the quotas of an event with their free places."""
        rows = await self._list(
            f"/events/{quote(slug, safe='')}/quotas/", {"with_availability": "true"}
        )
        return tuple(
            Quota(name=_text(row.get("name")), available=_int(row.get("available_number")))
            for row in rows
        )

    async def orders(self, slug: str) -> tuple[Order, ...]:
        """Return each order of an event without its personal values."""
        rows = await self._list(f"/events/{quote(slug, safe='')}/orders/")
        return tuple(order for row in rows if (order := order_of(row)) is not None)
