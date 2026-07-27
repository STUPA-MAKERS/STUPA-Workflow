"""Invoice CRUD, ZUGFeRD/Factur-X import and invoice file storage."""

from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select

from app.modules.audit.actions import AuditAction
from app.modules.budget.invoice_import import parse_zugferd_pdf
from app.modules.budget.tree.service_base import BudgetTreeServiceBase
from app.modules.budget.tree_models import Invoice
from app.modules.budget.tree_schemas import (
    InvoiceCreate,
    InvoiceFileResult,
    InvoiceOut,
    InvoiceParseResult,
    InvoiceUpdate,
)
from app.modules.files.mime import MimeRejected, sanitize_filename, validate_upload
from app.modules.files.scanner import ScannerError, build_scanner
from app.modules.files.storage import StorageError
from app.search import dialect_of, trigram_rank
from app.shared.errors import (
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
    ValidationProblem,
)
from app.shared.paging import Page

logger = logging.getLogger("app.budget")

# An invoice file token is always a server-generated key under this prefix.
# Reject anything else, so a client cannot point fileObjectKey at a foreign
# object in the bucket.
_INVOICE_FILE_PREFIX = "invoices/"


def _validate_invoice_file_token(token: str) -> str:
    if not token.startswith(_INVOICE_FILE_PREFIX) or ".." in token:
        raise ValidationProblem("invalid invoice file token")
    return token


class InvoiceOps(BudgetTreeServiceBase):
    """Invoice CRUD plus ZUGFeRD parse/import and file streaming."""

    @staticmethod
    def _invoice_out(inv: Invoice) -> InvoiceOut:
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
        )

    async def list_invoices(self) -> list[InvoiceOut]:
        """List all invoices, newest issue date first.

        Kept for compatibility. The booking-link dropdown needs the full list.
        """
        page = await self.list_invoices_paged(limit=10_000, offset=0)
        return page.items

    async def list_invoices_paged(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        gross_min: Decimal | None = None,
        gross_max: Decimal | None = None,
        issue_from: str | None = None,
        issue_to: str | None = None,
        due_from: str | None = None,
        due_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[InvoiceOut]:
        """List invoices with filters, fuzzy search and offset pagination.

        This mirrors `expenses.ExpenseOps.list_expenses_paged`. The search and
        filter predicates live in one shared `filters` list. That list goes into
        the count query and into the row query, so the total and the hits do not
        drift on infinite scroll. With `q` the trigram rank orders the hits by
        relevance before the usual "newest issue date first".
        """
        filters = []
        # Fuzzy search: a trigram rank over number, supplier and note (GIN
        # indexes). On a non-Postgres dialect the ILIKE substring fallback runs.
        rank_expr = None
        if q and q.strip():
            where, rank_expr = trigram_rank(
                q,
                [Invoice.number, Invoice.supplier, Invoice.note],
                dialect=dialect_of(self.session),
            )
            filters.append(where)
        if status is not None:
            filters.append(Invoice.status == status)
        if gross_min is not None:
            filters.append(Invoice.gross_amount >= gross_min)
        if gross_max is not None:
            filters.append(Invoice.gross_amount <= gross_max)
        # Nullable date columns: an invoice without a date falls out of every
        # range. func.date parses the ISO string from the frontend datepicker
        # into a real date. Postgres rejects "date >= varchar". On SQLite the
        # call does nothing, because ISO stays ISO.
        if issue_from:
            filters.append(Invoice.issue_date >= func.date(issue_from))
        if issue_to:
            filters.append(Invoice.issue_date <= func.date(issue_to))
        if due_from:
            filters.append(Invoice.due_date >= func.date(due_from))
        if due_to:
            filters.append(Invoice.due_date <= func.date(due_to))

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
        return Page(
            items=[self._invoice_out(i) for i in rows],
            total=total or 0,
            limit=limit,
            offset=offset,
        )

    async def get_invoice(self, invoice_id: UUID) -> InvoiceOut:
        inv = await self.session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFoundError(f"invoice {invoice_id} not found")
        return self._invoice_out(inv)

    async def create_invoice(self, payload: InvoiceCreate, *, actor: str) -> InvoiceOut:
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
            # Take over the file from the ZUGFeRD import. The token is the MinIO
            # key of the stored object. The prefix check keeps foreign objects out.
            inv.file_object_key = _validate_invoice_file_token(payload.file_token)
            inv.file_name = payload.file_name
            inv.file_mime = payload.file_mime
        self.session.add(inv)
        await self.session.flush()  # generate the id for the audit entry
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
            The storage token, the sanitized file name and the MIME type.
        """
        max_bytes = self.settings.attachment_max_bytes
        if len(data) > max_bytes:
            raise PayloadTooLargeError(f"Invoice exceeds {max_bytes} bytes.")
        if not data:
            raise UnsupportedMediaTypeError("Empty file.")
        try:
            mime = validate_upload(filename, data)
        except MimeRejected as exc:
            raise UnsupportedMediaTypeError(str(exc)) from exc
        if mime != "application/pdf":
            raise UnsupportedMediaTypeError("Invoice import expects a PDF.")

        await self._scan_or_raise(data)
        safe_name = sanitize_filename(filename)
        storage_key = await self._store_invoice_file(data, mime, safe_name)
        return storage_key, safe_name, mime

    async def store_invoice_file(self, data: bytes, *, filename: str | None) -> InvoiceFileResult:
        """Validate and store an invoice PDF without a ZUGFeRD parse.

        This lets the user attach an original file to an invoice that carries no
        ZUGFeRD data.

        Returns:
            The same `fileToken` that `POST /invoices` expects.
        """
        storage_key, safe_name, mime = await self._validate_scan_store(data, filename=filename)
        return InvoiceFileResult(fileToken=storage_key, fileName=safe_name, fileMime=mime)

    async def parse_invoice_file(self, data: bytes, *, filename: str | None) -> InvoiceParseResult:
        """Validate the PDF, parse the ZUGFeRD data and store the original.

        The order is deliberate: scan first, then parse, then store. A PDF
        without ZUGFeRD data is the common case. It must leave no orphaned
        object behind.
        """
        max_bytes = self.settings.attachment_max_bytes
        if len(data) > max_bytes:
            raise PayloadTooLargeError(f"Invoice exceeds {max_bytes} bytes.")
        if not data:
            raise UnsupportedMediaTypeError("Empty file.")
        try:
            mime = validate_upload(filename, data)
        except MimeRejected as exc:
            raise UnsupportedMediaTypeError(str(exc)) from exc
        if mime != "application/pdf":
            raise UnsupportedMediaTypeError("Invoice import expects a PDF.")

        await self._scan_or_raise(data)
        # The parser runs synchronously and binds the CPU. Move it to a thread,
        # so it does not block the event loop.
        parsed = await asyncio.to_thread(parse_zugferd_pdf, data)

        safe_name = sanitize_filename(filename)
        storage_key = await self._store_invoice_file(data, mime, safe_name)
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
            fileName=safe_name,
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

    async def _scan_or_raise(self, data: bytes) -> None:
        """Scan the data for viruses and raise on a bad verdict.

        Without ClamAV the scan is skipped, which covers development and
        contract CI. In `production` the method fails closed. The server never
        stores an unscanned invoice PDF when the scanner is missing. This
        matches the quarantine of the files module.
        """
        scanner = build_scanner(self.settings)
        if scanner is None:
            if self.settings.environment == "production":
                raise ServiceUnavailableError("Virus scan unavailable.")
            return
        try:
            verdict = await scanner.scan(data)
        except ScannerError as exc:
            raise ServiceUnavailableError("Virus scan unavailable.") from exc
        if not verdict.clean:
            raise UnsupportedMediaTypeError(
                f"File rejected by virus scan: {verdict.signature or 'unknown'}"
            )

    async def _store_invoice_file(self, data: bytes, mime: str, safe_name: str) -> str:
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        storage_key = f"invoices/{uuid.uuid4().hex}/{safe_name}"
        try:
            await self.storage.put(storage_key, data, mime)
        except StorageError as exc:
            raise ServiceUnavailableError("Object storage write failed.") from exc
        return storage_key

    async def update_invoice(self, invoice_id: UUID, payload: InvoiceUpdate) -> InvoiceOut:
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
        return self._invoice_out(inv)

    async def delete_invoice(self, invoice_id: UUID) -> None:
        inv = await self.session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFoundError(f"invoice {invoice_id} not found")
        # A booking survives the delete. The FK sets its invoice_id to NULL.
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
            # Remove the original as a best effort. If the object is already
            # gone, the delete still stands.
            try:
                await self.storage.remove(storage_key)
            except StorageError:
                logger.warning("could not remove file for deleted invoice %s", invoice_id)
