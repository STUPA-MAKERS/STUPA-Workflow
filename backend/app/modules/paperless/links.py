"""Paperless documents as the ends of links (§F/integrations/paperless/002763-002767).

A link names a Paperless document by the id of its row in ``paperless_document``. The
id comes from the number of the document (``document_ref``), so the link search names a
document before a row exists, and the platform stores each document once.

The row gets the title, the type and the date at each new link (``DocumentLinks.store``).
A read of a link uses these stored values and never calls Paperless.

The part is on while the feature `paperless` is on, the connection has its address and
its token, and the switch `Paperless-Dokumente verknüpfen` is on (``links_part_on``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.paperless.client import (
    DocumentHit,
    PaperlessError,
    document_url,
    link_address,
)
from app.modules.paperless.connection import ConnectionService, links_on
from app.modules.paperless.models import PaperlessDocument, PaperlessSettings
from app.settings import get_settings

#: The link kind of a Paperless document.
LINK_KIND = "paperless"
#: The permission that reads and links a Paperless document (002764).
PAPERLESS_USE = "paperless.use"
#: The high half of the id of a document row: the bytes of `paperles`.
_PREFIX = int.from_bytes(b"paperles") << 64
_NUMBER_BITS = (1 << 64) - 1


def document_ref(document_id: int) -> uuid.UUID:
    """The id of the row of the Paperless document with this number."""
    return uuid.UUID(int=_PREFIX | document_id)


def document_number(ref: uuid.UUID) -> int | None:
    """The number of the Paperless document of a row id, or None for another id."""
    number = ref.int & _NUMBER_BITS
    return number if ref.int == _PREFIX | number and number > 0 else None


def _connection(session: AsyncSession) -> ConnectionService:
    return ConnectionService(session, get_settings())


#: Builds the connection service of a session. A test puts a fake Paperless here.
connection_of: Callable[[AsyncSession], ConnectionService] = _connection


async def _settings(session: AsyncSession) -> PaperlessSettings | None:
    return await session.scalar(select(PaperlessSettings).where(PaperlessSettings.id == 1))


async def links_part_on(session: AsyncSession) -> bool:
    """Tell whether the switch of the links is on and the connection is complete."""
    row = await _settings(session)
    return row is not None and links_on(row)


@dataclass(frozen=True, slots=True)
class StoredDocument:
    """A linked document with its stored values and its address in Paperless."""

    id: uuid.UUID
    title: str
    document_type: str | None
    created: str | None
    url: str | None


def _target_of(hit: DocumentHit) -> StoredDocument:
    return StoredDocument(
        id=document_ref(hit.document_id),
        title=hit.title,
        document_type=hit.document_type,
        created=hit.created.isoformat() if hit.created is not None else None,
        url=None,
    )


@dataclass(frozen=True, slots=True)
class DocumentLinks:
    """Read, store and search the Paperless documents of links on one session."""

    session: AsyncSession

    async def stored(self, ids: Collection[uuid.UUID]) -> dict[uuid.UUID, StoredDocument]:
        """The stored documents with these row ids, without a call to Paperless."""
        if not ids:
            return {}
        settings = await _settings(self.session)
        base = (
            link_address(settings.base_url, settings.public_url) if settings is not None else None
        )
        rows = (
            await self.session.scalars(
                select(PaperlessDocument).where(PaperlessDocument.id.in_(list(ids)))
            )
        ).all()
        return {
            row.id: StoredDocument(
                id=row.id,
                title=row.title,
                document_type=row.document_type,
                created=row.created.isoformat() if row.created is not None else None,
                url=document_url(base, row.document_id) if base else None,
            )
            for row in rows
        }

    async def store(self, ref: uuid.UUID) -> bool:
        """Read the document of a row id from Paperless and store its values (002765).

        A row that exists gets the new values. The answer is False for an id that names
        no document of Paperless.

        Raises:
            PaperlessError: Paperless does not answer or the part has no connection.
        """
        number = document_number(ref)
        if number is None:
            return False
        client = await connection_of(self.session).client()
        if client is None:
            raise PaperlessError("unreachable")
        hit = await client.document(number)
        if hit is None:
            return False
        values = {
            "title": hit.title,
            "document_type": hit.document_type,
            "created": hit.created,
            "stored_at": datetime.now(UTC),
        }
        await self.session.execute(
            pg_insert(PaperlessDocument)
            .values(id=ref, document_id=number, **values)
            .on_conflict_do_update(index_elements=[PaperlessDocument.id], set_=values)
        )
        return True

    async def search(self, query: str, limit: int) -> list[StoredDocument]:
        """Search Paperless as the Paperless search does (002766), ``limit`` hits at most.

        An empty query answers the newest documents.

        Raises:
            PaperlessError: Paperless does not answer or the part has no connection.
        """
        client = await connection_of(self.session).client()
        if client is None:
            raise PaperlessError("unreachable")
        return [_target_of(hit) for hit in (await client.search(query))[:limit]]
