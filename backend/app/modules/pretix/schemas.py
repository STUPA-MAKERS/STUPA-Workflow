"""API models of the pretix integration."""

from __future__ import annotations

from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from app.shared.schemas import FrozenCamelModel, FrozenStrictCamelModel


class ConnectionIn(FrozenStrictCamelModel, frozen=True):
    """The connection and the switches as the admin page saves them.

    ``token`` is write-only. Without it the stored token stays. ``clearToken`` removes it.
    """

    base_url: str | None = Field(default=None, alias="baseUrl", max_length=2000)
    organizer: str | None = Field(default=None, max_length=200)
    token: str | None = Field(default=None, min_length=1, max_length=500)
    clear_token: bool = Field(default=False, alias="clearToken")
    show_sales: bool = Field(default=False, alias="showSales")
    book_income: bool = Field(default=False, alias="bookIncome")

    @model_validator(mode="after")
    def _one_token_change(self) -> Self:
        if self.token is not None and self.clear_token:
            raise ValueError("give a token or clear it, not both")
        return self


class ConnectionOut(FrozenCamelModel, frozen=True):
    """The connection without its token (§NF/security/network/003101).

    ``tokenSet`` tells only whether a token is stored. ``allowedHosts`` are the hosts of
    the deploy setting, so the page can say which address the server accepts.
    """

    base_url: str | None = Field(default=None, serialization_alias="baseUrl")
    organizer: str | None = None
    token_set: bool = Field(serialization_alias="tokenSet")
    show_sales: bool = Field(serialization_alias="showSales")
    book_income: bool = Field(serialization_alias="bookIncome")
    allowed_hosts: tuple[str, ...] = Field(serialization_alias="allowedHosts")


class ConnectionTestOut(FrozenCamelModel, frozen=True):
    """The result of a connection test. ``error`` is the cause code of a failure."""

    ok: bool
    error: str | None = None
    name: str | None = None


class PretixEventOut(FrozenCamelModel, frozen=True):
    """One event of the organizer for the picker `Pretix-Veranstaltung` (003083).

    ``taken`` tells that another Event links it.
    """

    slug: str
    name: str
    date_from: date | None = Field(default=None, serialization_alias="dateFrom")
    taken: bool = False


class LinkIn(FrozenStrictCamelModel, frozen=True):
    """The pretix event that an Event links."""

    slug: str = Field(min_length=1, max_length=200)


class IncomeBudgetIn(FrozenStrictCamelModel, frozen=True):
    """The field `Einnahmen-Kostenstelle` of an Event (003086); null clears it."""

    budget_id: UUID | None = Field(default=None, alias="budgetId")


class LinkOut(FrozenCamelModel, frozen=True):
    """The pretix event of an Event and its field `Einnahmen-Kostenstelle`."""

    slug: str
    name: str
    date_from: date | None = Field(default=None, serialization_alias="dateFrom")
    income_budget_id: UUID | None = Field(default=None, serialization_alias="incomeBudgetId")
    income_budget_name: str | None = Field(default=None, serialization_alias="incomeBudgetName")


class FailedBookingOut(FrozenCamelModel, frozen=True):
    """A booking that the platform could not make, with its cause (003086, 003097)."""

    source: str
    key: str
    error: str
    at: datetime
