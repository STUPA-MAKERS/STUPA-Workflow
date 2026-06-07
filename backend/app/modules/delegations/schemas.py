"""Delegation-DTOs (T-45). camelCase im JSON (FE-Kontrakt), per Name befüllbar."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


class DelegationCreate(_CamelModel):
    """Neue Delegation: Empfänger (``principalId``) erhält die Rolle des Delegierenden.

    ``validUntil`` ist **Pflicht** — eine Delegation ist immer zeitlich begrenzt
    (R1.5). ``validFrom`` (optional) erlaubt eine vorausdatierte Vertretung; fehlt es,
    gilt die Delegation ab sofort.
    """

    principal_id: UUID = Field(alias="principalId")
    role_id: UUID = Field(alias="roleId")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    valid_from: datetime | None = Field(default=None, alias="validFrom")
    valid_until: datetime = Field(alias="validUntil")
    delegate_voting: bool = Field(default=False, alias="delegateVoting")


class DelegationOut(_CamelModel):
    """Delegations-Sicht inkl. ``active`` (im Gültigkeitsfenster zum Abfragezeitpunkt)."""

    id: UUID
    principal_id: UUID = Field(serialization_alias="principalId")
    role_id: UUID = Field(serialization_alias="roleId")
    gremium_id: UUID | None = Field(serialization_alias="gremiumId")
    delegated_by: str | None = Field(serialization_alias="delegatedBy")
    granted_by: str | None = Field(serialization_alias="grantedBy")
    valid_from: datetime | None = Field(serialization_alias="validFrom")
    valid_until: datetime | None = Field(serialization_alias="validUntil")
    delegate_voting: bool = Field(serialization_alias="delegateVoting")
    active: bool
