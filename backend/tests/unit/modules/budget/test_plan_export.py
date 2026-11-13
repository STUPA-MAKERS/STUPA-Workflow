"""Unit tests of the export of a plan version, without a database."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from io import BytesIO

from openpyxl import load_workbook

from app.modules.budget import plan_export
from app.modules.budget.plan_export import ExportHead, PlanExport, build_export
from app.modules.budget.plan_rules import PlanState, Side
from app.shared.xlsx import build_table_workbook

D = Decimal
_PREV = uuid.uuid4()


@dataclass(frozen=True, slots=True)
class _Figures:
    fiscal_year_id: uuid.UUID
    expended: Decimal = D(0)
    income: Decimal = D(0)


@dataclass(frozen=True, slots=True)
class _Node:
    name: str
    path_key: str
    children: tuple[_Node, ...] = ()
    by_fiscal_year: tuple[_Figures, ...] = ()
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(frozen=True, slots=True)
class _Line:
    budget_id: uuid.UUID
    amount: Decimal
    side: Side | None = None
    note: str | None = None
    name: str | None = None
    path_key: str | None = None
    transferable: bool = False
    coverable: bool = False
    blocked: Decimal = D(0)


def _head(number: int = 0, state: PlanState = "draft", prev: str | None = "2025") -> ExportHead:
    return ExportHead(
        budget_name="VS-Mittel",
        fiscal_year="2026",
        prev_year=prev,
        number=number,
        state=state,
        exported_on=date(2026, 11, 13),
    )


_FEES = _Node("Beiträge", "VS-1", by_fiscal_year=(_Figures(_PREV, income=D("95.50")),))
_OFFICE = _Node("Büro", "VS-8-1", by_fiscal_year=(_Figures(_PREV, expended=D("30")),))
_OUTSIDE = _Node("Ohne Zeile", "VS-8-2")
_GRANTS = _Node("Zuschüsse", "VS-8", children=(_OFFICE, _OUTSIDE))
_OPEN = _Node("Neu", "VS-9")
_TOP = _Node("VS-Mittel", "VS", children=(_FEES, _GRANTS, _OPEN))


def _export(number: int = 0, state: PlanState = "draft", prev: str | None = "2025") -> PlanExport:
    lines = (
        _Line(_FEES.id, D("100"), side="income"),
        _Line(_GRANTS.id, D("60"), side="expense", transferable=True, coverable=True),
        _Line(
            _OFFICE.id, D("60"), side="expense", coverable=True, blocked=D("5"), note="IT",
            name="Büro alt", path_key="VS-8-9",
        ),
        _Line(_OPEN.id, D("0")),
    )
    return build_export(
        _head(number, state, prev),
        _TOP,
        lines,
        base=(_Line(_FEES.id, D("80"), side="income"),) if number else (),
        prev=(_Line(_GRANTS.id, D("50"), side="expense"),),
        prev_fiscal_year_id=_PREV if prev else None,
    )


def test_the_rows_follow_the_tree_and_the_sides() -> None:
    """Rule: §F/finance/budget/000875. A cost center without a line is not in the file."""
    export = _export()
    assert [g.group for g in export.groups] == ["income", "expense", "none"]
    income, expense, none = export.groups
    assert [(r.key, r.name, r.depth) for r in expense.rows] == [
        ("VS-8", "Zuschüsse", 0),
        ("VS-8-9", "Büro alt", 1),
    ]
    assert (income.amount, expense.amount, export.balance) == (D("100"), D("60"), D("40"))
    assert (income.rows[0].prev, income.rows[0].actual) == (None, D("95.50"))
    assert (expense.rows[0].prev, expense.rows[0].actual) == (D("50"), D("0.00"))
    assert expense.rows[1].actual == D("30")
    assert (expense.prev, expense.actual, income.actual) == (D("50"), D("0.00"), D("95.50"))
    assert none.rows[0].actual is None
    assert [r.marks for r in expense.rows] == ["übertragbar, deckungsfähig", "deckungsfähig"]
    assert none.label == "Ohne Seite"


def test_a_plan_without_lines_has_no_group_and_a_balance_of_zero() -> None:
    """A group without a line is left out."""
    export = build_export(_head(), _TOP, ())
    assert export.groups == ()
    assert export.balance == D("0.00")
    assert [row.kind for row in plan_export.sheet_rows(export)] == ["balance"]


def test_the_table_of_a_first_plan_with_a_year_before() -> None:
    """The table has the Ansatz and the Ist of the year before, and no change."""
    export = _export()
    headers = plan_export.sheet_headers(export)
    rows = plan_export.sheet_rows(export)
    assert headers == (
        "Schlüssel", "Bezeichnung", "Ansatz 2026", "Ansatz 2025", "Ist 2025",
        "Vermerke", "Gesperrt", "Erläuterung",
    )
    assert plan_export.money_columns(export) == frozenset({2, 3, 4, 6})
    assert [row.kind for row in rows] == [
        "group", "line", "sum", "group", "line", "line", "sum", "group", "line", "sum", "balance",
    ]
    assert all(len(row.cells) == len(headers) for row in rows)
    assert rows[5].cells == (
        "VS-8-9", "Büro alt", D("60"), None, D("30"), "deckungsfähig", D("5"), "IT",
    )
    assert rows[4].cells[6] is None
    assert rows[6].cells[:3] == (None, "Summe Ausgaben", D("60"))
    assert rows[-1].cells[1:3] == ("Saldo (Einnahmen − Ausgaben)", D("40"))


def test_the_table_of_a_nachtrag_shows_the_version_before_and_the_change() -> None:
    """A Nachtrag has the columns of the version before. No year before: no such columns."""
    export = _export(number=2, state="in_progress", prev=None)
    assert plan_export.sheet_headers(export) == (
        "Schlüssel", "Bezeichnung", "Ansatz 2026", "Ansatz bisher", "Änderung",
        "Vermerke", "Gesperrt", "Erläuterung",
    )
    rows = plan_export.sheet_rows(export)
    assert rows[1].cells[2:5] == (D("100"), D("80"), D("20"))
    assert rows[4].cells[2:5] == (D("60"), None, None)
    assert rows[2].cells[2:5] == (D("100"), D("80"), D("20"))
    assert export.groups[0].rows[0].actual is None


def test_the_head_names_the_version_and_its_state() -> None:
    """A version that is not in force has a mark for each page."""
    draft, nachtrag, decided = _head(), _head(1, "in_progress"), _head(0, "in_force")
    assert (draft.version, draft.title, draft.mark) == (
        "Haushaltsplan", "Haushaltsplan VS-Mittel 2026", "Entwurf",
    )
    assert (nachtrag.version, nachtrag.mark) == ("Nachtrag 1", "Im Verfahren")
    assert decided.mark == ""
    assert _head(0, "replaced").mark == "Ersetzt"
    assert plan_export.head_lines(draft) == (
        ("Haushalt", "VS-Mittel"),
        ("Haushaltsjahr", "2026"),
        ("Version", "Haushaltsplan"),
        ("Stand", "Entwurf"),
        ("Exportiert am", "13.11.2026"),
    )


def test_a_version_in_progress_shows_its_open_step() -> None:
    """Rule: §F/finance/budget/000875. The open step stands in place of the state."""
    waits = replace(_head(0, "in_progress"), step="Genehmigung Rektorat")
    assert (waits.state_label, waits.mark) == ("Genehmigung Rektorat", "Genehmigung Rektorat")
    assert ("Stand", "Genehmigung Rektorat") in plan_export.head_lines(waits)
    assert _head(0, "in_progress").state_label == "Im Verfahren"
    assert replace(_head(0, "draft"), step="Beschluss StuPa").state_label == "Entwurf"


def test_the_file_name() -> None:
    """The name holds the budget, the year, the Nachtrag and the draft state, in ASCII."""
    name = plan_export.export_filename
    assert name(_head(), "xlsx") == "Haushaltsplan_VS-Mittel_2026_Entwurf.xlsx"
    assert name(_head(2, "in_force"), "pdf") == "Haushaltsplan_VS-Mittel_2026_Nachtrag-2.pdf"
    odd = ExportHead("Töpfe & Äpfel/ß", "2026/27", None, 0, "in_progress", date(2026, 1, 1))
    assert name(odd, "pdf") == "Haushaltsplan_Toepfe-Aepfel-ss_2026-27.pdf"
    blank = ExportHead("€€", "2026", None, 0, "in_force", date(2026, 1, 1))
    assert name(blank, "pdf") == "Haushaltsplan_Haushalt_2026.pdf"


def test_money_is_german() -> None:
    """An amount has a point per thousand, a comma and a real minus sign."""
    assert plan_export.money(D("1234567.5")) == "1.234.567,50"
    assert plan_export.money(D("-40")) == "−40,00"
    assert plan_export.money(D("0")) == "0,00"


def test_the_pdf_request_holds_the_table_as_text() -> None:
    """The render service gets each cell as a text and the title as YAML."""
    export = _export()
    plan = plan_export.pdf_config(export)["plan"]
    assert isinstance(plan, dict)
    assert plan["title"] == "Haushaltsplan VS-Mittel 2026"
    assert plan["mark"] == "Entwurf"
    assert [pair[0] for pair in plan["head"]] == ["Haushalt", "Haushaltsjahr", "Version", "Stand"]
    assert plan["money"] == [2, 3, 4, 6]
    assert plan["rows"][5] == {
        "kind": "line",
        "depth": 1,
        "cells": ["VS-8-9", "Büro alt", "60,00", "", "30,00", "deckungsfähig", "5,00", "IT"],
    }
    assert plan_export.pdf_source(export) == '---\ntitle: "Haushaltsplan VS-Mittel 2026"\n---\n'


def test_the_workbook_holds_the_head_and_the_amounts_as_numbers() -> None:
    """Rule: §F/finance/budget/000875. A text that starts a formula is made safe."""
    export = _export()
    rows = plan_export.sheet_rows(export)
    data = build_table_workbook(
        title=export.head.title,
        head=(*plan_export.head_lines(export.head), ("Notiz", "=1+1")),
        headers=plan_export.sheet_headers(export),
        rows=[row.cells for row in rows],
        bold_rows=frozenset(i for i, row in enumerate(rows) if row.kind != "line"),
        indents={i: row.depth for i, row in enumerate(rows)},
        money_columns=plan_export.money_columns(export),
    )
    ws = load_workbook(BytesIO(data)).active
    assert ws is not None
    cells = [[c.value for c in row] for row in ws.iter_rows()]
    assert cells[0][0] == "Haushaltsplan VS-Mittel 2026"
    assert cells[4][:2] == ["Stand", "Entwurf"]
    assert cells[6][:2] == ["Notiz", "'=1+1"]
    header = 8
    assert cells[header][:3] == ["Schlüssel", "Bezeichnung", "Ansatz 2026"]
    office = ws[header + 1 + 6]
    assert [c.value for c in office][:3] == ["VS-8-9", "Büro alt", 60]
    assert office[2].number_format == "#,##0.00"
    assert office[1].alignment.indent == 1
    assert office[0].font.bold is False
    assert ws[header + 1 + 7][1].font.bold is True
    assert ws.freeze_panes == f"A{header + 2}"
    assert ws.title == "Haushaltsplan VS-Mittel 2026"
