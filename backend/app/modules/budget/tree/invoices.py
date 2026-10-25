"""Invoice CRUD, ZUGFeRD/Factur-X import and invoice file storage."""

from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import ColumnElement, case, exists, func, not_, select

from app.modules.audit.actions import AuditAction
from app.modules.budget.invoice_import import parse_zugferd_pdf
from app.modules.budget.tree.service_base import BudgetTreeServiceBase
from app.modules.budget.tree_models import Budget, BudgetExpense, Invoice
from app.modules.budget.tree_schemas import (
    InvoiceBookingOut,
    InvoiceCreate,
    InvoiceFileResult,
    InvoiceOut,
    InvoicePage,
    InvoiceParseResult,
    InvoiceSegmentCounts,
    InvoiceUpdate,
)
from app.modules.files.mime import MimeRejected, validate_upload
from app.modules.files.scanner import scan_or_raise
from app.modules.files.storage import StorageError
from app.search import dialect_of, trigram_rank
from app.shared.errors import (
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
    ValidationProblem,
)
from app.shared.filenames import sanitize_display_name, sanitize_storage_name

logger = logging.getLogger("app.budget")

_INVOICE_FILE_PREFIX = "invoices/"


def _validate_invoice_file_token(token: str) -> str:
    """Return the token when it is a server-generated invoice key.

    An invoice file token is always a key under ``invoices/``. Anything else is
    rejected, so a client cannot point ``fileObjectKey`` at a foreign object in the
    bucket.

    Raises:
        ValidationProblem: The token has another prefix or contains ``..``.
    """
    if not token.startswith(_INVOICE_FILE_PREFIX) or ".." in token:
        raise ValidationProblem("invalid invoice file token")
    return token


class InvoiceOps(BudgetTreeServiceBase):
    """Invoice CRUD plus ZUGFeRD parse/import and file streaming.

    The read paths take ``visible_gremium_ids``. ``None`` means the full budget view
    and shows every linked booking. A set limits ``linkedBookings`` to the cost
    centres that `visible_budget_ids` opens for those Gremien.
    """

    @staticmethod
    def _invoice_out(
        inv: Invoice, linked: list[InvoiceBookingOut] | None = None
    ) -> InvoiceOut:
        return InvoiceOut(
            id=inv.id,
            number=inv.number,
            issueDate=inv.issue_date,
            dueDate=inv.due_date,
            supplier=inv.supplier,
            netAmount=inv.net_amount,
            taxAmount=inv.tax_amount,
            grossAmount=inv.gross_amount,
            currency=inv.currency,
            note=inv.note,
            status=inv.status,  # type: ignore[arg-type]
            fileName=inv.file_name,
            hasFile=inv.file_object_key is not None,
            actor=inv.actor,
            createdAt=inv.created_at,
            linkedBookings=linked or [],
        )

    async def _visible_ids(self, visible_gremium_ids: set[UUID] | None) -> set[UUID] | None:
        """Return the cost centres a gremium-scoped reader sees, or None for the full view."""
        if visible_gremium_ids is None:
            return None
        return await self.visible_budget_ids(visible_gremium_ids)

    async def _linked_bookings(
        self, invoice_ids: list[UUID], visible: set[UUID] | None
    ) -> dict[UUID, list[InvoiceBookingOut]]:
        """Load the bookings that reference the invoices, in one query.

        Sub-bookings count as well, because a sub-booking can carry its own receipt.
        The bookings come in booking order. ``visible`` holds the cost centres of a
        gremium-scoped reader (see `_visible_ids`); None is the full view.

        The query excludes a booking without an invoice, so ``invoice_id`` is never None
        here.

        Returns:
            The bookings per invoice id. An invoice without a visible booking is
            absent from the map.
        """
        if not invoice_ids:
            return {}
        stmt = (
            select(BudgetExpense, Budget.path_key, Budget.name)
            .join(Budget, Budget.id == BudgetExpense.budget_id)
            .where(BudgetExpense.invoice_id.in_(invoice_ids))
        )
        if visible is not None:
            if not visible:
                return {}
            stmt = stmt.where(BudgetExpense.budget_id.in_(visible))
        rows = (
            await self.session.execute(
                stmt.order_by(BudgetExpense.created_at, BudgetExpense.id)
            )
        ).all()
        linked: dict[UUID, list[InvoiceBookingOut]] = {}
        for booking, path_key, budget_name in rows:
            linked.setdefault(cast("UUID", booking.invoice_id), []).append(
                InvoiceBookingOut(
                    id=booking.id,
                    budgetId=booking.budget_id,
                    pathKey=path_key,
                    budgetName=budget_name,
                    fiscalYearId=booking.fiscal_year_id,
                    kind=booking.kind,  # type: ignore[arg-type]
                    amount=booking.amount,
                    description=booking.description,
                    paymentDate=booking.payment_date,
                    parentExpenseId=booking.parent_expense_id,
                    createdAt=booking.created_at,
                )
            )
        return linked

    async def _invoice_with_bookings(
        self, inv: Invoice, visible_gremium_ids: set[UUID] | None
    ) -> InvoiceOut:
        visible = await self._visible_ids(visible_gremium_ids)
        linked = await self._linked_bookings([inv.id], visible)
        return self._invoice_out(inv, linked.get(inv.id))

    @staticmethod
    def _booked_clause(visible: set[UUID] | None) -> ColumnElement[bool]:
        """Return the condition "the invoice has a booking that the reader can see".

        A booking on a cost centre outside the scope of a gremium-scoped reader does not
        count, so that the segment of an invoice matches the ``linkedBookings`` it shows.
        """
        conditions: list[ColumnElement[bool]] = [BudgetExpense.invoice_id == Invoice.id]
        if visible is not None:
            conditions.append(BudgetExpense.budget_id.in_(visible))
        return exists().where(*conditions)

    async def list_invoices_paged(
        self,
        *,
        invoice_id: UUID | None = None,
        q: str | None = None,
        status: str | None = None,
        booked: bool | None = None,
        gross_min: Decimal | None = None,
        gross_max: Decimal | None = None,
        issue_from: str | None = None,
        issue_to: str | None = None,
        due_from: str | None = None,
        due_to: str | None = None,
        visible_gremium_ids: set[UUID] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> InvoicePage:
        """List invoices with filters, fuzzy search and offset pagination.

        This mirrors `expenses.ExpenseOps.list_expenses_paged`. The search and
        filter predicates live in one shared `filters` list. That list goes into
        the count query and into the row query, so the total and the hits do not
        drift on infinite scroll. With `q` the trigram rank orders the hits by
        relevance before the usual "newest issue date first".

        ``visible_gremium_ids`` filters only ``linkedBookings``, not the invoices.
        An invoice is not bound to a cost centre.

        ``booked`` keeps the invoices with (``True``) or without (``False``) a booking
        that the reader can see. Together with ``status`` it gives the segments of the
        list: "Eingang" is ``open`` without a booking, "Verbucht" is ``open`` with one.
        ``counts`` holds the size of each segment under the other filters.

        ``invoice_id`` selects the exact invoice for a deep link, such as a
        global-search hit. It stands beside the other filters rather than replacing
        them, so the list still shows the one row it was asked for and the reset button
        still clears it. The fuzzy search ranks by trigrams over number, supplier and
        note (GIN indexes). On a non-Postgres dialect an ILIKE substring fallback runs.

        An invoice without a date falls out of every date range. ``func.date`` parses
        the ISO string of the frontend datepicker into a real date, because Postgres
        rejects "date >= varchar". On SQLite the call does nothing, because ISO stays
        ISO. The segment filters apply after the counts, so a count covers its own
        segment under every other filter.
        """
        filters = []
        if invoice_id is not None:
            filters.append(Invoice.id == invoice_id)
        rank_expr = None
        if q and q.strip():
            where, rank_expr = trigram_rank(
                q,
                [Invoice.number, Invoice.supplier, Invoice.note],
                dialect=dialect_of(self.session),
            )
            filters.append(where)
        if gross_min is not None:
            filters.append(Invoice.gross_amount >= gross_min)
        if gross_max is not None:
            filters.append(Invoice.gross_amount <= gross_max)
        if issue_from:
            filters.append(Invoice.issue_date >= func.date(issue_from))
        if issue_to:
            filters.append(Invoice.issue_date <= func.date(issue_to))
        if due_from:
            filters.append(Invoice.due_date >= func.date(due_from))
        if due_to:
            filters.append(Invoice.due_date <= func.date(due_to))

        visible = await self._visible_ids(visible_gremium_ids)
        booked_clause = self._booked_clause(visible)
        counts = await self._segment_counts(filters, booked_clause)
        if status is not None:
            filters.append(Invoice.status == status)
        if booked is not None:
            filters.append(booked_clause if booked else not_(booked_clause))

        total = await self.session.scalar(
            select(func.count()).select_from(Invoice).where(*filters)
        )
        ordering = Invoice.issue_date.desc().nulls_last()
        order_by = (rank_expr.desc(), ordering) if rank_expr is not None else (ordering,)
        rows = (
            await self.session.scalars(
                select(Invoice).where(*filters).order_by(*order_by).limit(limit).offset(offset)
            )
        ).all()
        linked = await self._linked_bookings([i.id for i in rows], visible)
        return InvoicePage(
            items=[self._invoice_out(i, linked.get(i.id)) for i in rows],
            total=total or 0,
            limit=limit,
            offset=offset,
            counts=counts,
        )

    async def _segment_counts(
        self, filters: list[ColumnElement[bool]], booked_clause: ColumnElement[bool]
    ) -> InvoiceSegmentCounts:
        """Count the invoices of each list segment in one query."""
        is_open = Invoice.status == "open"

        def count_if(condition: ColumnElement[bool]) -> ColumnElement[int]:
            return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)

        row = (
            await self.session.execute(
                select(
                    func.count(),
                    count_if(is_open & not_(booked_clause)),
                    count_if(is_open & booked_clause),
                    count_if(Invoice.status == "paid"),
                )
                .select_from(Invoice)
                .where(*filters)
            )
        ).one()
        return InvoiceSegmentCounts(
            all=int(row[0]), inbox=int(row[1]), booked=int(row[2]), paid=int(row[3])
        )

    async def get_invoice(
        self, invoice_id: UUID, *, visible_gremium_ids: set[UUID] | None = None
    ) -> InvoiceOut:
        """Return one invoice with the bookings that the reader can see.

        Raises:
            NotFoundError: No invoice has this id.
        """
        inv = await self.session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFoundError(f"invoice {invoice_id} not found")
        return await self._invoice_with_bookings(inv, visible_gremium_ids)

    async def create_invoice(self, payload: InvoiceCreate, *, actor: str) -> InvoiceOut:
        """Create an invoice and audit it.

        A ``fileToken`` from the ZUGFeRD import takes over the stored original. The
        token is the MinIO key of the object, and the prefix check keeps foreign objects
        out. The client sends the file name back, so the name gets the display-name rule
        again.
        """
        inv = Invoice(
            number=payload.number,
            issue_date=payload.issue_date,
            due_date=payload.due_date,
            supplier=payload.supplier,
            net_amount=payload.net_amount,
            tax_amount=payload.tax_amount,
            gross_amount=payload.gross_amount,
            note=payload.note,
            status=payload.status,
            actor=actor,
        )
        if payload.file_token is not None:
            inv.file_object_key = _validate_invoice_file_token(payload.file_token)
            inv.file_name = sanitize_display_name(payload.file_name, default="beleg.pdf")
            inv.file_mime = payload.file_mime
        self.session.add(inv)
        await self.session.flush()
        await self._audit(
            AuditAction.BUDGET_INVOICE_CREATE,
            target_type="invoice",
            target_id=str(inv.id),
            data={"number": inv.number, "gross": str(inv.gross_amount)},
        )
        await self.session.commit()
        return self._invoice_out(inv)

    async def _validate_scan_store(
        self, data: bytes, *, filename: str | None
    ) -> tuple[str, str, str]:
        """Validate a PDF by size, MIME type and virus scan, then store it.

        Both the ZUGFeRD parse and the manual invoice-file upload use this path.

        Returns:
            The storage token, the display name and the MIME type.
        """
        max_bytes = self.settings.attachment_max_bytes
        if len(data) > max_bytes:
            raise PayloadTooLargeError(f"Invoice exceeds {max_bytes} bytes.")
        if not data:
            raise UnsupportedMediaTypeError("Empty file.")
        display_name = sanitize_display_name(filename)
        try:
            mime = validate_upload(display_name, data)
        except MimeRejected as exc:
            raise UnsupportedMediaTypeError(str(exc)) from exc
        if mime != "application/pdf":
            raise UnsupportedMediaTypeError("Invoice import expects a PDF.")

        await scan_or_raise(data, self.settings)
        storage_key = await self._store_invoice_file(
            data, mime, sanitize_storage_name(display_name)
        )
        return storage_key, display_name, mime

    async def store_invoice_file(self, data: bytes, *, filename: str | None) -> InvoiceFileResult:
        """Validate and store an invoice PDF without a ZUGFeRD parse.

        This lets the user attach an original file to an invoice that carries no
        ZUGFeRD data.

        Returns:
            The same `fileToken` that `POST /invoices` expects.
        """
        storage_key, display_name, mime = await self._validate_scan_store(
            data, filename=filename
        )
        return InvoiceFileResult(fileToken=storage_key, fileName=display_name, fileMime=mime)

    async def parse_invoice_file(self, data: bytes, *, filename: str | None) -> InvoiceParseResult:
        """Validate the PDF, parse the ZUGFeRD data and store the original.

        The order is deliberate: scan first, then parse, then store. A PDF
        without ZUGFeRD data is the common case. It must leave no orphaned
        object behind.

        The parser runs in a thread, because it is synchronous and binds the CPU, and
        would otherwise block the event loop.
        """
        max_bytes = self.settings.attachment_max_bytes
        if len(data) > max_bytes:
            raise PayloadTooLargeError(f"Invoice exceeds {max_bytes} bytes.")
        if not data:
            raise UnsupportedMediaTypeError("Empty file.")
        display_name = sanitize_display_name(filename)
        try:
            mime = validate_upload(display_name, data)
        except MimeRejected as exc:
            raise UnsupportedMediaTypeError(str(exc)) from exc
        if mime != "application/pdf":
            raise UnsupportedMediaTypeError("Invoice import expects a PDF.")

        await scan_or_raise(data, self.settings)
        parsed = await asyncio.to_thread(parse_zugferd_pdf, data)

        storage_key = await self._store_invoice_file(
            data, mime, sanitize_storage_name(display_name)
        )
        return InvoiceParseResult(
            number=parsed.number,
            issueDate=parsed.issue_date,
            dueDate=parsed.due_date,
            supplier=parsed.supplier,
            netAmount=parsed.net_amount,
            taxAmount=parsed.tax_amount,
            grossAmount=parsed.gross_amount,
            currency=parsed.currency,
            fileToken=storage_key,
            fileName=display_name,
            fileMime=mime,
            duplicate=await self._invoice_number_exists(parsed.number),
        )

    async def _invoice_number_exists(self, number: str | None) -> bool:
        """Tell if an invoice with this number exists, for the duplicate warning."""
        if not number:
            return False
        existing = await self.session.scalars(
            select(Invoice.id).where(Invoice.number == number).limit(1)
        )
        return existing.first() is not None

    async def invoice_file_bytes(self, invoice_id: UUID) -> tuple[bytes, str, str]:
        """Load the original file on the server.

        The method returns no presigned URL on purpose. MinIO runs only on the
        internal Docker network. An S3v4-signed URL binds the internal host and
        the browser cannot reach it. The protocol PDF follows the same rule and
        streams through the API.

        Returns:
            The file bytes, the MIME type and the file name.
        """
        inv = await self.session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFoundError(f"invoice {invoice_id} not found")
        if inv.file_object_key is None:
            raise NotFoundError("invoice has no stored file")
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        try:
            data = await self.storage.get(inv.file_object_key)
        except StorageError as exc:
            raise ServiceUnavailableError("Could not read invoice file.") from exc
        return data, inv.file_mime or "application/pdf", inv.file_name or "beleg.pdf"

    async def _store_invoice_file(self, data: bytes, mime: str, key_name: str) -> str:
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        storage_key = f"invoices/{uuid.uuid4().hex}/{key_name}"
        try:
            await self.storage.put(storage_key, data, mime)
        except StorageError as exc:
            raise ServiceUnavailableError("Object storage write failed.") from exc
        return storage_key

    async def update_invoice(self, invoice_id: UUID, payload: InvoiceUpdate) -> InvoiceOut:
        """Update the fields that the payload sets and audit the change.

        The result shows every linked booking, because the write needs ``budget.book``,
        which is a full-view permission.

        Raises:
            NotFoundError: No invoice has this id.
        """
        inv = await self.session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFoundError(f"invoice {invoice_id} not found")
        fields = payload.model_fields_set
        if "number" in fields:
            inv.number = payload.number
        if "issue_date" in fields:
            inv.issue_date = payload.issue_date
        if "due_date" in fields:
            inv.due_date = payload.due_date
        if "supplier" in fields:
            inv.supplier = payload.supplier
        if "net_amount" in fields:
            inv.net_amount = payload.net_amount
        if "tax_amount" in fields:
            inv.tax_amount = payload.tax_amount
        if "gross_amount" in fields and payload.gross_amount is not None:
            inv.gross_amount = payload.gross_amount
        if "note" in fields:
            inv.note = payload.note
        if "status" in fields and payload.status is not None:
            inv.status = payload.status
        await self._audit(
            AuditAction.BUDGET_INVOICE_UPDATE,
            target_type="invoice",
            target_id=str(invoice_id),
            data={"fields": sorted(fields)},
        )
        await self.session.commit()
        return await self._invoice_with_bookings(inv, None)

    async def delete_invoice(self, invoice_id: UUID) -> None:
        """Delete an invoice and remove its stored original.

        A linked booking survives, because the FK sets its ``invoice_id`` to NULL. The
        original is removed as a best effort: if the object is already gone, the delete
        still stands.

        Raises:
            NotFoundError: No invoice has this id.
        """
        inv = await self.session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFoundError(f"invoice {invoice_id} not found")
        storage_key = inv.file_object_key
        await self._audit(
            AuditAction.BUDGET_INVOICE_DELETE,
            target_type="invoice",
            target_id=str(invoice_id),
            data={"number": inv.number, "gross": str(inv.gross_amount)},
        )
        await self.session.delete(inv)
        await self.session.commit()
        if storage_key is not None and self.storage is not None:
            try:
                await self.storage.remove(storage_key)
            except StorageError:
                logger.warning("could not remove file for deleted invoice %s", invoice_id)
