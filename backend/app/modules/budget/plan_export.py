"""The export of one version of a Haushaltsplan, without a database (§F/finance/budget/000875).

`build_export` turns the lines of a version into the rows that the XLSX file and the PDF
print: the Titel and their cost centers in tree order, grouped by side, with the sums
and the balance. `export_filename` names the file.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from app.modules.budget.plan_rules import PlanState, Side

Group = Literal["income", "expense", "none"]

#: The order of the groups in a file: Einnahmen, Ausgaben, then the Titel without a side.
GROUPS: tuple[Group, ...] = ("income", "expense", "none")

GROUP_LABELS: Mapping[Group, str] = {
    "income": "Einnahmen",
    "expense": "Ausgaben",
    "none": "Ohne Seite",
}

STATE_LABELS: Mapping[PlanState, str] = {
    "draft": "Entwurf",
    "in_progress": "Im Verfahren",
    "in_force": "In Kraft",
    "replaced": "Ersetzt",
}

_ZERO = Decimal("0.00")

_UMLAUTS = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}
)


class _Figures(Protocol):
    @property
    def fiscal_year_id(self) -> UUID: ...
    @property
    def expended(self) -> Decimal: ...
    @property
    def income(self) -> Decimal: ...


class _Node(Protocol):
    @property
    def id(self) -> UUID: ...
    @property
    def name(self) -> str: ...
    @property
    def path_key(self) -> str: ...
    @property
    def by_fiscal_year(self) -> Sequence[_Figures]: ...
    @property
    def children(self) -> Sequence[_Node]: ...


class _Line(Protocol):
    @property
    def budget_id(self) -> UUID: ...
    @property
    def side(self) -> Side | None: ...
    @property
    def amount(self) -> Decimal: ...
    @property
    def note(self) -> str | None: ...
    @property
    def name(self) -> str | None: ...
    @property
    def path_key(self) -> str | None: ...
    @property
    def transferable(self) -> bool: ...
    @property
    def coverable(self) -> bool: ...
    @property
    def blocked(self) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class ExportRow:
    """One line of the version. `depth` is 0 for a Titel."""

    key: str
    name: str
    depth: int
    amount: Decimal
    #: The Ansatz of the version before, for a Nachtrag. `None` without such a line.
    base: Decimal | None
    #: The Ansatz of the year before. `None` when that year has no line.
    prev: Decimal | None
    #: The booked amount of the year before. `None` without a year before or a side.
    actual: Decimal | None
    transferable: bool
    coverable: bool
    blocked: Decimal
    note: str

    @property
    def marks(self) -> str:
        """The Vermerke of the line as one text."""
        return ", ".join(
            label
            for label, on in (("übertragbar", self.transferable), ("deckungsfähig", self.coverable))
            if on
        )

    @property
    def change(self) -> Decimal | None:
        """The change against the version before, for a Nachtrag."""
        return None if self.base is None else self.amount - self.base


@dataclass(frozen=True, slots=True)
class ExportGroup:
    """The lines of one side with the sums of its Titel."""

    group: Group
    rows: tuple[ExportRow, ...]
    amount: Decimal
    base: Decimal
    prev: Decimal
    actual: Decimal

    @property
    def label(self) -> str:
        """The heading of the group."""
        return GROUP_LABELS[self.group]


@dataclass(frozen=True, slots=True)
class ExportHead:
    """What the head of a file says about the version."""

    budget_name: str
    fiscal_year: str
    #: The year before as the page shows it. `None` when the budget has none.
    prev_year: str | None
    number: int
    state: PlanState
    exported_on: date
    #: The name of the first step that a version in progress has not passed.
    step: str | None = None
    #: The year before has a plan in force, so the file shows its Ansatz and its Ist.
    prev_decided: bool = True

    @property
    def version(self) -> str:
        """The name of the version: "Haushaltsplan" or "Nachtrag n"."""
        return "Haushaltsplan" if self.number == 0 else f"Nachtrag {self.number}"

    @property
    def state_label(self) -> str:
        """The state of the version in words: the open step for a version in progress."""
        return (
            self.step
            if self.state == "in_progress" and self.step
            else STATE_LABELS[self.state]
        )

    @property
    def title(self) -> str:
        """The title of the document."""
        return f"{self.version} {self.budget_name} {self.fiscal_year}"

    @property
    def mark(self) -> str:
        """The state as a mark on each page. Empty for a version in force."""
        return "" if self.state == "in_force" else self.state_label


@dataclass(frozen=True, slots=True)
class PlanExport:
    """One version of a Haushaltsplan, ready for a file."""

    head: ExportHead
    groups: tuple[ExportGroup, ...]

    @property
    def nachtrag(self) -> bool:
        """The version is a Nachtrag, so the file shows the version before."""
        return self.head.number > 0

    @property
    def balance(self) -> Decimal:
        """Einnahmen minus Ausgaben of the version."""
        sums = {g.group: g.amount for g in self.groups}
        return sums.get("income", _ZERO) - sums.get("expense", _ZERO)


def _actual(node: _Node, side: Side | None, prev_fiscal_year_id: UUID | None) -> Decimal | None:
    """Return the booked amount of the year before: the income for the income side."""
    if prev_fiscal_year_id is None or side is None:
        return None
    view = next((v for v in node.by_fiscal_year if v.fiscal_year_id == prev_fiscal_year_id), None)
    if view is None:
        return _ZERO
    return view.income if side == "income" else view.expended


def _amount_of(lines: Mapping[UUID, _Line], node_id: UUID) -> Decimal | None:
    line = lines.get(node_id)
    return None if line is None else line.amount


def _rows(
    node: _Node,
    depth: int,
    lines: Mapping[UUID, _Line],
    base: Mapping[UUID, _Line],
    prev: Mapping[UUID, _Line],
    prev_fiscal_year_id: UUID | None,
) -> tuple[tuple[Side | None, ExportRow], ...]:
    """Return the row of a node and of each node below it that has a line."""
    line = lines.get(node.id)
    if line is None:
        return ()
    row = ExportRow(
        key=line.path_key or node.path_key,
        name=line.name or node.name,
        depth=depth,
        amount=line.amount,
        base=_amount_of(base, node.id),
        prev=_amount_of(prev, node.id),
        actual=_actual(node, line.side, prev_fiscal_year_id),
        transferable=line.transferable,
        coverable=line.coverable,
        blocked=line.blocked,
        note=line.note or "",
    )
    below = tuple(
        pair
        for child in node.children
        for pair in _rows(child, depth + 1, lines, base, prev, prev_fiscal_year_id)
    )
    return ((line.side, row), *below)


_Figure = Literal["amount", "base", "prev", "actual"]


def _total(rows: Sequence[ExportRow], field: _Figure) -> Decimal:
    """Sum one figure over the Titel of a group. A missing figure counts as zero."""
    return sum(
        (value for r in rows if r.depth == 0 and (value := getattr(r, field)) is not None),
        _ZERO,
    )


def build_export(
    head: ExportHead,
    top: _Node,
    lines: Sequence[_Line],
    *,
    base: Sequence[_Line] = (),
    prev: Sequence[_Line] = (),
    prev_fiscal_year_id: UUID | None = None,
) -> PlanExport:
    """Build the export of a version from its lines and the tree of its budget.

    Args:
        head: The head of the file.
        top: The top-level cost center with its subtree and the figures per year.
        lines: The lines of the version.
        base: The lines of the version before, for a Nachtrag.
        prev: The lines of the version in force of the year before.
        prev_fiscal_year_id: The year before, for the booked amounts.

    A cost center without a line is not in the file. A group without a line is left
    out, so a decided plan has no group "Ohne Seite".
    """
    by_id = {line.budget_id: line for line in lines}
    base_by_id = {line.budget_id: line for line in base}
    prev_by_id = {line.budget_id: line for line in prev}
    pairs = tuple(
        pair
        for child in top.children
        for pair in _rows(child, 0, by_id, base_by_id, prev_by_id, prev_fiscal_year_id)
    )
    grouped: tuple[tuple[Group, tuple[ExportRow, ...]], ...] = tuple(
        (group, tuple(row for side, row in pairs if (side or "none") == group))
        for group in GROUPS
    )
    return PlanExport(
        head=head,
        groups=tuple(
            ExportGroup(
                group=group,
                rows=rows,
                amount=_total(rows, "amount"),
                base=_total(rows, "base"),
                prev=_total(rows, "prev"),
                actual=_total(rows, "actual"),
            )
            for group, rows in grouped
            if rows
        ),
    )


RowKind = Literal["group", "line", "sum", "balance"]
Cell = Decimal | str | None


@dataclass(frozen=True, slots=True)
class SheetRow:
    """One row of the table of a file: a group heading, a line, a sum or the balance."""

    kind: RowKind
    depth: int
    cells: tuple[Cell, ...]


def _columns(
    export: PlanExport,
    *,
    key: Cell,
    name: Cell,
    amount: Cell,
    base: Cell = None,
    change: Cell = None,
    prev: Cell = None,
    actual: Cell = None,
    marks: Cell = None,
    blocked: Cell = None,
    note: Cell = None,
) -> tuple[Cell, ...]:
    """Return the cells of one row, with only the columns that the version has.

    A Nachtrag has the version before and the change. A year whose year before has
    a plan in force has the Ansatz and the booked amount of that year (spec 000889),
    because without a plan both columns hold nothing to compare.
    """
    has_prev = export.head.prev_year is not None and export.head.prev_decided
    return tuple(
        cell
        for on, cell in (
            (True, key),
            (True, name),
            (True, amount),
            (export.nachtrag, base),
            (export.nachtrag, change),
            (has_prev, prev),
            (has_prev, actual),
            (True, marks),
            (True, blocked),
            (True, note),
        )
        if on
    )


def sheet_headers(export: PlanExport) -> tuple[str, ...]:
    """Return the column headings of the table."""
    head = export.head
    return tuple(
        str(cell)
        for cell in _columns(
            export,
            key="Schlüssel",
            name="Bezeichnung",
            amount=f"Ansatz {head.fiscal_year}",
            base="Ansatz bisher",
            change="Änderung",
            prev=f"Ansatz {head.prev_year}",
            actual=f"Ist {head.prev_year}",
            marks="Vermerke",
            blocked="Gesperrt",
            note="Erläuterung",
        )
    )


def money_columns(export: PlanExport) -> frozenset[int]:
    """Return the places of the columns that hold an amount."""
    marker = Decimal(1)
    cells = _columns(
        export,
        key=None,
        name=None,
        amount=marker,
        base=marker,
        change=marker,
        prev=marker,
        actual=marker,
        blocked=marker,
    )
    return frozenset(i for i, cell in enumerate(cells) if cell is not None)


def _group_rows(export: PlanExport, group: ExportGroup) -> tuple[SheetRow, ...]:
    lines = tuple(
        SheetRow(
            "line",
            r.depth,
            _columns(
                export,
                key=r.key,
                name=r.name,
                amount=r.amount,
                base=r.base,
                change=r.change,
                prev=r.prev,
                actual=r.actual,
                marks=r.marks,
                blocked=r.blocked or None,
                note=r.note,
            ),
        )
        for r in group.rows
    )
    total = SheetRow(
        "sum",
        0,
        _columns(
            export,
            key=None,
            name=f"Summe {group.label}",
            amount=group.amount,
            base=group.base,
            change=group.amount - group.base,
            prev=group.prev,
            actual=group.actual,
        ),
    )
    heading = SheetRow("group", 0, _columns(export, key=None, name=group.label, amount=None))
    return (heading, *lines, total)


def sheet_rows(export: PlanExport) -> tuple[SheetRow, ...]:
    """Return the rows of the table: each group with its lines and its sum, then the balance."""
    balance = SheetRow(
        "balance",
        0,
        _columns(export, key=None, name="Saldo (Einnahmen − Ausgaben)", amount=export.balance),
    )
    return (*(row for group in export.groups for row in _group_rows(export, group)), balance)


def plan_lines(head: ExportHead) -> tuple[tuple[str, str], ...]:
    """Return what names the version, as pairs of a label and a value: the head of the PDF."""
    return (
        ("Haushalt", head.budget_name),
        ("Haushaltsjahr", head.fiscal_year),
        ("Version", head.version),
        ("Stand", head.state_label),
    )


def head_lines(head: ExportHead) -> tuple[tuple[str, str], ...]:
    """Return the head of the XLSX file: what names the version, and the day of the export."""
    return (*plan_lines(head), ("Exportiert am", head.exported_on.strftime("%d.%m.%Y")))


def money(value: Decimal) -> str:
    """Format an amount the German way: `1.234,56`, with a real minus sign."""
    text = f"{abs(value):,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return f"−{text}" if value < 0 else text


def _pdf_cell(cell: Cell) -> str:
    return money(cell) if isinstance(cell, Decimal) else (cell or "")


def pdf_source(export: PlanExport) -> str:
    """Return the Markdown source of the render request: the title of the document."""
    return f"---\ntitle: {json.dumps(export.head.title)}\n---\n"


def pdf_config(export: PlanExport) -> dict[str, object]:
    """Return the `plan` config of the render request: the head and the table as text.

    The render service prints what it gets. Each amount is already a text here, so
    the PDF and the sheet show the same figures.
    """
    return {
        "plan": {
            "title": export.head.title,
            "mark": export.head.mark,
            "head": [list(pair) for pair in plan_lines(export.head)],
            "headers": list(sheet_headers(export)),
            "money": sorted(money_columns(export)),
            "rows": [
                {"kind": row.kind, "depth": row.depth, "cells": [_pdf_cell(c) for c in row.cells]}
                for row in sheet_rows(export)
            ],
        }
    }


@dataclass(frozen=True, slots=True)
class PlanFile:
    """What the render service needs for the PDF of a version, and the name of the file."""

    source: str
    config: Mapping[str, object]
    name: str

    @property
    def record(self) -> dict[str, object]:
        """The file as one JSON object, for a snapshot."""
        return {"source": self.source, "config": dict(self.config), "name": self.name}


def plan_file(export: PlanExport) -> PlanFile:
    """Return the PDF request of an export."""
    return PlanFile(
        source=pdf_source(export),
        config=pdf_config(export),
        name=export_filename(export.head, "pdf"),
    )


def plan_file_of(record: Mapping[str, object]) -> PlanFile:
    """Read a file back from the JSON object of a snapshot."""
    config = record.get("config")
    return PlanFile(
        source=str(record.get("source", "")),
        config=config if isinstance(config, Mapping) else {},
        name=str(record.get("name", "Haushaltsplan.pdf")),
    )


def _slug(text: str) -> str:
    """Return `text` with only ASCII letters, digits and `-`, for a file name."""
    plain = text.translate(_UMLAUTS)
    ascii_only = unicodedata.normalize("NFKD", plain).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_only).strip("-") or "Haushalt"


def export_filename(head: ExportHead, extension: Literal["xlsx", "pdf"]) -> str:
    """Name the file: `Haushaltsplan_<Haushalt>_<year>[_Nachtrag-n][_Entwurf].<ext>`.

    The name holds ASCII only, so it is safe in a `Content-Disposition` header. A
    version in progress has no part for its state, because the file says it inside.
    """
    parts = (
        "Haushaltsplan",
        _slug(head.budget_name),
        _slug(head.fiscal_year),
        f"Nachtrag-{head.number}" if head.number > 0 else "",
        "Entwurf" if head.state == "draft" else "",
    )
    return "_".join(part for part in parts if part) + f".{extension}"
