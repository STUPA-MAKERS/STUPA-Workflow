"""API models of the Paperless integration."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.shared.schemas import FrozenCamelModel, FrozenStrictCamelModel

FilingKind = Literal[
    "protocol", "protocol_public", "application", "attachment", "plan", "ticket_file"
]

#: The kinds of element whose page links to its document.
ElementKind = Literal["protocol", "application", "plan"]


class ConnectionIn(FrozenStrictCamelModel, frozen=True):
    """The connection and the switches as the admin page saves them.

    ``token`` is write-only. Without it the stored token stays. ``clearToken`` removes
    the stored token. ``publicUrl`` is the address for links; empty means the links use
    ``baseUrl`` (§F/integrations/paperless/002844).
    """

    base_url: str | None = Field(default=None, alias="baseUrl", max_length=2000)
    public_url: str | None = Field(default=None, alias="publicUrl", max_length=2000)
    token: str | None = Field(default=None, min_length=1, max_length=500)
    clear_token: bool = Field(default=False, alias="clearToken")
    file_protocols: bool = Field(default=False, alias="fileProtocols")
    file_applications: bool = Field(default=False, alias="fileApplications")
    file_plans: bool = Field(default=False, alias="filePlans")
    insert_enabled: bool = Field(default=False, alias="insertEnabled")
    link_enabled: bool = Field(default=False, alias="linkEnabled")

    @model_validator(mode="after")
    def _one_token_change(self) -> Self:
        if self.token is not None and self.clear_token:
            raise ValueError("give a token or clear it, not both")
        return self


class ConnectionOut(FrozenCamelModel, frozen=True):
    """The connection without its token (§NF/security/network/002515).

    ``tokenSet`` tells only whether a token is stored. ``allowedHosts`` are the hosts
    of the deploy setting, so the page can say which address the server accepts.
    """

    base_url: str | None = Field(default=None, serialization_alias="baseUrl")
    public_url: str | None = Field(default=None, serialization_alias="publicUrl")
    token_set: bool = Field(serialization_alias="tokenSet")
    file_protocols: bool = Field(serialization_alias="fileProtocols")
    file_applications: bool = Field(serialization_alias="fileApplications")
    file_plans: bool = Field(serialization_alias="filePlans")
    insert_enabled: bool = Field(serialization_alias="insertEnabled")
    link_enabled: bool = Field(serialization_alias="linkEnabled")
    allowed_hosts: tuple[str, ...] = Field(serialization_alias="allowedHosts")


class ConnectionTestOut(FrozenCamelModel, frozen=True):
    """The result of the connection test. ``error`` is the cause code of a failure."""

    ok: bool
    error: str | None = None


class FailedFilingOut(FrozenCamelModel, frozen=True):
    """A filing whose job failed for the last time."""

    id: UUID
    kind: FilingKind
    element_id: UUID = Field(serialization_alias="elementId")
    title: str
    failed_at: datetime | None = Field(default=None, serialization_alias="failedAt")
    error: str | None = None


class BackfillOut(FrozenCamelModel, frozen=True):
    """The jobs that the action `Bestehende Dokumente ablegen` started."""

    started: int


class ElementDocumentOut(FrozenCamelModel, frozen=True):
    """The document of an element in Paperless, for the entry `In Paperless öffnen`.

    ``url`` is None while the element has no filed document.
    """

    url: str | None = None
    document_id: int | None = Field(default=None, serialization_alias="documentId")


class FiledDocumentOut(FrozenCamelModel, frozen=True):
    """A filed document as an erasure lists it (§F/administration/privacy/002532)."""

    document_id: int = Field(serialization_alias="documentId")
    title: str
    url: str | None = None
    filed_at: datetime | None = Field(default=None, serialization_alias="filedAt")


class InsertStateOut(FrozenCamelModel, frozen=True):
    """Whether the parts that a person with `paperless.use` uses are on (002512).

    ``enabled`` is the part `Aus Paperless einfügen`, ``linkEnabled`` the part
    `Paperless-Dokumente verknüpfen` (§F/integrations/paperless/002767).
    """

    enabled: bool
    link_enabled: bool = Field(default=False, serialization_alias="linkEnabled")


class DocumentHitOut(FrozenCamelModel, frozen=True):
    """One hit of the Paperless search (§F/integrations/paperless/002534)."""

    document_id: int = Field(serialization_alias="documentId")
    title: str
    document_type: str | None = Field(default=None, serialization_alias="documentType")
    created: date | None = None


class InsertIn(FrozenStrictCamelModel, frozen=True):
    """The pick of the Paperless search: the number of the document to copy."""

    document_id: int = Field(alias="documentId", gt=0)
