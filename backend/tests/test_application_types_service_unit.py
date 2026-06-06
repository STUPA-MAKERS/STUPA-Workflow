"""Unit (ohne DB): ApplicationTypesService-Mapping + Query-Verzweigung.

Die ``AsyncSession`` wird durch ein Fake ersetzt, das ``scalar`` (Total) und
``scalars`` (Zeilen) bedient — so sind Paging-Hülle, i18n-Auflösung und die
Admin-/Public-Feldverzweigung ohne Postgres testbar. Echte SQL-Pfade: Integration.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.modules.application_types.service import ApplicationTypesService


class _ScalarsResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeSession:
    """Minimal-Session: merkt sich, ob ein WHERE-Filter (inaktiv-Ausschluss) greift."""

    def __init__(self, rows: list[object], total: int) -> None:
        self.rows = rows
        self.total = total
        self.scalar_calls = 0

    async def scalar(self, _stmt: object) -> int:
        self.scalar_calls += 1
        return self.total

    async def scalars(self, _stmt: object) -> _ScalarsResult:
        return _ScalarsResult(self.rows)


def _row(**over: object) -> SimpleNamespace:
    base = {
        "id": uuid4(),
        "key": "finanz",
        "name_i18n": {"de": "Finanzantrag", "en": "Funding request"},
        "has_budget": True,
        "active_form_version_id": uuid4(),
        "gremium_id": uuid4(),
    }
    base.update(over)
    return SimpleNamespace(**base)


def _run(coro):  # noqa: ANN001, ANN202 — Test-Helfer
    return asyncio.run(coro)


def test_list_public_maps_minimal_fields() -> None:
    row = _row()
    svc = ApplicationTypesService(_FakeSession([row], total=1))  # type: ignore[arg-type]
    page = _run(svc.list_types(lang="de", limit=50, offset=0))

    assert page.total == 1
    assert page.limit == 50
    assert page.offset == 0
    item = page.items[0]
    assert item.name == "Finanzantrag"
    assert item.has_budget is True
    assert item.active is True
    assert item.active_form_version_id == row.active_form_version_id
    # Public: keine Admin-Felder.
    assert item.key is None
    assert item.gremium_id is None


def test_list_resolves_name_for_lang() -> None:
    svc = ApplicationTypesService(_FakeSession([_row()], total=1))  # type: ignore[arg-type]
    page = _run(svc.list_types(lang="en", limit=50, offset=0))
    assert page.items[0].name == "Funding request"


def test_list_name_falls_back_to_key_when_i18n_empty() -> None:
    row = _row(name_i18n={})
    svc = ApplicationTypesService(_FakeSession([row], total=1))  # type: ignore[arg-type]
    page = _run(svc.list_types(lang="de", limit=50, offset=0))
    assert page.items[0].name == "finanz"


def test_list_admin_includes_extra_fields_and_inactive() -> None:
    row = _row(active_form_version_id=None)
    svc = ApplicationTypesService(_FakeSession([row], total=1))  # type: ignore[arg-type]
    page = _run(svc.list_types(lang="de", limit=50, offset=0, include_inactive=True, admin=True))
    item = page.items[0]
    assert item.active is False  # keine aktive Form-Version
    assert item.active_form_version_id is None
    assert item.key == "finanz"
    assert item.gremium_id == row.gremium_id


def test_list_empty_returns_zero_total() -> None:
    svc = ApplicationTypesService(_FakeSession([], total=0))  # type: ignore[arg-type]
    page = _run(svc.list_types(lang="de", limit=50, offset=0))
    assert page.total == 0
    assert page.items == []
