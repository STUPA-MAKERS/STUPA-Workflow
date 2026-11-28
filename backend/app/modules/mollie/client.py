"""The read-only HTTP client of the Mollie API v2.

Each call carries the access token of the connection, uses the method GET only
(§F/integrations/mollie/003099), goes to `api.mollie.com` only and follows no redirect
(§NF/security/network/003100). A `next` address of a list that names another host is
refused.

The client reads only the money values (§F/integrations/mollie/003098): of a payment its
id, amount, status, dates, settlement and the pretix values of its metadata; of a refund
and a chargeback its id, payment, amount, status, date and settlement; of a settlement its
id, reference, status, date, amount and the costs; of a balance transaction the fee of its
payment. It never reads the name, the email address, the IBAN or the card of a payer.

A failure is a `MollieError` with a short cause code and never the text of an exception or
of an answer (§NF/security/network/003101).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx

#: The only host that the client calls.
MOLLIE_HOST = "api.mollie.com"
API_ROOT = f"https://{MOLLIE_HOST}/v2"

ErrorCode = Literal[
    "blocked", "timeout", "unreachable", "redirect", "unauthorized", "status", "format"
]

TIMEOUT_SECONDS = 20.0

#: The size of one page of a list, the largest that Mollie gives.
PAGE_SIZE = 250

#: The most pages of one read, so a broken `next` address never loops.
MAX_PAGES = 200


class MollieError(Exception):
    """A call to Mollie failed. ``code`` is the short cause."""

    def __init__(self, code: ErrorCode) -> None:
        """Keep the cause code."""
        super().__init__(code)
        self.code: ErrorCode = code


@dataclass(frozen=True, slots=True)
class Payment:
    """One payment without a value of the payer (§F/integrations/mollie/003098).

    Attributes:
        id: The id (`tr_…`).
        amount: The amount.
        status: The status of Mollie (`paid`, `open`, `failed`, …).
        created_at: The moment Mollie created it.
        paid_at: The moment of the payment, else None.
        settlement_id: The settlement that paid it out, else None.
        organizer: The pretix organizer of the metadata, else None.
        event: The pretix event of the metadata, else None.
    """

    id: str
    amount: Decimal
    status: str
    created_at: datetime | None
    paid_at: datetime | None
    settlement_id: str | None
    organizer: str | None
    event: str | None


@dataclass(frozen=True, slots=True)
class Move:
    """One refund or chargeback of a payment."""

    id: str
    kind: Literal["refund", "chargeback"]
    payment_id: str
    amount: Decimal
    status: str
    at: datetime | None
    settlement_id: str | None


@dataclass(frozen=True, slots=True)
class Settlement:
    """One settlement: what Mollie paid out to the bank and what its costs took."""

    id: str
    reference: str
    status: str
    settled_at: datetime | None
    amount: Decimal
    fees: Decimal


@dataclass(frozen=True, slots=True)
class Fee:
    """The fee that Mollie took for one payment, from a balance transaction."""

    payment_id: str
    fee: Decimal


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _amount(value: object) -> Decimal:
    """Read an amount object `{value, currency}`; anything else is zero."""
    raw = value.get("value") if isinstance(value, Mapping) else None
    try:
        return Decimal(raw) if isinstance(raw, str) else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


def _moment(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def payment_of(raw: Mapping[str, object]) -> Payment | None:
    """Read one payment; only its money values and the pretix metadata."""
    payment_id = _text(raw.get("id"))
    if payment_id is None:
        return None
    meta = raw.get("metadata")
    values = meta if isinstance(meta, Mapping) else {}
    return Payment(
        id=payment_id,
        amount=_amount(raw.get("amount")),
        status=_text(raw.get("status")) or "",
        created_at=_moment(raw.get("createdAt")),
        paid_at=_moment(raw.get("paidAt")),
        settlement_id=_text(raw.get("settlementId")),
        organizer=_text(values.get("organizer")),
        event=_text(values.get("event")),
    )


def move_of(raw: Mapping[str, object], kind: Literal["refund", "chargeback"]) -> Move | None:
    """Read one refund or chargeback."""
    move_id = _text(raw.get("id"))
    payment_id = _text(raw.get("paymentId"))
    if move_id is None or payment_id is None:
        return None
    return Move(
        id=move_id,
        kind=kind,
        payment_id=payment_id,
        amount=abs(_amount(raw.get("amount"))),
        status=_text(raw.get("status")) or ("charged_back" if kind == "chargeback" else ""),
        at=_moment(raw.get("createdAt")),
        settlement_id=_text(raw.get("settlementId")),
    )


def _rows(value: object) -> tuple[Mapping[str, object], ...]:
    """Return the objects of a list, or nothing for another value."""
    return (
        tuple(row for row in value if isinstance(row, Mapping)) if isinstance(value, list) else ()
    )


def _costs(periods: object) -> Decimal:
    """Sum the gross costs of every period of a settlement."""
    months = (
        month
        for year in (periods.values() if isinstance(periods, Mapping) else ())
        if isinstance(year, Mapping)
        for month in year.values()
        if isinstance(month, Mapping)
    )
    return sum(
        (
            abs(_amount(cost.get("amountGross")))
            for month in months
            for cost in _rows(month.get("costs"))
        ),
        Decimal(0),
    )


def settlement_of(raw: Mapping[str, object]) -> Settlement | None:
    """Read one settlement with the sum of its costs."""
    settlement_id = _text(raw.get("id"))
    if settlement_id is None:
        return None
    return Settlement(
        id=settlement_id,
        reference=_text(raw.get("reference")) or settlement_id,
        status=_text(raw.get("status")) or "",
        settled_at=_moment(raw.get("settledAt")),
        amount=_amount(raw.get("amount")),
        fees=_costs(raw.get("periods")),
    )


def fee_of(raw: Mapping[str, object]) -> Fee | None:
    """Read the fee of a payment from a balance transaction, else None."""
    if raw.get("type") != "payment":
        return None
    context = raw.get("context")
    values = context if isinstance(context, Mapping) else {}
    nested = values.get("payment")
    payment_id = _text(values.get("paymentId")) or (
        _text(nested.get("paymentId")) if isinstance(nested, Mapping) else None
    )
    if payment_id is None:
        return None
    return Fee(payment_id=payment_id, fee=abs(_amount(raw.get("deductions"))))


def _client(timeout_seconds: float) -> httpx.AsyncClient:  # pragma: no cover - real HTTP
    return httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(timeout_seconds))


def _host_ok(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == MOLLIE_HOST and parts.port is None


#: Tells whether a read can stop after a page: each row of it is known and final.
Known = Callable[[tuple[Mapping[str, object], ...]], bool]


def _never(_rows: tuple[Mapping[str, object], ...]) -> bool:
    return False


@dataclass(frozen=True, slots=True)
class MollieClient:
    """Read from one Mollie organization with the token of the connection.

    A test injects the HTTP client factory.
    """

    token: str
    timeout_seconds: float = TIMEOUT_SECONDS
    client_factory: Callable[[float], httpx.AsyncClient] = _client

    async def _get(self, url: str, params: Mapping[str, str] | None = None) -> object:
        """Send one GET and return the JSON of the answer.

        Raises:
            MollieError: The host is not `api.mollie.com`, Mollie does not answer in
                time, or it answers with a redirect, an error or no JSON.
        """
        if not _host_ok(url):
            raise MollieError("blocked")
        try:
            async with self.client_factory(self.timeout_seconds) as client:
                response = await client.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise MollieError("timeout") from exc
        except httpx.HTTPError as exc:
            raise MollieError("unreachable") from exc
        if 300 <= response.status_code < 400:
            raise MollieError("redirect")
        if response.status_code in (401, 403):
            raise MollieError("unauthorized")
        if not 200 <= response.status_code < 300:
            raise MollieError("status")
        try:
            return response.json()
        except ValueError as exc:
            raise MollieError("format") from exc

    async def _pages(
        self,
        url: str,
        params: Mapping[str, str] | None,
        embedded: str,
        known: Known,
        left: int,
    ) -> tuple[Mapping[str, object], ...]:
        """Read one page of a list, and the next page while `known` is false for it."""
        body = await self._get(url, params)
        holder = body.get("_embedded") if isinstance(body, dict) else None
        rows_raw = holder.get(embedded) if isinstance(holder, dict) else None
        if not isinstance(rows_raw, list):
            raise MollieError("format")
        rows = tuple(row for row in rows_raw if isinstance(row, dict))
        links = body.get("_links") if isinstance(body, dict) else None
        following = links.get("next") if isinstance(links, dict) else None
        href = following.get("href") if isinstance(following, dict) else None
        rest = (
            await self._pages(href, None, embedded, known, left - 1)
            if isinstance(href, str) and href and left > 1 and rows and not known(rows)
            else ()
        )
        return rows + rest

    async def _list(
        self, path: str, embedded: str, known: Known = _never
    ) -> tuple[Mapping[str, object], ...]:
        return await self._pages(
            f"{API_ROOT}{path}", {"limit": str(PAGE_SIZE)}, embedded, known, MAX_PAGES
        )

    async def organization(self) -> str:
        """Return the name of the organization of the token.

        Raises:
            MollieError: The connection does not work.
        """
        body = await self._get(f"{API_ROOT}/organizations/me")
        name = body.get("name") if isinstance(body, dict) else None
        if not isinstance(name, str):
            raise MollieError("format")
        return name

    async def payments(self, known: Known = _never) -> tuple[Payment, ...]:
        """Return the payments, the newest first, until a page that is all known."""
        rows = await self._list("/payments", "payments", known)
        return tuple(payment for row in rows if (payment := payment_of(row)) is not None)

    async def refunds(self, known: Known = _never) -> tuple[Move, ...]:
        """Return the refunds, the newest first, until a page that is all known."""
        rows = await self._list("/refunds", "refunds", known)
        return tuple(refund for row in rows if (refund := move_of(row, "refund")) is not None)

    async def chargebacks(self, known: Known = _never) -> tuple[Move, ...]:
        """Return the chargebacks, the newest first, until a page that is all known."""
        rows = await self._list("/chargebacks", "chargebacks", known)
        return tuple(
            chargeback for row in rows if (chargeback := move_of(row, "chargeback")) is not None
        )

    async def settlements(self, known: Known = _never) -> tuple[Settlement, ...]:
        """Return the settlements, the newest first, until a page that is all known."""
        rows = await self._list("/settlements", "settlements", known)
        return tuple(settlement for row in rows if (settlement := settlement_of(row)) is not None)

    async def fees(self, known: Known = _never) -> tuple[Fee, ...]:
        """Return the fee of each payment from the transactions of every balance."""
        balances = await self._list("/balances", "balances")
        ids = tuple(balance for row in balances if (balance := _text(row.get("id"))) is not None)
        pages = [
            await self._list(
                f"/balances/{quote(balance_id, safe='')}/transactions",
                "balance_transactions",
                known,
            )
            for balance_id in ids
        ]
        return tuple(fee for rows in pages for row in rows if (fee := fee_of(row)) is not None)
