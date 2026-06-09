"""Excel-Export-Helfer (TASKS #2).

Baut ``.xlsx``-Workbooks für den Budget-Baum und die Antragsliste. ``openpyxl``
wird **lazy** importiert (nur auf dem Export-Pfad), damit der Contract-CI ohne
das Paket lädt. Die Endpunkte (``/budget/export.xlsx`` /
``/applications/export.xlsx``) reichen bereits gefilterte Daten herein — dieses
Modul kennt keine DB, nur Reihen → Bytes.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from io import BytesIO
from typing import TYPE_CHECKING, Any, Iterable, Sequence

if TYPE_CHECKING:  # pragma: no cover - nur Typen
    from app.modules.applications.schemas import ApplicationListItem
    from app.modules.budget.tree_schemas import BudgetTreeNodeOut

XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _num(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


def _autosize(worksheet: Any, headers: Sequence[str]) -> None:
    """Spaltenbreite grob an die längste Zelle je Spalte anpassen."""
    widths = [len(str(h)) for h in headers]
    for row in worksheet.iter_rows(min_row=2, values_only=True):
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)) if cell is not None else 0)
    from openpyxl.utils import get_column_letter

    for i, width in enumerate(widths, start=1):
        worksheet.column_dimensions[get_column_letter(i)].width = min(width + 2, 60)


def _header_row(worksheet: Any, headers: Sequence[str]) -> None:
    from openpyxl.styles import Font

    worksheet.append(list(headers))
    for cell in worksheet[1]:
        cell.font = Font(bold=True)
    worksheet.freeze_panes = "A2"


def _iter_nodes(
    nodes: Iterable["BudgetTreeNodeOut"], depth: int = 0
) -> Iterable[tuple[int, "BudgetTreeNodeOut"]]:
    for node in nodes:
        yield depth, node
        yield from _iter_nodes(node.children, depth + 1)


def build_budget_workbook(
    roots: Sequence["BudgetTreeNodeOut"],
    *,
    fiscal_year_labels: dict[Any, str],
    fiscal_year_id: Any | None = None,
) -> bytes:
    """Budget-Baum (eine Zeile je Knoten×HHJ) als ``.xlsx``-Bytes.

    ``roots`` ist bereits auf die sichtbare Auswahl (Gremium/Teilbaum) reduziert;
    ``fiscal_year_id`` filtert optional auf ein einzelnes HHJ.
    """
    from openpyxl import Workbook

    headers = [
        "Kostenstelle",
        "Schlüssel",
        "Haushaltsjahr",
        "Zugeteilt",
        "Gebunden",
        "Beantragt",
        "Verfügbar",
        "Währung",
    ]
    wb = Workbook()
    ws = wb.active
    assert ws is not None  # noqa: S101 - openpyxl liefert immer ein aktives Sheet
    ws.title = "Budget"
    _header_row(ws, headers)

    for depth, node in _iter_nodes(roots):
        indented = ("    " * depth) + node.name
        allocations = [
            a
            for a in node.by_fiscal_year
            if fiscal_year_id is None or a.fiscal_year_id == fiscal_year_id
        ]
        if not allocations:
            ws.append([indented, node.path_key, "", None, None, None, None, node.currency])
            continue
        for alloc in allocations:
            ws.append(
                [
                    indented,
                    node.path_key,
                    fiscal_year_labels.get(alloc.fiscal_year_id, ""),
                    _num(alloc.allocated),
                    _num(alloc.committed),
                    _num(alloc.requested),
                    _num(alloc.available),
                    node.currency,
                ]
            )

    _autosize(ws, headers)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_applications_workbook(
    items: Sequence["ApplicationListItem"],
    *,
    type_names: dict[Any, str],
    gremium_names: dict[Any, str],
    locale: str = "de",
) -> bytes:
    """Antragsliste als ``.xlsx``-Bytes (Reihenfolge/Filter wie übergeben)."""
    from openpyxl import Workbook

    headers = [
        "Titel",
        "Antragstyp",
        "Status",
        "Gremium",
        "Betrag",
        "Währung",
        "Erstellt",
        "Aktualisiert",
    ]
    wb = Workbook()
    ws = wb.active
    assert ws is not None  # noqa: S101 - openpyxl liefert immer ein aktives Sheet
    ws.title = "Anträge"
    _header_row(ws, headers)

    for item in items:
        state_label = ""
        if item.state is not None:
            label = item.state.label or {}
            state_label = label.get(locale) or label.get("de") or label.get("en") or ""
        ws.append(
            [
                item.title or "",
                type_names.get(item.type_id, ""),
                state_label,
                gremium_names.get(item.gremium_id, "") if item.gremium_id else "",
                _num(item.amount),
                item.currency or "",
                _fmt_dt(item.created_at),
                _fmt_dt(item.updated_at),
            ]
        )

    _autosize(ws, headers)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _fmt_dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value is not None else ""
