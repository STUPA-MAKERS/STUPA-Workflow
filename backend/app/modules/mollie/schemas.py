"""API models of the Mollie integration."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from app.shared.schemas import FrozenCamelModel, FrozenStrictCamelModel


class ConnectionIn(FrozenStrictCamelModel, frozen=True):
    """The connection and its fields as the admin page saves them.

    ``token`` is write-only. Without it the stored token stays. ``clearToken`` removes it.
    """

    token: str | None = Field(default=None, min_length=1, max_length=500)
    clear_token: bool = Field(default=False, alias="clearToken")
    fee_budget_id: UUID | None = Field(default=None, alias="feeBudgetId")
    unassigned_budget_id: UUID | None = Field(default=None, alias="unassignedBudgetId")

    @model_validator(mode="after")
    def _one_token_change(self) -> Self:
        if self.token is not None and self.clear_token:
            raise ValueError("give a token or clear it, not both")
        return self


class ConnectionOut(FrozenCamelModel, frozen=True):
    """The connection without its token (§NF/security/network/003101)."""

    token_set: bool = Field(serialization_alias="tokenSet")
    organization: str | None = None
    fee_budget_id: UUID | None = Field(default=None, serialization_alias="feeBudgetId")
    unassigned_budget_id: UUID | None = Field(
        default=None, serialization_alias="unassignedBudgetId"
    )
    read_ok_at: datetime | None = Field(default=None, serialization_alias="readOkAt")
    read_error: str | None = Field(default=None, serialization_alias="readError")


class ConnectionTestOut(FrozenCamelModel, frozen=True):
    """The result of a connection test with the name of the organization."""

    ok: bool
    error: str | None = None
    name: str | None = None
