"""Wire models of the Postfach of a Bereich (camelCase). No model returns a password."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.shared.schemas import FrozenCamelModel, FrozenStrictCamelModel

#: The folder for done mails of a new Postfach.
DEFAULT_DONE_FOLDER = "Erledigt"

_ADDRESS = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
_HOST = r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$"


class MailboxCreate(FrozenStrictCamelModel, frozen=True):
    """A new Postfach. It starts with the switch off unless ``enabled`` says else."""

    address: str = Field(max_length=254, pattern=_ADDRESS)
    imap_host: str = Field(alias="imapHost", max_length=253, pattern=_HOST)
    imap_port: int = Field(alias="imapPort", ge=1, le=65535)
    imap_user: str = Field(alias="imapUser", min_length=1, max_length=254)
    imap_password: str = Field(alias="imapPassword", min_length=1, max_length=1024)
    smtp_host: str = Field(alias="smtpHost", max_length=253, pattern=_HOST)
    smtp_port: int = Field(alias="smtpPort", ge=1, le=65535)
    smtp_user: str = Field(alias="smtpUser", min_length=1, max_length=254)
    smtp_password: str = Field(alias="smtpPassword", min_length=1, max_length=1024)
    done_folder: str = Field(
        default=DEFAULT_DONE_FOLDER, alias="doneFolder", min_length=1, max_length=120
    )
    enabled: bool = False


class MailboxPatch(FrozenStrictCamelModel, frozen=True):
    """A change of a Postfach. A field that the body leaves out stays, also a password."""

    address: str | None = Field(default=None, max_length=254, pattern=_ADDRESS)
    imap_host: str | None = Field(default=None, alias="imapHost", max_length=253, pattern=_HOST)
    imap_port: int | None = Field(default=None, alias="imapPort", ge=1, le=65535)
    imap_user: str | None = Field(default=None, alias="imapUser", min_length=1, max_length=254)
    imap_password: str | None = Field(
        default=None, alias="imapPassword", min_length=1, max_length=1024
    )
    smtp_host: str | None = Field(default=None, alias="smtpHost", max_length=253, pattern=_HOST)
    smtp_port: int | None = Field(default=None, alias="smtpPort", ge=1, le=65535)
    smtp_user: str | None = Field(default=None, alias="smtpUser", min_length=1, max_length=254)
    smtp_password: str | None = Field(
        default=None, alias="smtpPassword", min_length=1, max_length=1024
    )
    done_folder: str | None = Field(default=None, alias="doneFolder", min_length=1, max_length=120)
    enabled: bool | None = None


class MailboxOut(FrozenCamelModel, frozen=True):
    """A Postfach without its passwords.

    ``error`` is the cause code of the fetch after eight failed runs in sequence, else
    null (§F/integrations/ticket-mail/002723).
    """

    area_id: UUID = Field(serialization_alias="areaId")
    address: str
    imap_host: str = Field(serialization_alias="imapHost")
    imap_port: int = Field(serialization_alias="imapPort")
    imap_user: str = Field(serialization_alias="imapUser")
    smtp_host: str = Field(serialization_alias="smtpHost")
    smtp_port: int = Field(serialization_alias="smtpPort")
    smtp_user: str = Field(serialization_alias="smtpUser")
    done_folder: str = Field(serialization_alias="doneFolder")
    enabled: bool
    error: str | None = None
    fetched_at: datetime | None = Field(default=None, serialization_alias="fetchedAt")


class MailboxList(FrozenCamelModel, frozen=True):
    """Each Postfach and the hosts of ``TICKET_MAIL_HOST_ALLOWLIST``."""

    items: tuple[MailboxOut, ...]
    allowed_hosts: tuple[str, ...] = Field(serialization_alias="allowedHosts")


class MailboxCheck(FrozenCamelModel, frozen=True):
    """The result of one connection. ``error`` is the cause code of a failure."""

    ok: bool
    error: str | None = None


class MailboxTestOut(FrozenCamelModel, frozen=True):
    """The result of the test of both connections of a Postfach."""

    imap: MailboxCheck
    smtp: MailboxCheck
