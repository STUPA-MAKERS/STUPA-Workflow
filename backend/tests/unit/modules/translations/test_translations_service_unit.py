"""``TranslationService`` and the catalog without a database: a fake session records the writes."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.translations import catalog as catalog_mod
from app.modules.translations import service as svc_mod
from app.modules.translations.catalog import BuiltinText
from app.modules.translations.models import UiLanguage
from app.modules.translations.service import TranslationService
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

TEXTS = {
    "a.count": BuiltinText(de="{count} Anträge", en="{count} applications"),
    "a.title": BuiltinText(de="Titel", en=None),
    "b.save": BuiltinText(de="Speichern", en="Save"),
}


class _Rows:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)

    def __iter__(self) -> Any:
        return iter(self._items)


class _Session:
    """Answers ``get`` from a store and ``scalars``/``execute`` from queues."""

    def __init__(
        self, *, scalars: list[list[Any]] | None = None, execute: list[list[Any]] | None = None
    ) -> None:
        self.store: dict[str, UiLanguage] = {}
        self.scalars_q = list(scalars or [])
        self.execute_q = list(execute or [])
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = 0
        self.refreshed: list[Any] = []

    async def get(self, _model: type, ident: str) -> Any:
        return self.store.get(ident)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed += 1

    async def refresh(self, obj: Any) -> None:
        self.refreshed.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def scalars(self, stmt: Any) -> _Rows:
        self.statements.append(stmt)
        return _Rows(self.scalars_q.pop(0))

    async def execute(self, stmt: Any) -> _Rows:
        self.statements.append(stmt)
        return _Rows(self.execute_q.pop(0) if self.execute_q else [])


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The audit entries that the service writes."""
    seen: list[dict[str, Any]] = []

    async def _record(_session: Any, **kw: Any) -> None:
        seen.append(kw)

    monkeypatch.setattr(svc_mod, "audit_record", _record)
    monkeypatch.setattr(svc_mod, "builtin_texts", lambda: TEXTS)
    monkeypatch.setattr(
        svc_mod,
        "catalog",
        lambda: {key: catalog_mod.placeholders_of(t.de) for key, t in TEXTS.items()},
    )
    return seen


def _lang(code: str = "fr", *, active: bool = True) -> UiLanguage:
    return UiLanguage(code=code, name="Français", active=active)


async def test_languages_filter_the_active_ones(audits: list[dict[str, Any]]) -> None:
    del audits
    session = _Session(scalars=[[_lang()], [_lang()]])
    service = TranslationService(session)  # type: ignore[arg-type]
    assert [r.code for r in await service.languages(active_only=False)] == ["fr"]
    await service.languages(active_only=True)
    assert "WHERE" not in str(session.statements[0]).upper()
    assert "active" in str(session.statements[1])


async def test_create_language_refuses_builtin_and_existing(audits: list[dict[str, Any]]) -> None:
    session = _Session()
    session.store["fr"] = _lang()
    service = TranslationService(session)  # type: ignore[arg-type]
    for code, problem in (("de", "language_builtin"), ("fr", "language_exists")):
        with pytest.raises(ConflictError) as exc:
            await service.create_language(code=code, name="X", active=True, actor="admin")
        assert exc.value.code == problem
    row = await service.create_language(code="pt-BR", name="Português", active=False, actor="adm")
    assert (row.code, row.name, row.active, row.updated_by) == ("pt-BR", "Português", False, "adm")
    assert row.created_at == row.updated_at
    assert session.added == [row] and session.refreshed == [row] and session.committed == 1
    assert audits == [
        {
            "actor": "adm",
            "action": svc_mod.AuditAction.CONFIG_CHANGE,
            "target_type": "ui_language",
            "target_id": "pt-BR",
            "data": {"created": True, "name": "Português", "active": False},
        }
    ]


async def test_update_language_audits_only_real_changes(audits: list[dict[str, Any]]) -> None:
    session = _Session()
    row = _lang(active=False)
    session.store["fr"] = row
    service = TranslationService(session)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError) as exc:
        await service.update_language("it", name="Italiano", active=None, actor="a")
    assert exc.value.code == "language_not_found"
    await service.update_language("fr", name="Français", active=False, actor="a")
    await service.update_language("fr", name=None, active=None, actor="a")
    assert audits == [] and session.committed == 2
    await service.update_language("fr", name="French", active=True, actor="b")
    assert (row.name, row.active, row.updated_by) == ("French", True, "b")
    assert audits[0]["data"] == {
        "name": {"from": "Français", "to": "French"},
        "active": {"from": False, "to": True},
    }


async def test_delete_language_counts_its_overrides(audits: list[dict[str, Any]]) -> None:
    session = _Session(scalars=[["a.title", "b.save"]])
    row = _lang()
    session.store["fr"] = row
    service = TranslationService(session)  # type: ignore[arg-type]
    await service.delete_language("fr", actor="a")
    assert session.deleted == [row] and session.committed == 1
    assert audits[0]["data"] == {"deleted": True, "overrides": 2}
    assert "DELETE" in str(session.statements[0]).upper()


async def test_overrides_leave_out_null_rows(audits: list[dict[str, Any]]) -> None:
    del audits
    session = _Session(execute=[[("a.title", "Title"), ("b.save", None)], []])
    service = TranslationService(session)  # type: ignore[arg-type]
    assert await service.overrides("en") == {"a.title": "Title"}
    with pytest.raises(NotFoundError):
        await service.admin_overrides("xx")
    assert await service.admin_overrides("de") == {}


async def test_builtin_filters_by_prefix_and_open_work(audits: list[dict[str, Any]]) -> None:
    del audits
    session = _Session(execute=[[("a.title", "Title")], [("a.title", "Title")]])
    service = TranslationService(session)  # type: ignore[arg-type]
    with pytest.raises(ValidationProblem) as exc:
        await service.builtin(prefix=None, locale=None, untranslated=True)
    assert exc.value.code == "locale_required"
    every = await service.builtin(prefix=None, locale=None, untranslated=False)
    assert [key for key, _t, _o in every] == ["a.count", "a.title", "b.save"]
    assert all(own is None for _k, _t, own in every)
    a_keys = await service.builtin(prefix="a.", locale="en", untranslated=False)
    assert [(key, own) for key, _t, own in a_keys] == [("a.count", None), ("a.title", "Title")]
    open_work = await service.builtin(prefix=None, locale="en", untranslated=True)
    assert [key for key, _t, _o in open_work] == ["a.count", "b.save"]


async def test_save_refuses_unknown_keys_and_wrong_placeholders(
    audits: list[dict[str, Any]],
) -> None:
    session = _Session()
    service = TranslationService(session)  # type: ignore[arg-type]
    with pytest.raises(ValidationProblem) as unknown:
        await service.save("en", {"z.nope": "x", "a.title": "T"}, actor="a")
    assert unknown.value.code == "unknown_key"
    with pytest.raises(ValidationProblem) as wrong:
        await service.save("en", {"a.count": "{n} items", "a.title": "T"}, actor="a")
    assert wrong.value.code == "placeholder_mismatch"
    assert [e.field for e in wrong.value.errors] == ["a.count"]  # type: ignore[union-attr]
    assert session.statements == [] and audits == [] and session.committed == 0


async def test_save_writes_clears_and_audits(audits: list[dict[str, Any]]) -> None:
    session = _Session(execute=[[], [], [("a.count", "{count} items")]])
    service = TranslationService(session)  # type: ignore[arg-type]
    out = await service.save(
        "en", {"a.count": "{count} items", "a.title": "  ", "b.save": None}, actor="a"
    )
    assert out == {"a.count": "{count} items"}
    delete_sql, insert_sql, _read = (str(s) for s in session.statements)
    assert delete_sql.upper().startswith("DELETE")
    assert "ON CONFLICT" in insert_sql.upper() or "INSERT" in insert_sql.upper()
    assert audits[0]["target_id"] == "en"
    assert audits[0]["data"] == {"set": 1, "cleared": 2, "keys": ["a.count", "a.title", "b.save"]}
    assert session.committed == 1


async def test_save_without_changes_writes_nothing(audits: list[dict[str, Any]]) -> None:
    session = _Session(execute=[[]])
    service = TranslationService(session)  # type: ignore[arg-type]
    assert await service.save("de", {}, actor="a") == {}
    assert audits == [] and len(session.statements) == 1


async def test_save_only_sets(audits: list[dict[str, Any]]) -> None:
    session = _Session(execute=[[], []])
    session.store["fr"] = _lang()
    service = TranslationService(session)  # type: ignore[arg-type]
    await service.save("fr", {"b.save": "Enregistrer"}, actor="a")
    assert "INSERT" in str(session.statements[0]).upper()
    assert audits[0]["data"]["set"] == 1 and audits[0]["data"]["cleared"] == 0


@pytest.mark.parametrize(
    ("requested", "locale", "chain"),
    [
        (None, "de", ["de"]),
        ("en", "en", ["en", "de"]),
        ("fr", "fr", ["fr", "en", "de"]),
        ("it", "de", ["de"]),
    ],
)
async def test_bundle_resolves_the_locale(
    audits: list[dict[str, Any]], requested: str | None, locale: str, chain: list[str]
) -> None:
    del audits
    session = _Session(scalars=[[_lang("fr")]])
    service = TranslationService(session)  # type: ignore[arg-type]
    got, active, overrides = await service.bundle(requested)
    assert got == locale
    assert [r.code for r in active] == ["fr"]
    assert list(overrides) == chain


def test_catalog_reads_the_configured_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "de.json").write_text(
        json.dumps({"z.last": "Ende", "a.first": "{n} von {total} {n}"}), "utf-8"
    )
    (tmp_path / "en.json").write_text(json.dumps({"a.first": "{n} of {total}"}), "utf-8")
    monkeypatch.setattr(
        catalog_mod, "get_settings", lambda: SimpleNamespace(ui_catalog_dir=str(tmp_path))
    )
    catalog_mod.builtin_texts.cache_clear()
    catalog_mod.catalog.cache_clear()
    try:
        assert catalog_mod.catalog_dir() == tmp_path
        assert catalog_mod.builtin_texts() == {
            "a.first": BuiltinText(de="{n} von {total} {n}", en="{n} of {total}"),
            "z.last": BuiltinText(de="Ende", en=None),
        }
        assert catalog_mod.catalog() == {"a.first": ("n", "total"), "z.last": ()}
    finally:
        catalog_mod.builtin_texts.cache_clear()
        catalog_mod.catalog.cache_clear()
    monkeypatch.setattr(catalog_mod, "get_settings", lambda: SimpleNamespace(ui_catalog_dir=None))
    assert catalog_mod.catalog_dir() == catalog_mod._REPO_DIR  # pyright: ignore[reportPrivateUsage]
