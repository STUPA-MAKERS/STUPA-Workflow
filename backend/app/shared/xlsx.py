"""Excel export helpers for the budget tree and the application list.

The module imports `openpyxl` lazily, only on the export path, so an environment without
the package still loads. An endpoint passes in data that it filtered already. This module
knows no database. It turns rows into bytes.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence, Set
from datetime import datetime
from decimal import Decimal
from functools import reduce
from io import BytesIO
from itertools import count
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - types only
    from uuid import UUID

    from openpyxl import Workbook
    from openpyxl.worksheet.worksheet import Worksheet

    from app.modules.applications.schemas import ApplicationListItem
    from app.modules.budget.tree_schemas import BudgetTreeNodeOut

XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _num(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


#: Leading characters that start an active formula or a DDE call when Excel or
#: LibreOffice opens the file (CSV and XLSX formula injection).
_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")


def _safe[T](value: T) -> T | str:
    """Neutralize formula injection.

    A string that starts with a dangerous character gets a leading apostrophe. The
    dangerous characters are `=`, `+`, `-`, `@`, tab and CR. A spreadsheet then treats
    the value as text and not as a formula. A value that is not a string, such as a
    number or `None`, passes through unchanged.
    """
    if isinstance(value, str) and value[:1] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def _append(worksheet: Worksheet, row: Sequence[object]) -> None:
    """Append a row with `ws.append` and protect every cell against formula injection."""
    worksheet.append([_safe(cell) for cell in row])


def _cell_width(cell: object) -> int:
    return len(str(cell)) if cell is not None else 0


def _column_widths(
    headers: Sequence[str], rows: Sequence[Sequence[object]]
) -> tuple[int, ...]:
    """Return the length of the longest cell of each column, the header included."""
    return tuple(
        max((len(str(header)), *(_cell_width(row[i]) for row in rows)))
        for i, header in enumerate(headers)
    )


def _autosize(worksheet: Worksheet, headers: Sequence[str]) -> None:
    """Fit each column width roughly to its longest cell."""
    rows = tuple(worksheet.iter_rows(min_row=2, values_only=True))
    widths = _column_widths(headers, rows)
    from openpyxl.utils import get_column_letter

    for i, width in enumerate(widths, start=1):
        worksheet.column_dimensions[get_column_letter(i)].width = min(width + 2, 60)


def _header_row(worksheet: Worksheet, headers: Sequence[str]) -> None:
    from openpyxl.styles import Font

    worksheet.append(list(headers))
    for cell in worksheet[1]:
        cell.font = Font(bold=True)
    worksheet.freeze_panes = "A2"


def _first_sheet(worksheet: Worksheet | None, title: str) -> Worksheet:
    """Give the default sheet of a new workbook its title."""
    assert worksheet is not None
    worksheet.title = title
    return worksheet


def _workbook_bytes(workbook: Workbook) -> bytes:
    """Serialize a workbook to `.xlsx` bytes."""
    buf = BytesIO()
    workbook.save(buf)
    return buf.getvalue()


def _iter_nodes(
    nodes: Iterable[BudgetTreeNodeOut], depth: int = 0
) -> Iterable[tuple[int, BudgetTreeNodeOut]]:
    for node in nodes:
        yield depth, node
        yield from _iter_nodes(node.children, depth + 1)


def build_budget_workbook(
    roots: Sequence[BudgetTreeNodeOut],
    *,
    fiscal_year_labels: Mapping[UUID, str],
    fiscal_year_id: UUID | None = None,
) -> bytes:
    """Build the budget tree as `.xlsx` bytes, with one sheet per fiscal year.

    Args:
        roots: The tree, already reduced to the visible selection of Gremium or
            subtree.
        fiscal_year_labels: Maps a fiscal year id to the sheet title. A year without an
            entry gets the sheet title `HHJ`.
        fiscal_year_id: Filter to a single fiscal year and write only its sheet. Pass
            `None` to write a sheet for every fiscal year.

    The sheets follow the first appearance of each fiscal year in tree order, so the sheet
    order stays stable.
    """
    from openpyxl import Workbook

    headers = [
        "Kostenstelle",
        "Schlüssel",
        "Zugeteilt",
        "Gebunden",
        "Beantragt",
        "Verfügbar",
        "Währung",
    ]
    nodes = tuple(_iter_nodes(roots))
    fy_order: tuple[Any, ...] = tuple(
        dict.fromkeys(
            alloc.fiscal_year_id
            for _depth, node in nodes
            for alloc in node.by_fiscal_year
            if fiscal_year_id is None or alloc.fiscal_year_id == fiscal_year_id
        )
    )

    wb = Workbook()
    default_ws = wb.active
    if default_ws is not None:
        wb.remove(default_ws)

    if not fy_order:
        empty = wb.create_sheet(title="Budget")
        _header_row(empty, headers)
        _autosize(empty, headers)
        return _workbook_bytes(wb)

    titles = _sheet_titles(tuple(fiscal_year_labels.get(fy, "HHJ") for fy in fy_order))
    for fy, title in zip(fy_order, titles, strict=True):
        ws = wb.create_sheet(title=title)
        _header_row(ws, headers)
        for depth, node in nodes:
            _append(ws, _budget_row(depth, node, fy))
        _autosize(ws, headers)

    return _workbook_bytes(wb)


def _budget_row(depth: int, node: BudgetTreeNodeOut, fy: object) -> list[object]:
    """Return the row of one cost center in the sheet of fiscal year ``fy``.

    A cost center without an allocation in that year gets empty amount cells.
    """
    indented = ("    " * depth) + node.name
    alloc = next((a for a in node.by_fiscal_year if a.fiscal_year_id == fy), None)
    amounts = (
        [None, None, None, None]
        if alloc is None
        else [
            _num(alloc.allocated),
            _num(alloc.committed),
            _num(alloc.requested),
            _num(alloc.available),
        ]
    )
    return [indented, node.path_key, *amounts, node.currency]


def _unique_title(label: str, used: Set[str]) -> str:
    r"""Build a sheet name that Excel accepts and that ``used`` does not hold yet.

    The name holds 31 characters at most and none of the characters `[]:*?/\`.
    """
    safe = ("".join("_" if c in '[]:*?/\\' else c for c in label).strip() or "HHJ")[:31]
    suffixed = (_suffixed(safe, n) for n in count(2))
    return safe if safe not in used else next(t for t in suffixed if t not in used)


def _suffixed(base: str, n: int) -> str:
    """Return ``base`` with the suffix `` (n)``, cut so the name keeps 31 characters."""
    suffix = f" ({n})"
    return base[: 31 - len(suffix)] + suffix


def _sheet_titles(labels: Sequence[str]) -> tuple[str, ...]:
    """Return one unique sheet name per label, in order."""
    start: tuple[str, ...] = ()
    return reduce(_add_title, labels, start)


def _add_title(titles: tuple[str, ...], label: str) -> tuple[str, ...]:
    """Return ``titles`` with a unique sheet name for ``label`` at the end."""
    return (*titles, _unique_title(label, frozenset(titles)))


def _sheet_title(label: str, used: set[str]) -> str:
    r"""Build a unique sheet name that Excel accepts and record it in ``used``.

    The name holds 31 characters at most and none of the characters `[]:*?/\`.
    """
    title = _unique_title(label, used)
    used.add(title)
    return title


def build_applications_workbook(
    items: Sequence[ApplicationListItem],
    *,
    type_names: dict[Any, str],
    gremium_names: dict[Any, str],
    locale: str = "de",
) -> bytes:
    """Build the application list as `.xlsx` bytes, in the order and filter as passed."""
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
        "Status seit",
    ]
    wb = Workbook()
    ws = _first_sheet(wb.active, "Anträge")
    _header_row(ws, headers)

    for item in items:
        _append(
            ws,
            [
                item.title or "",
                type_names.get(item.type_id, ""),
                _state_label(item, locale),
                gremium_names.get(item.gremium_id, "") if item.gremium_id else "",
                _num(item.amount),
                item.currency or "",
                _fmt_dt(item.created_at),
                _fmt_dt(item.updated_at),
                _fmt_dt(item.state_since),
            ],
        )

    _autosize(ws, headers)
    return _workbook_bytes(wb)


def _state_label(item: ApplicationListItem, locale: str) -> str:
    """Return the state label of an application in ``locale``, else German, else English."""
    label = (item.state.label or {}) if item.state is not None else {}
    return label.get(locale) or label.get("de") or label.get("en") or ""


def build_expenses_workbook(items: Iterable[Any], locale: str = "de") -> bytes:
    """Build the bookings, expenses and income, as `.xlsx` bytes.

    The rows keep the order and the filter as passed.
    """
    from openpyxl import Workbook

    kind_label = (
        {"expense": "Ausgabe", "income": "Einnahme"}
        if locale == "de"
        else {"expense": "Expense", "income": "Income"}
    )
    headers = [
        "Datum", "Art", "Beschreibung", "Kostenstelle", "Antrag", "Betrag", "Währung",
    ]
    wb = Workbook()
    ws = _first_sheet(wb.active, "Buchungen")
    _header_row(ws, headers)
    for e in items:
        _append(
            ws,
            [
                _fmt_dt(e.created_at),
                kind_label.get(e.kind, e.kind),
                e.description or "",
                e.path_key or "",
                e.application_title or "",
                _num(e.amount),
                e.currency or "",
            ],
        )
    _autosize(ws, headers)
    return _workbook_bytes(wb)


def build_auskunft_workbook(
    *,
    email: str,
    applications: Sequence[Mapping[str, Any]],
    versions: Sequence[Mapping[str, Any]],
    principal: Mapping[str, Any] | None,
) -> bytes:
    """Build the GDPR subject-access export (Art. 15) as `.xlsx` bytes.

    The workbook holds every personal data record stored for `email`. The function is
    database-agnostic and takes already-prepared rows. It writes three sheets: the
    account of the principal, the applications with `data` as JSON, and the versions.
    """
    from openpyxl import Workbook

    wb = Workbook()
    ws_account = _first_sheet(wb.active, "Konto")
    acc_headers = ["Feld", "Wert"]
    _header_row(ws_account, acc_headers)
    _append(ws_account, ["E-Mail (Anfrage)", email])
    if principal is not None:
        _append(ws_account, ["Login-Subjekt (sub)", principal.get("sub") or ""])
        _append(ws_account, ["E-Mail", principal.get("email") or ""])
        _append(ws_account, ["Anzeigename", principal.get("displayName") or ""])
        _append(ws_account, ["Aktiv", "ja" if principal.get("active") else "nein"])
        _append(ws_account, ["Letzter Login", _fmt_dt(principal.get("lastLogin"))])
    _autosize(ws_account, acc_headers)

    ws_apps = wb.create_sheet(title="Anträge")
    app_headers = [
        "Antrags-ID", "Antragstyp", "Status", "Erstellt", "Antragsteller", "Daten (JSON)",
    ]
    _header_row(ws_apps, app_headers)
    for a in applications:
        _append(
            ws_apps,
            [
                str(a.get("id") or ""),
                a.get("typeName") or "",
                a.get("status") or "",
                _fmt_dt(a.get("createdAt")),
                a.get("applicantName") or "",
                json.dumps(a.get("data") or {}, ensure_ascii=False, sort_keys=True),
            ],
        )
    _autosize(ws_apps, app_headers)

    ws_versions = wb.create_sheet(title="Versionen")
    v_headers = ["Antrags-ID", "Version", "Geändert von", "Zeitpunkt", "Daten (JSON)"]
    _header_row(ws_versions, v_headers)
    for v in versions:
        _append(
            ws_versions,
            [
                str(v.get("applicationId") or ""),
                v.get("version"),
                v.get("changedBy") or "",
                _fmt_dt(v.get("at")),
                json.dumps(v.get("data") or {}, ensure_ascii=False, sort_keys=True),
            ],
        )
    _autosize(ws_versions, v_headers)
    return _workbook_bytes(wb)


def _fmt_dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value is not None else ""
