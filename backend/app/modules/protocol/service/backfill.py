"""The backfill of missing public PDFs, with a failure count per protocol."""

from __future__ import annotations

from collections import Counter
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select

from app.modules.gremien.models import Gremium
from app.modules.meetings.protocol_models import Protocol
from app.modules.protocol.public import PublicSnapshot, apply_public_snapshot
from app.modules.protocol.service.common import (
    PUBLIC_RENDER_MAX_FAILURES,
    BackfillOutcome,
    BackfillResult,
    _upload,
    logger,
    protocol_public_storage_key,
)
from app.modules.protocol.service.render import RenderOps
from app.shared.errors import ServiceUnavailableError


class BackfillOps(RenderOps):
    """Backfill of the public PDF."""

    def _missing_public_clause(self) -> ColumnElement[bool]:
        """Return the rule "final, and the public version is missing"."""
        missing = Protocol.public_content.is_(None)
        renders = self.storage is not None and self.typst is not None
        return and_(
            Protocol.status == "final",
            or_(missing, Protocol.public_pdf_storage_key.is_(None)) if renders else missing,
        )

    async def backfill_public(
        self, gremium_id: UUID, *, retry_failed: bool = True
    ) -> BackfillResult:
        """Build the missing public versions of the final protocols of a gremium.

        The job runs after a gremium switched `protocols_public` on. A final
        protocol without a public snapshot, or without a public PDF while storage is
        on, gets both, with the same renderer and variant as the finalization. Each
        protocol commits on its own. A failure of one protocol does not stop the
        others: the protocol stays hidden (fail closed) and the result counts it.

        A permanent failure (for example a render error in the text) counts up
        `public_render_failures`. With `retry_failed=False` (the hourly heal job),
        a protocol at `PUBLIC_RENDER_MAX_FAILURES` is skipped, so the same error does
        not run every hour. A switch of the gremium flag retries it.

        Any exception of one protocol is caught and logged, because one bad protocol
        must not stop the job.
        """
        base = select(Protocol.id).where(
            Protocol.gremium_id == gremium_id, self._missing_public_clause()
        )
        stmt = (
            base
            if retry_failed
            else base.where(Protocol.public_render_failures < PUBLIC_RENDER_MAX_FAILURES)
        )
        ids = (await self.session.scalars(stmt.order_by(Protocol.created_at))).all()
        outcomes = Counter([await self._backfill_outcome(protocol_id) for protocol_id in ids])
        return BackfillResult(
            done=outcomes["done"], transient=outcomes["transient"], failed=outcomes["failed"]
        )

    async def _backfill_outcome(self, protocol_id: UUID) -> BackfillOutcome:
        """Run the backfill of one protocol and classify its outcome.

        A failure rolls the session back, so the next protocol starts clean. Any
        exception is caught and logged, because one bad protocol must not stop the job.
        """
        try:
            await self._backfill_one(protocol_id)
        except ServiceUnavailableError:
            await self.session.rollback()
            return "transient"
        except Exception:
            logger.exception("public backfill failed (protocol=%s)", protocol_id)
            await self.session.rollback()
            await self._count_render_failure(protocol_id)
            return "failed"
        return "done"

    async def gremien_missing_public(self) -> list[UUID]:
        """List the public gremien with a final protocol that lacks its public version.

        A protocol counts when it is not held back and has no snapshot, or no public PDF
        while storage is on.

        The hourly heal job runs the backfill for them, so a protocol whose build
        failed or raced appears without a new switch of the gremium flag.
        """
        rows = await self.session.scalars(
            select(Protocol.gremium_id)
            .join(Gremium, Gremium.id == Protocol.gremium_id)
            .where(
                Gremium.protocols_public.is_(True),
                Protocol.public_withheld.is_(False),
                Protocol.public_render_failures < PUBLIC_RENDER_MAX_FAILURES,
                self._missing_public_clause(),
            )
            .distinct()
        )
        return list(rows.all())

    async def _count_render_failure(self, protocol_id: UUID) -> None:
        """Count a permanent failure of the public build, in its own commit.

        At `PUBLIC_RENDER_MAX_FAILURES` the method logs a warning once; the hourly
        heal job then skips the protocol.
        """
        protocol = await self.session.get(Protocol, protocol_id)
        if protocol is None:
            return
        protocol.public_render_failures = int(protocol.public_render_failures or 0) + 1
        if protocol.public_render_failures == PUBLIC_RENDER_MAX_FAILURES:
            logger.warning(
                "public version of protocol %s failed %s times; the heal job skips it "
                "until the gremium flag is switched again",
                protocol_id,
                PUBLIC_RENDER_MAX_FAILURES,
            )
        await self.session.commit()

    async def _backfill_one(self, protocol_id: UUID) -> None:
        """Build the public snapshot and the public PDF of one locked final protocol.

        A protocol that a parallel job built while this one waited for the lock is left
        as it is. A public PDF that exists without a size (an older protocol with a
        non-public TOP) is read from storage to get its size.
        """
        protocol = await self._get(protocol_id, for_update=True)
        pdf_done = protocol.public_pdf_storage_key is not None or self.storage is None
        if protocol.public_content is not None and pdf_done:
            await self.session.commit()
            return
        snapshot = PublicSnapshot()
        markdown = await self._build_document(protocol, public=True, snapshot=snapshot)
        key = protocol.public_pdf_storage_key
        pdf = (
            await self._render_pdf(protocol, markdown, public=True)
            if key is None
            else (await self._stored_pdf(key) if protocol.public_pdf_size is None else None)
        )
        uploads = _upload(protocol_public_storage_key(protocol.id), pdf) if key is None else ()
        apply_public_snapshot(protocol, snapshot, pdf)
        protocol.public_render_failures = 0
        await self.session.flush()
        await self.session.commit()
        await self._store(uploads)
