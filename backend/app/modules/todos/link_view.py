"""The read sheet of a link target: what a card shows to its readers (spec 000487).

A person who reads a card reads the elements that it links, also from a Kostenstelle or
a Gremium that the person cannot read otherwise. The sheet is read only and shows the
facts of one target:

* application — the amounts and the form answers of the plain field types. A field that
  any form version of the type marks as ``isPII`` stays out, and so do e-mail, IBAN,
  file and table fields, because they carry personal data without the flag;
* expense and invoice — the booking and invoice fields;
* meeting — the date, the time, the status and the agenda;
* agenda item — the meeting, the text and the votes of the item;
* vote — the question, the meeting, the status and the result;
* todo — the board, the column, the description and the checklist, without its links,
  because the access does not continue to the links of a linked card.

A ticket and a gremium have no sheet: a ticket holds the report of a person outside the
team, and the gremium page has its own gate.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Gremium
from app.modules.applications.models import Application
from app.modules.applications.service.service_base import pii_keys_for_type
from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import Budget, BudgetExpense, Invoice
from app.modules.forms.models import FormField
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.todos.links import GRANT_KINDS, LinkResolver
from app.modules.todos.models import TodoBoard, TodoCard, TodoCheckItem, TodoColumn
from app.modules.todos.schemas import TodoLinkDetail, TodoLinkView, TodoViewFact, TodoViewRow
from app.modules.voting.models import Vote
from app.shared.errors import NotFoundError

#: The form field types that the sheet shows. Every other type stays out: e-mail and
#: IBAN carry personal data without the ``isPII`` flag, the rest has no plain value.
SHOWN_FIELD_TYPES: frozenset[str] = frozenset(
    {"text", "textarea", "markdown", "number", "currency", "date", "select", "multiselect"}
)
#: The answers that the sheet already shows in its title.
SKIPPED_FIELD_KEYS: frozenset[str] = frozenset({"title"})

type Built = tuple[list[TodoViewFact], list[TodoViewRow]]


def _fact(key: str, value: object, fmt: str = "text") -> TodoViewFact | None:
    """One fact, or None for an empty value."""
    if value is None or value == "":
        return None
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)  # type: ignore[attr-defined]
    return TodoViewFact(key=key, value=text, format=fmt)  # type: ignore[arg-type]


def _facts(*items: TodoViewFact | None) -> list[TodoViewFact]:
    return [item for item in items if item is not None]


def _answer(field: FormField, value: Any) -> TodoViewFact | None:  # noqa: ANN401
    """The fact of one form answer, or None for an empty or unshown value."""
    if field.type not in SHOWN_FIELD_TYPES or value is None or value in ("", []):
        return None
    if isinstance(value, list):
        text = ", ".join(str(v) for v in value)
    elif isinstance(value, dict):
        return None
    else:
        text = str(value)
    fmt = {"currency": "money", "date": "date", "textarea": "markdown", "markdown": "markdown"}
    return TodoViewFact(
        key=field.key,
        label={str(k): str(v) for k, v in (field.label_i18n or {}).items()},
        value=text,
        format=fmt.get(field.type, "text"),  # type: ignore[arg-type]
    )


def _money(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


class LinkViewer:
    """Build the read sheet of one link target."""

    def __init__(self, session: AsyncSession, links: LinkResolver) -> None:
        """Bind the viewer to a session and the link resolver of the request."""
        self.session = session
        self.links = links

    async def view(self, kind: str, target_id: uuid.UUID, principal: Principal) -> TodoLinkView:
        """Return the sheet of the target.

        Raises:
            NotFoundError: The kind has no sheet, or the principal does not read the
                target (HTTP 404).
        """
        if kind not in GRANT_KINDS:
            raise NotFoundError(f"{kind} {target_id} not found")
        found = (await self.links.resolve([(kind, target_id)], principal))[(kind, target_id)]
        if not found.accessible:
            raise NotFoundError(f"{kind} {target_id} not found")
        builders: dict[str, Callable[[uuid.UUID], Awaitable[Built]]] = {
            "application": self._application,
            "meeting": self._meeting,
            "agenda_item": self._agenda_item,
            "vote": self._vote,
            "invoice": self._invoice,
            "expense": self._expense,
            "todo": self._todo,
        }
        facts, rows = await builders[kind](target_id)
        return TodoLinkView(
            kind=kind,  # type: ignore[arg-type]
            title=found.title or "",
            detail=found.detail or TodoLinkDetail(),
            facts=facts,
            rows=rows,
        )

    async def _application(self, target_id: uuid.UUID) -> Built:
        app = await self.session.get(Application, target_id)
        if app is None:  # pragma: no cover - the resolver found it
            return [], []
        hidden = await pii_keys_for_type(self.session, app.type_id)
        fields = (
            await self.session.scalars(
                select(FormField)
                .where(FormField.form_version_id == app.form_version_id)
                .order_by(FormField.order, FormField.key)
            )
        ).all()
        data = app.data or {}
        answers = [
            _answer(f, data.get(f.key))
            for f in fields
            if not f.is_pii and f.key not in hidden and f.key not in SKIPPED_FIELD_KEYS
        ]
        return (
            _facts(
                _fact("amount", _money(app.amount), "money"),
                _fact("approvedAmount", _money(app.approved_amount), "money"),
                *answers,
            ),
            [],
        )

    async def _meeting(self, target_id: uuid.UUID) -> Built:
        row = (
            await self.session.execute(
                select(Meeting, Gremium.name)
                .join(Gremium, Gremium.id == Meeting.gremium_id)
                .where(Meeting.id == target_id)
            )
        ).first()
        if row is None:  # pragma: no cover - the resolver found it
            return [], []
        meeting, gremium = row
        start = meeting.start_time
        items = (
            await self.session.execute(
                select(MeetingAgendaItem, Application.data)
                .outerjoin(Application, Application.id == MeetingAgendaItem.application_id)
                .where(MeetingAgendaItem.meeting_id == meeting.id)
                .order_by(
                    MeetingAgendaItem.position,
                    MeetingAgendaItem.created_at,
                    MeetingAgendaItem.id,
                )
            )
        ).all()
        rows = [
            TodoViewRow(
                title=item.title or str((data or {}).get("title") or ""),
                done=item.done_at is not None,
            )
            for item, data in items
        ]
        return (
            _facts(
                _fact("gremium", gremium),
                _fact("date", meeting.date, "date"),
                _fact("startTime", start.strftime("%H:%M") if start is not None else None),
                _fact("meetingStatus", meeting.status),
            ),
            rows,
        )

    async def _agenda_item(self, target_id: uuid.UUID) -> Built:
        item = await self.session.get(MeetingAgendaItem, target_id)
        if item is None:  # pragma: no cover - the resolver found it
            return [], []
        votes = (
            await self.session.scalars(
                select(Vote).where(Vote.agenda_item_id == item.id).order_by(Vote.created_at)
            )
        ).all()
        rows = [
            TodoViewRow(
                title=v.question or "", meta=v.result or v.status, done=v.status == "closed"
            )
            for v in votes
        ]
        return _facts(_fact("body", item.body, "markdown")), rows

    async def _vote(self, target_id: uuid.UUID) -> Built:
        vote = await self.session.get(Vote, target_id)
        if vote is None:  # pragma: no cover - the resolver found it
            return [], []
        return (
            _facts(
                _fact("voteStatus", vote.status),
                _fact("voteResult", vote.result),
                _fact("eligible", vote.eligible_count),
            ),
            [],
        )

    async def _invoice(self, target_id: uuid.UUID) -> Built:
        inv = await self.session.get(Invoice, target_id)
        if inv is None:  # pragma: no cover - the resolver found it
            return [], []
        return (
            _facts(
                _fact("number", inv.number),
                _fact("supplier", inv.supplier),
                _fact("issueDate", inv.issue_date, "date"),
                _fact("dueDate", inv.due_date, "date"),
                _fact("netAmount", _money(inv.net_amount), "money"),
                _fact("taxAmount", _money(inv.tax_amount), "money"),
                _fact("grossAmount", _money(inv.gross_amount), "money"),
                _fact("invoiceStatus", inv.status),
                _fact("note", inv.note, "markdown"),
            ),
            [],
        )

    async def _expense(self, target_id: uuid.UUID) -> Built:
        row = (
            await self.session.execute(
                select(BudgetExpense, Budget.path_key, Budget.name)
                .join(Budget, Budget.id == BudgetExpense.budget_id)
                .where(BudgetExpense.id == target_id)
            )
        ).first()
        if row is None:  # pragma: no cover - the resolver found it
            return [], []
        exp, path_key, budget_name = row
        return (
            _facts(
                _fact("amount", _money(exp.amount), "money"),
                _fact("bookingKind", exp.kind),
                _fact("costCentre", f"{path_key} {budget_name}".strip()),
                _fact("counterparty", exp.correspondent),
                _fact("invoiceDate", exp.invoice_date, "date"),
                _fact("paymentDate", exp.payment_date, "date"),
                _fact("referenceNumber", exp.reference_number),
                _fact("paymentMethod", exp.payment_method),
                _fact("category", exp.category),
                _fact("note", exp.note, "markdown"),
            ),
            [],
        )

    async def _todo(self, target_id: uuid.UUID) -> Built:
        row = (
            await self.session.execute(
                select(TodoCard, TodoBoard.name, TodoColumn.name)
                .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                .where(TodoCard.id == target_id)
            )
        ).first()
        if row is None:  # pragma: no cover - the resolver found it
            return [], []
        card, _board, _column = row
        items = (
            await self.session.scalars(
                select(TodoCheckItem)
                .where(TodoCheckItem.card_id == card.id)
                .order_by(TodoCheckItem.position, TodoCheckItem.id)
            )
        ).all()
        rows = [TodoViewRow(title=i.text, done=i.done) for i in items]
        return (
            _facts(
                _fact("dueDate", card.due_date, "date"),
                _fact("description", card.description_md, "markdown"),
            ),
            rows,
        )
