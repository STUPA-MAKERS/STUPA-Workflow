"""DB-lose Vollabdeckung für :mod:`app.modules.applications.service`.

Treibt jeden Service-Pfad über einen Ergebnis-Queue-Fake (FIFO je ``execute`` /
``scalars`` / ``scalar``; eigene Queue für ``get``), inkl. Fehlerpfade (404/409/422),
Guard-Branches (Edit-Lock, Bypass), PII-Anonymisierung, Filter-/Sortier-Kombinationen
in :meth:`list_applications` und :meth:`list_tasks` (vote- vs. manuelle-Übergang-Pfade).

Externe Service-Abhängigkeiten (FormsService, FlowService) und die Volltext-Helfer
(``dialect_of``/``trigram_rank``) werden gemonkeypatcht — kein Postgres/Redis/Netz.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

import app.modules.applications.service as svc_mod
from app.modules.applications.service import (
    ApplicationsService,
    _amount_currency,
    _field_from_row,
    _state_out,
    _title_of,
    _whitelist,
)
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# generische Fakes
# --------------------------------------------------------------------------- #
class _Obj:
    """Attribut-Container (leichter als SimpleNamespace für Tippzwecke)."""

    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)

    # Dynamischer ORM-Zeilen-Stub: jeder Attributzugriff/-zuweisung ist erlaubt.
    # Hält den Strict-Typecheck ruhig, ohne `Any`-Casts an jeder Zugriffsstelle.
    def __getattr__(self, name: str) -> Any:  # nur bei fehlendem Attribut
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        self.__dict__[name] = value


class _Result:
    """``Result``/``ScalarResult``-Ersatz."""

    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None

    def __iter__(self) -> Any:
        return iter(self._items)


class _Session:
    """``AsyncSession``-Stub mit getrennten FIFO-Queues je Zugriffsart.

    * ``get_results`` — Queue für ``session.get(Model, pk)`` (Default ``None``).
    * ``execute_results`` — Queue für ``session.execute`` (liefert ``_Result``).
    * ``scalars_results`` — Queue für ``session.scalars`` (liefert ``_Result``).
    * ``scalar_results`` — Queue für ``session.scalar`` (Default ``None``).
    """

    def __init__(
        self,
        *,
        get_results: list[Any] | None = None,
        execute_results: list[list[Any]] | None = None,
        scalars_results: list[list[Any]] | None = None,
        scalar_results: list[Any] | None = None,
    ) -> None:
        self.get_results = list(get_results or [])
        self.execute_results = list(execute_results or [])
        self.scalars_results = list(scalars_results or [])
        self.scalar_results = list(scalar_results or [])
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.statements: list[Any] = []
        self.committed = 0
        self.rolled_back = 0
        self.flushed = 0
        self.refreshed = 0
        self.commit_raises: Exception | None = None
        self.bind = None

    async def get(self, _model: type, _pk: Any) -> Any:
        return self.get_results.pop(0) if self.get_results else None

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        rows = self.execute_results.pop(0) if self.execute_results else []
        return _Result(rows)

    async def scalars(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        rows = self.scalars_results.pop(0) if self.scalars_results else []
        return _Result(rows)

    async def scalar(self, stmt: Any) -> Any:
        self.statements.append(stmt)
        return self.scalar_results.pop(0) if self.scalar_results else None

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        # ``at`` ist DB-server_default → bei einem frischen ORM-Objekt None; der
        # Service serialisiert es direkt nach commit() (ohne refresh) → hier setzen.
        if hasattr(obj, "at") and getattr(obj, "at", None) is None:
            obj.at = NOW

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flushed += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()

    async def commit(self) -> None:
        if self.commit_raises is not None:
            raise self.commit_raises
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1

    async def refresh(self, _obj: Any) -> None:
        self.refreshed += 1


def _ff(key: str, **over: Any) -> FormFieldDef:
    base: dict[str, Any] = {"key": key, "type": "text", "label": {"de": key}}
    base.update(over)
    return FormFieldDef.model_validate(base)


def _app(**over: Any) -> _Obj:
    base: dict[str, Any] = {
        "id": uuid4(),
        "type_id": uuid4(),
        "form_version_id": uuid4(),
        "flow_version_id": uuid4(),
        "current_state_id": uuid4(),
        "gremium_id": uuid4(),
        "budget_pot_id": None,
        "budget_id": None,
        "fiscal_year_id": None,
        "amount": None,
        "currency": None,
        "data": {"title": "Antrag"},
        "lang": "de",
        "created_by": None,
        "email_confirmed_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(over)
    return _Obj(**base)


def _state(**over: Any) -> _Obj:
    base: dict[str, Any] = {
        "id": uuid4(),
        "key": "draft",
        "label_i18n": {"de": "Entwurf"},
        "color": "#abc",
        "edit_allowed": True,
        "kind": "normal",
        "config": {},
    }
    base.update(over)
    return _Obj(**base)


# --------------------------------------------------------------------------- #
# Modul-Helfer
# --------------------------------------------------------------------------- #
def test_field_from_row_maps_all_columns() -> None:
    row = _Obj(
        key="cost",
        type="currency",
        label_i18n={"de": "Kosten"},
        help_i18n={"de": "Hilfe"},
        required=True,
        validation={"min": 1},
        visible_if=None,
        compute=None,
        options=None,
        is_pii=True,
        is_promoted=True,
        promote_target="amount",
    )
    field = _field_from_row(row)
    assert field.key == "cost"
    assert field.is_pii is True
    assert field.promote_target == "amount"


def test_field_from_row_validation_falsy_becomes_none() -> None:
    """``validation`` mit Falsy-Wert (``{}``) → ``None`` (or-Kurzschluss)."""
    row = _Obj(
        key="x", type="text", label_i18n={"de": "x"}, help_i18n=None,
        required=False, validation={}, visible_if=None, compute=None,
        options=None, is_pii=False, is_promoted=False, promote_target=None,
    )
    field = _field_from_row(row)
    assert field.validation is None


def test_title_of_variants() -> None:
    assert _title_of(None) is None
    assert _title_of({}) is None
    assert _title_of({"title": "  "}) is None
    assert _title_of({"title": 123}) is None
    assert _title_of({"title": "  Hallo  "}) == "Hallo"


def test_amount_currency_decimal_passthrough() -> None:
    fields = [_ff("cost", type="currency", isPromoted=True, promoteTarget="amount")]
    amount, currency = _amount_currency(fields, {"cost": Decimal("5")})
    assert amount == Decimal("5")
    assert currency == "EUR"


def test_state_out_color_override_empty_string_kept() -> None:
    """color_override='' (nicht None) wird übernommen, nicht der Fallback."""
    state = _state(color="#stored")
    out = _state_out(state, "")  # type: ignore[arg-type]
    assert out is not None
    assert out.color == ""


def test_state_out_none_returns_none() -> None:
    assert _state_out(None) is None


def test_whitelist_keeps_known_drops_unknown() -> None:
    fields = [_ff("title"), _ff("note")]
    assert _whitelist(fields, {"title": "t", "junk": 1, "note": "n"}) == {
        "title": "t",
        "note": "n",
    }


# --------------------------------------------------------------------------- #
# _get_app / get
# --------------------------------------------------------------------------- #
async def test_get_app_missing_404() -> None:
    svc = ApplicationsService(_Session(get_results=[None]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc._get_app(uuid4())


async def test_get_with_pii_owner_and_applicant() -> None:
    state = _state()
    app = _app(created_by="user-1", current_state_id=state.id)
    applicant = _Obj(email="a@b.de", name="Alice", anonymized_at=None)
    session = _Session(
        get_results=[app, state],
        # _to_out: zuerst applicant-Query, dann _resolve_state_colors (gecached).
        execute_results=[[applicant], [("draft", "#zzz")]],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.get(app.id, include_pii=True, requester_sub="user-1")
    assert out.is_owner is True
    assert out.can_edit is True
    assert out.applicant is not None
    assert out.applicant.email == "a@b.de"
    assert out.version == 0  # scalar() default None → 0


async def test_get_without_pii_and_can_manage() -> None:
    state = _state()
    app = _app(created_by="someone-else", current_state_id=state.id)
    session = _Session(
        get_results=[app, state],
        execute_results=[[("draft", "#zzz")]],
        scalar_results=[3],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.get(
        app.id, include_pii=False, requester_sub="other", requester_can_manage=True
    )
    assert out.is_owner is False
    assert out.can_edit is True  # manage
    assert out.applicant is None
    assert out.version == 3


async def test_get_include_pii_but_no_applicant_row() -> None:
    state = _state()
    app = _app(current_state_id=state.id)
    session = _Session(
        get_results=[app, state],
        execute_results=[[], [("draft", "#zzz")]],  # leeres applicant-Result, dann Farben
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.get(app.id, include_pii=True)
    assert out.applicant is None


async def test_get_state_none_when_no_current_state() -> None:
    app = _app(current_state_id=None)
    session = _Session(get_results=[app], execute_results=[[]])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.get(app.id, include_pii=False)
    assert out.state is None


# --------------------------------------------------------------------------- #
# _resolve_state_colors (Cache) / _state_out_resolved
# --------------------------------------------------------------------------- #
async def test_resolve_state_colors_caches_result() -> None:
    session = _Session(execute_results=[[("approved", "#0f0"), ("draft", None)]])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    first = await svc._resolve_state_colors()
    assert first == {"approved": "#0f0"}  # None gefiltert
    # zweiter Aufruf → Cache, KEIN weiteres execute
    second = await svc._resolve_state_colors()
    assert second is first
    assert len(session.statements) == 1


async def test_state_out_resolved_none() -> None:
    svc = ApplicationsService(_Session())  # type: ignore[arg-type]
    assert await svc._state_out_resolved(None) is None


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #
def _payload(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "type_id": uuid4(),
        "budget_pot_id": None,
        "data": {"title": "Mein Antrag", "cost": "10"},
        "applicant_email": "a@b.de",
        "applicant_name": "Alice",
        "lang": "de",
    }
    base.update(over)
    return SimpleNamespace(**base)


def _effective(fields: list[FormFieldDef], fv_id: UUID) -> Any:
    section = SimpleNamespace(fields=fields)
    return SimpleNamespace(sections=[section], form_version_id=fv_id)


class _FakeForms:
    """FormsService-Ersatz, der eine vordefinierte effektive Form liefert."""

    effective: Any = None

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_effective_form(
        self, _type_id: Any, _pot_id: Any = None, *, form_version_id: Any = None
    ) -> Any:
        return _FakeForms.effective


class _FakeFlow:
    scheduled: list[tuple[Any, Any]] = []
    available: list[Any] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def schedule_state_deadline(self, app: Any, state: Any) -> None:
        _FakeFlow.scheduled.append((app, state))

    async def available_transitions(
        self, _app_id: Any, _principal: Any, *, deadline_passed: Any = None
    ) -> list[Any]:
        return _FakeFlow.available


@pytest.fixture(autouse=True)
def _reset_flow() -> None:
    _FakeFlow.scheduled = []
    _FakeFlow.available = []
    _FakeForms.effective = None


@pytest.fixture
def _patch_forms(monkeypatch: pytest.MonkeyPatch) -> type[_FakeForms]:
    monkeypatch.setattr(svc_mod, "FormsService", _FakeForms)
    return _FakeForms


@pytest.fixture
def _patch_flow(monkeypatch: pytest.MonkeyPatch) -> type[_FakeFlow]:
    monkeypatch.setattr("app.modules.flow.service.FlowService", _FakeFlow)
    return _FakeFlow


async def test_create_unknown_type_404() -> None:
    session = _Session(get_results=[None])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError, match="application type"):
        await svc.create(_payload())  # type: ignore[arg-type]


async def test_create_no_active_flow_404(_patch_forms: type[_FakeForms]) -> None:
    app_type = _Obj(id=uuid4(), has_budget=False, gremium_id=uuid4())
    session = _Session(get_results=[app_type], execute_results=[[]])  # kein aktiver Flow
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError, match="no active global flow"):
        await svc.create(_payload())  # type: ignore[arg-type]


async def test_create_validation_error_422(_patch_forms: type[_FakeForms]) -> None:
    app_type = _Obj(id=uuid4(), has_budget=False, gremium_id=uuid4())
    fv_id = uuid4()
    # Pflichtfeld 'title' fehlt im Payload-data → AnswerValidationError → 422.
    _FakeForms.effective = _effective(
        [_ff("title", required=True)], fv_id
    )
    session = _Session(
        get_results=[app_type],
        execute_results=[[fv_id]],  # _resolve_flow_version_id
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    with pytest.raises(ValidationProblem):
        await svc.create(_payload(data={"cost": "10"}))  # type: ignore[arg-type]


async def test_create_no_initial_state_404(
    _patch_forms: type[_FakeForms],
) -> None:
    app_type = _Obj(id=uuid4(), has_budget=False, gremium_id=uuid4())
    fv_id = uuid4()
    _FakeForms.effective = _effective([_ff("title", required=True)], fv_id)
    session = _Session(
        get_results=[app_type],
        execute_results=[[fv_id], []],  # flow ok, aber kein initial state
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError, match="initial state"):
        await svc.create(_payload(data={"title": "T"}))  # type: ignore[arg-type]


async def test_create_anonymous_ok(
    _patch_forms: type[_FakeForms], _patch_flow: type[_FakeFlow]
) -> None:
    app_type = _Obj(id=uuid4(), has_budget=True, gremium_id=uuid4())
    fv_id = uuid4()
    initial = _state(is_initial=True)
    _FakeForms.effective = _effective(
        [
            _ff("title", required=True),
            _ff("cost", type="currency", isPromoted=True, promoteTarget="amount"),
        ],
        fv_id,
    )
    session = _Session(
        get_results=[app_type],
        execute_results=[[fv_id], [initial]],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    app, email = await svc.create(
        _payload(data={"title": "T", "cost": "12.50", "junk": "x"})  # type: ignore[arg-type]
    )
    assert email == "a@b.de"
    assert app.amount == Decimal("12.50")
    assert app.currency == "EUR"
    assert "junk" not in app.data  # whitelist
    assert app.created_by is None  # anonym
    assert app.email_confirmed_at is None  # Gast unbestätigt
    assert session.committed == 1
    # Applicant + SubmissionVersion + StatusEvent + Application
    kinds = {type(o).__name__ for o in session.added}
    assert {"Application", "Applicant", "SubmissionVersion", "StatusEvent"} <= kinds
    assert _FakeFlow.scheduled  # Frist materialisiert


async def test_create_logged_in_actor_confirms_immediately(
    _patch_forms: type[_FakeForms], _patch_flow: type[_FakeFlow]
) -> None:
    app_type = _Obj(id=uuid4(), has_budget=False, gremium_id=uuid4())
    fv_id = uuid4()
    initial = _state(is_initial=True)
    _FakeForms.effective = _effective([_ff("title", required=True)], fv_id)
    session = _Session(
        get_results=[app_type],
        execute_results=[[fv_id], [initial]],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    app, _ = await svc.create(
        _payload(data={"title": "T"}), actor="principal-sub-1"  # type: ignore[arg-type]
    )
    assert app.created_by == "principal-sub-1"
    assert app.email_confirmed_at is not None


# --------------------------------------------------------------------------- #
# effective_form
# --------------------------------------------------------------------------- #
async def test_effective_form_delegates_with_pinned_version(
    _patch_forms: type[_FakeForms],
) -> None:
    app = _app()
    _FakeForms.effective = _effective([_ff("title")], app.form_version_id)
    session = _Session(get_results=[app])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.effective_form(app.id)
    assert out is _FakeForms.effective


# --------------------------------------------------------------------------- #
# patch
# --------------------------------------------------------------------------- #
def _patch_pinned(monkeypatch: pytest.MonkeyPatch, fields: list[FormFieldDef]) -> None:
    async def _fake_pinned(self: Any, app: Any) -> list[FormFieldDef]:
        return list(fields)

    monkeypatch.setattr(ApplicationsService, "_pinned_fields", _fake_pinned)


async def test_patch_missing_404() -> None:
    svc = ApplicationsService(_Session(get_results=[None]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.patch(uuid4(), {}, changed_by="x")


async def test_patch_locked_state_409(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(data={"title": "x"})
    locked = _state(edit_allowed=False)
    svc = ApplicationsService(_Session(get_results=[app, locked]))  # type: ignore[arg-type]
    with pytest.raises(ConflictError, match="locked"):
        await svc.patch(app.id, {"title": "y"}, changed_by="x")


async def test_patch_locked_state_bypass_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(data={"title": "old"})
    locked = _state(edit_allowed=False)
    app_type = _Obj(id=app.type_id, has_budget=False)
    _patch_pinned(monkeypatch, [_ff("title", required=True)])
    session = _Session(
        get_results=[app, locked, app_type],
        execute_results=[[("draft", "#z")]],  # _resolve_state_colors in _to_out
        scalar_results=[2, None],  # _current_version (patch) then _to_out version
    )
    # _to_out needs a state get → also re-get current state
    session.get_results.append(locked)
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.patch(
        app.id, {"title": "new"}, changed_by="u", bypass_state_lock=True
    )
    assert out.data == {"title": "new"}
    assert session.committed == 1
    assert any(type(o).__name__ == "SubmissionVersion" for o in session.added)


async def test_patch_validation_error_422(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(data={"title": "x"})
    state = _state(edit_allowed=True)
    app_type = _Obj(id=app.type_id, has_budget=False)
    _patch_pinned(monkeypatch, [_ff("title", required=True)])
    session = _Session(get_results=[app, state, app_type])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    with pytest.raises(ValidationProblem):
        await svc.patch(app.id, {"other": "v"}, changed_by="u")  # title fehlt
    assert session.committed == 0


async def test_patch_adds_system_title_field_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_pinned_fields`` ohne 'title' → System-Titelfeld wird vorangestellt."""
    app = _app(data={"title": "old", "note": "a"})
    state = _state(edit_allowed=True)
    app_type = _Obj(id=app.type_id, has_budget=False)
    _patch_pinned(monkeypatch, [_ff("note")])  # KEIN title
    session = _Session(
        get_results=[app, state, app_type, state],
        execute_results=[[("draft", "#z")]],
        scalar_results=[1, None],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.patch(app.id, {"title": "new", "note": "b"}, changed_by="u")
    assert out.data == {"title": "new", "note": "b"}  # title NICHT verworfen


async def test_patch_empty_diff_stores_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keine Datenänderung → ``diff=None`` in der neuen Version."""
    app = _app(data={"title": "same"})
    state = _state(edit_allowed=True)
    app_type = _Obj(id=app.type_id, has_budget=False)
    _patch_pinned(monkeypatch, [_ff("title", required=True)])
    session = _Session(
        get_results=[app, state, app_type, state],
        execute_results=[[("draft", "#z")]],
        scalar_results=[0, None],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    await svc.patch(app.id, {"title": "same"}, changed_by="u")
    version = next(o for o in session.added if type(o).__name__ == "SubmissionVersion")
    assert version.diff is None


async def test_patch_app_type_missing_uses_false_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``app_type`` None → has_budget-Kontext fällt auf False zurück."""
    app = _app(data={"title": "x"})
    state = _state(edit_allowed=True)
    _patch_pinned(monkeypatch, [_ff("title", required=True)])
    session = _Session(
        get_results=[app, state, None, state],  # 3. get = app_type → None
        execute_results=[[("draft", "#z")]],
        scalar_results=[0, None],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.patch(app.id, {"title": "y"}, changed_by="u")
    assert out.data == {"title": "y"}


async def test_patch_concurrent_integrity_error_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import IntegrityError

    app = _app(data={"title": "x"})
    state = _state(edit_allowed=True)
    app_type = _Obj(id=app.type_id, has_budget=False)
    _patch_pinned(monkeypatch, [_ff("title", required=True)])
    session = _Session(get_results=[app, state, app_type], scalar_results=[0])
    session.commit_raises = IntegrityError("stmt", {}, Exception("dup"))
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    with pytest.raises(ConflictError, match="Concurrent"):
        await svc.patch(app.id, {"title": "y"}, changed_by="u")
    assert session.rolled_back == 1


# --------------------------------------------------------------------------- #
# delete
# --------------------------------------------------------------------------- #
async def test_delete_removes_and_commits() -> None:
    app = _app()
    session = _Session(get_results=[app])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    await svc.delete(app.id)
    assert app in session.deleted
    assert session.committed == 1


async def test_delete_missing_404() -> None:
    svc = ApplicationsService(_Session(get_results=[None]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.delete(uuid4())


# --------------------------------------------------------------------------- #
# timeline
# --------------------------------------------------------------------------- #
async def test_timeline_resolves_actor_names_and_states() -> None:
    app = _app()
    to_state = _state(key="approved")
    ev1 = _Obj(
        from_state_id=None, to_state_id=to_state.id, actor="sub-1", at=NOW, note="hi"
    )
    ev2 = _Obj(
        from_state_id=to_state.id, to_state_id=to_state.id, actor=None, at=NOW, note=None
    )
    session = _Session(
        get_results=[app, to_state, to_state],
        execute_results=[
            [("sub-1", "Alice", None)],  # _author_names
            [("approved", "#0f0")],  # _resolve_state_colors (gecached danach)
        ],
        scalars_results=[[ev1, ev2]],  # timeline events
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.timeline(app.id)
    assert len(out) == 2
    assert out[0].actor == "Alice"  # aufgelöst
    assert out[1].actor is None  # kein Akteur


async def test_timeline_missing_404() -> None:
    svc = ApplicationsService(_Session(get_results=[None]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.timeline(uuid4())


# --------------------------------------------------------------------------- #
# versions
# --------------------------------------------------------------------------- #
async def test_versions_resolves_names() -> None:
    app = _app()
    v1 = _Obj(version=1, data={"title": "a"}, diff=None, changed_by="sub-1", at=NOW)
    v2 = _Obj(version=2, data={"title": "b"}, diff=None, changed_by=None, at=NOW)
    session = _Session(
        get_results=[app],
        execute_results=[[("sub-1", None, "alice@x.de")]],  # _author_names: dn None → email
        scalars_results=[[v1, v2]],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.versions(app.id)
    assert out[0].changed_by == "alice@x.de"
    assert out[1].changed_by is None


async def test_versions_missing_404() -> None:
    svc = ApplicationsService(_Session(get_results=[None]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.versions(uuid4())


# --------------------------------------------------------------------------- #
# _pinned_fields / _pii_keys_for_type (echte Implementierung)
# --------------------------------------------------------------------------- #
async def test_pinned_fields_with_budget_pot() -> None:
    app = _app(budget_pot_id=uuid4())
    row = _Obj(
        key="title", type="text", label_i18n={"de": "t"}, help_i18n=None,
        required=True, validation=None, visible_if=None, compute=None,
        options=None, is_pii=False, is_promoted=False, promote_target=None,
    )
    pot_field = _Obj(field={"key": "pot_field", "type": "text", "label": {"de": "p"}})
    session = _Session(scalars_results=[[row], [pot_field]])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    fields = await svc._pinned_fields(app)  # type: ignore[arg-type]
    keys = {f.key for f in fields}
    assert keys == {"title", "pot_field"}


async def test_pinned_fields_no_pot() -> None:
    app = _app(budget_pot_id=None)
    row = _Obj(
        key="title", type="text", label_i18n={"de": "t"}, help_i18n=None,
        required=True, validation=None, visible_if=None, compute=None,
        options=None, is_pii=False, is_promoted=False, promote_target=None,
    )
    session = _Session(scalars_results=[[row]])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    fields = await svc._pinned_fields(app)  # type: ignore[arg-type]
    assert {f.key for f in fields} == {"title"}


async def test_pii_keys_for_type() -> None:
    session = _Session(scalars_results=[["email", "name"]])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    keys = await svc._pii_keys_for_type(uuid4())
    assert keys == {"email", "name"}


# --------------------------------------------------------------------------- #
# list_applications
# --------------------------------------------------------------------------- #
@pytest.fixture
def _patch_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc_mod, "dialect_of", lambda _s: "postgresql")

    def _rank(q: str, cols: list[Any], *, dialect: str = "postgresql") -> Any:
        from sqlalchemy import literal
        return literal(True), literal(1)

    monkeypatch.setattr(svc_mod, "trigram_rank", _rank)


async def test_list_applications_no_filters_default_sort() -> None:
    app = _app()
    state = _state()
    session = _Session(
        get_results=[state],
        execute_results=[[("draft", "#z")]],
        scalars_results=[[app]],
        scalar_results=[1],  # total
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    page = await svc.list_applications(limit=20, offset=0)
    assert page.total == 1
    assert len(page.items) == 1
    assert page.items[0].title == "Antrag"


async def test_list_applications_all_filters_postgres_search(
    _patch_search: None,
) -> None:
    app = _app(budget_id=uuid4())
    state = _state()
    node_path = "VS-800"
    session = _Session(
        get_results=[state],
        execute_results=[[("draft", "#z")]],
        scalars_results=[[app]],
        scalar_results=[node_path, 1],  # budget path_key lookup, then total
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    page = await svc.list_applications(
        state_id=uuid4(),
        gremium_id=uuid4(),
        type_id=uuid4(),
        budget_pot_id=uuid4(),
        budget_id=uuid4(),
        q="suche",
        amount_min=Decimal("1"),
        amount_max=Decimal("99"),
        created_from=date(2026, 1, 1),
        created_to=date(2026, 12, 31),
        sort="amount",
        order="asc",
        owner_sub="me",
        limit=10,
        offset=5,
    )
    assert page.total == 1
    assert page.offset == 5


async def test_list_applications_unknown_budget_yields_empty() -> None:
    session = _Session(
        scalar_results=[None, 0],  # budget path_key None → false() filter, total 0
        scalars_results=[[]],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    page = await svc.list_applications(budget_id=uuid4(), limit=10, offset=0)
    assert page.total == 0
    assert page.items == []


async def test_list_applications_blank_q_skips_search() -> None:
    """q='   ' (nur Whitespace) → kein Trigram-Pfad."""
    session = _Session(scalar_results=[0], scalars_results=[[]])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    page = await svc.list_applications(q="   ", limit=10, offset=0)
    assert page.total == 0


async def test_list_applications_sqlite_search_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc_mod, "dialect_of", lambda _s: "sqlite")

    def _rank(q: str, cols: list[Any], *, dialect: str = "postgresql") -> Any:
        from sqlalchemy import literal
        return literal(True), literal(1)

    monkeypatch.setattr(svc_mod, "trigram_rank", _rank)
    session = _Session(scalar_results=[0], scalars_results=[[]])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    page = await svc.list_applications(q="foo", limit=10, offset=0)
    assert page.total == 0


async def test_list_applications_total_none_becomes_zero() -> None:
    session = _Session(scalar_results=[None], scalars_results=[[]])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    page = await svc.list_applications(limit=10, offset=0)
    assert page.total == 0


# --------------------------------------------------------------------------- #
# name_maps
# --------------------------------------------------------------------------- #
async def test_name_maps_locale_fallbacks() -> None:
    tid1, tid2, tid3 = uuid4(), uuid4(), uuid4()
    gid = uuid4()
    session = _Session(
        execute_results=[
            [
                (tid1, {"de": "DE", "en": "EN"}),  # locale en wanted
                (tid2, {"de": "NurDE"}),  # fällt auf de zurück
                (tid3, None),  # None → "" (über {} fallbacks)
            ],
            [(gid, "Gremium A")],
        ]
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    types, gremien = await svc.name_maps(locale="en")
    assert types[tid1] == "EN"
    assert types[tid2] == "NurDE"
    assert types[tid3] == ""
    assert gremien[gid] == "Gremium A"


async def test_name_maps_en_missing_falls_to_de() -> None:
    tid = uuid4()
    session = _Session(execute_results=[[(tid, {"de": "X"})], []])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    types, _ = await svc.name_maps(locale="en")
    assert types[tid] == "X"


# --------------------------------------------------------------------------- #
# _in_gremium
# --------------------------------------------------------------------------- #
async def test_in_gremium_true() -> None:
    session = _Session(scalar_results=[uuid4()])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    assert await svc._in_gremium("sub", uuid4()) is True


async def test_in_gremium_false() -> None:
    session = _Session(scalar_results=[None])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    assert await svc._in_gremium("sub", uuid4()) is False


# --------------------------------------------------------------------------- #
# list_tasks
# --------------------------------------------------------------------------- #
def _principal(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "sub": "me",
        "roles": [],
        "groups": set(),
    }
    base.update(over)
    ns = SimpleNamespace(**base)
    perms: set[str] = over.get("_perms", set())
    ns.has = lambda p, _perms=perms: p in _perms  # type: ignore[attr-defined]
    return ns


async def test_list_tasks_no_apps_returns_empty(_patch_flow: type[_FakeFlow]) -> None:
    session = _Session(scalars_results=[[]])  # keine Anträge
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.list_tasks(_principal(roles=["admin"]))
    assert out == []


async def test_list_tasks_vote_state_admin(_patch_flow: type[_FakeFlow]) -> None:
    app = _app(current_state_id=uuid4())
    vote_state = _state(kind="vote")
    vote_state.id = app.current_state_id
    session = _Session(
        execute_results=[[("draft", "#z")]],  # _resolve_state_colors
        scalars_results=[[app], [vote_state]],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.list_tasks(_principal(roles=["admin"]))
    assert len(out) == 1


async def test_list_tasks_vote_state_member_in_gremium(
    _patch_flow: type[_FakeFlow],
) -> None:
    gid = uuid4()
    app = _app(current_state_id=uuid4())
    vote_state = _state(kind="vote", config={"gremiumId": str(gid)})
    vote_state.id = app.current_state_id
    session = _Session(
        execute_results=[[("draft", "#z")]],
        scalars_results=[[app], [vote_state]],
        scalar_results=[uuid4()],  # _in_gremium → membership row exists
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.list_tasks(_principal(_perms={"vote.cast"}))
    assert len(out) == 1


async def test_list_tasks_vote_state_member_not_in_gremium_no_transition(
    _patch_flow: type[_FakeFlow],
) -> None:
    gid = uuid4()
    app = _app(current_state_id=uuid4(), created_by="someone")
    vote_state = _state(kind="vote", config={"gremiumId": str(gid)})
    vote_state.id = app.current_state_id
    _FakeFlow.available = []  # keine manuellen Übergänge
    session = _Session(
        execute_results=[[("draft", "#z")]],
        scalars_results=[[app], [vote_state]],
        scalar_results=[None],  # nicht im Gremium
    )
    # principal darf transition → geht in den manuellen Pfad, available leer → kein Task
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.list_tasks(_principal(_perms={"application.transition"}))
    assert out == []


async def test_list_tasks_vote_state_invalid_gremium_config(
    _patch_flow: type[_FakeFlow],
) -> None:
    """config ohne/leeres gremiumId → ok bleibt False (Vote-Pfad), kein _in_gremium."""
    app = _app(current_state_id=uuid4(), created_by="other")
    vote_state = _state(kind="vote", config={"gremiumId": ""})
    vote_state.id = app.current_state_id
    _FakeFlow.available = []
    session = _Session(
        execute_results=[[("draft", "#z")]],
        scalars_results=[[app], [vote_state]],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.list_tasks(_principal(_perms=set()))  # kein transition, nicht owner
    assert out == []


async def test_list_tasks_manual_transition_requires_action(
    _patch_flow: type[_FakeFlow],
) -> None:
    app = _app(current_state_id=uuid4())
    normal = _state(kind="normal")
    normal.id = app.current_state_id
    _FakeFlow.available = [
        _Obj(requires_action=False),
        _Obj(requires_action=True),
    ]
    session = _Session(
        execute_results=[[("draft", "#z")]],
        scalars_results=[[app], [normal]],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.list_tasks(_principal(_perms={"application.transition"}))
    assert len(out) == 1


async def test_list_tasks_owner_only_no_perm(_patch_flow: type[_FakeFlow]) -> None:
    """Kein transition-Recht, aber Ersteller:in → manueller Pfad greift."""
    app = _app(current_state_id=uuid4(), created_by="me")
    normal = _state(kind="normal")
    normal.id = app.current_state_id
    _FakeFlow.available = [_Obj(requires_action=True)]
    session = _Session(
        execute_results=[[("draft", "#z")]],
        scalars_results=[[app], [normal]],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.list_tasks(_principal(sub="me", _perms=set()))
    assert len(out) == 1


async def test_list_tasks_state_missing_in_map_skipped(
    _patch_flow: type[_FakeFlow],
) -> None:
    """Antrag verweist auf State, der nicht im by_id-Map ist → übersprungen."""
    app = _app(current_state_id=uuid4())
    other_state = _state()  # andere id
    session = _Session(scalars_results=[[app], [other_state]])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.list_tasks(_principal(roles=["admin"]))
    assert out == []


async def test_list_tasks_current_state_none_skipped(
    _patch_flow: type[_FakeFlow],
) -> None:
    """current_state_id None (Defensive im Loop) → übersprungen.

    Die Query filtert ``is_not(None)``, der Fake liefert dennoch einen Antrag mit
    ``current_state_id=None`` → der Loop-Guard greift."""
    app = _app(current_state_id=None)
    session = _Session(scalars_results=[[app], []])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.list_tasks(_principal(roles=["admin"]))
    assert out == []


# --------------------------------------------------------------------------- #
# _author_names
# --------------------------------------------------------------------------- #
async def test_author_names_empty_set_short_circuits() -> None:
    session = _Session()
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    assert await svc._author_names(set()) == {}
    assert session.statements == []  # kein Query


async def test_author_names_resolves_display_then_email_then_sub() -> None:
    session = _Session(
        execute_results=[
            [
                ("s1", "Display", "e1@x.de"),  # display_name
                ("s2", None, "e2@x.de"),  # email
                ("s3", None, None),  # sub
            ]
        ]
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    names = await svc._author_names({"s1", "s2", "s3", ""})
    assert names == {"s1": "Display", "s2": "e2@x.de", "s3": "s3"}


# --------------------------------------------------------------------------- #
# add_comment / list_comments
# --------------------------------------------------------------------------- #
async def test_add_comment_with_author() -> None:
    app = _app()
    session = _Session(
        get_results=[app],
        execute_results=[[("sub-1", "Alice", None)]],  # _author_names
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.add_comment(
        app.id, author="sub-1", author_kind="principal", body="hi", visibility="public"
    )
    assert out.author == "Alice"
    assert out.body == "hi"
    assert session.committed == 1


async def test_add_comment_anonymous_author_none() -> None:
    app = _app()
    session = _Session(get_results=[app], execute_results=[[]])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.add_comment(
        app.id, author=None, author_kind="applicant", body="hi", visibility="public"
    )
    assert out.author is None


async def test_add_comment_missing_app_404() -> None:
    svc = ApplicationsService(_Session(get_results=[None]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.add_comment(
            uuid4(), author=None, author_kind="applicant", body="x", visibility="public"
        )


async def test_list_comments_include_internal() -> None:
    app = _app()
    c1 = _Obj(
        id=uuid4(), author="sub-1", author_kind="principal", body="intern",
        visibility="internal", at=NOW,
    )
    c2 = _Obj(
        id=uuid4(), author=None, author_kind="applicant", body="öffentlich",
        visibility="public", at=NOW,
    )
    session = _Session(
        get_results=[app],
        execute_results=[[("sub-1", "Alice", None)]],
        scalars_results=[[c1, c2]],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.list_comments(app.id, include_internal=True)
    assert len(out) == 2
    assert out[0].author == "Alice"
    assert out[1].author is None


async def test_list_comments_public_only() -> None:
    app = _app()
    c = _Obj(
        id=uuid4(), author="sub-1", author_kind="principal", body="x",
        visibility="public", at=NOW,
    )
    session = _Session(
        get_results=[app],
        execute_results=[[("sub-1", "A", None)]],
        scalars_results=[[c]],
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    out = await svc.list_comments(app.id, include_internal=False)
    assert len(out) == 1


async def test_list_comments_missing_404() -> None:
    svc = ApplicationsService(_Session(get_results=[None]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.list_comments(uuid4(), include_internal=False)


# --------------------------------------------------------------------------- #
# anonymize
# --------------------------------------------------------------------------- #
async def test_anonymize_full_with_files_service_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(data={"title": "T", "email": "secret@x.de", "note": "n"})
    applicant = _Obj(email="a@b.de", name="Alice", anonymized_at=None)
    v1 = _Obj(
        version=1,
        data={"title": "T", "email": "secret@x.de"},
        diff={"added": {"email": "secret@x.de", "title": "T"}, "removed": {}, "changed": {}},
    )
    _patch_pinned_keys(monkeypatch, [_ff("email", isPII=True), _ff("note")])

    session = _Session(
        get_results=[app],
        execute_results=[
            [applicant],  # select applicant
        ],
        scalars_results=[
            ["email"],  # _pii_keys_for_type
            [v1],  # submission versions
        ],
    )

    files_calls: list[Any] = []

    class _Files:
        async def delete_for_application(self, app_id: Any, *, actor: str) -> None:
            files_calls.append((app_id, actor))

    svc = ApplicationsService(session)  # type: ignore[arg-type]
    await svc.anonymize(app.id, files=_Files(), actor="admin")  # type: ignore[arg-type]

    assert applicant.email is None
    assert applicant.name is None
    assert applicant.anonymized_at is not None
    assert "email" not in app.data  # PII-Schlüssel entfernt
    assert "email" not in v1.data
    assert "email" not in v1.diff["added"]
    assert files_calls == [(app.id, "admin")]
    assert session.committed == 1
    assert session.refreshed == 1


def _patch_pinned_keys(monkeypatch: pytest.MonkeyPatch, fields: list[FormFieldDef]) -> None:
    async def _fake(self: Any, app: Any) -> list[FormFieldDef]:
        return list(fields)

    monkeypatch.setattr(ApplicationsService, "_pinned_fields", _fake)


async def test_anonymize_no_applicant_no_pii_keys_no_files_no_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kein Applicant, keine PII-Keys, files=None, commit=False:

    deckt: applicant None, ``if pii_keys`` False, files-else (DB-Delete), flush-Zweig."""
    app = _app(data={"title": "T"})
    _patch_pinned_keys(monkeypatch, [_ff("title")])  # kein isPII
    session = _Session(
        get_results=[app],
        execute_results=[[]],  # applicant select → leer
        scalars_results=[[]],  # _pii_keys_for_type → leer
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    await svc.anonymize(app.id, files=None, commit=False)
    assert session.committed == 0
    assert session.flushed == 1
    # data unverändert (keine PII-Keys)
    assert app.data == {"title": "T"}


async def test_anonymize_version_without_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PII-Keys vorhanden, aber eine Version hat ``diff=None`` → diff-Scrub übersprungen."""
    app = _app(data={"title": "T", "email": "x@y.de"})
    v1 = _Obj(version=1, data={"email": "x@y.de"}, diff=None)
    _patch_pinned_keys(monkeypatch, [_ff("email", isPII=True)])
    session = _Session(
        get_results=[app],
        execute_results=[[]],  # kein applicant
        scalars_results=[[], [v1]],  # pii_keys_for_type empty, but pinned has email
    )
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    await svc.anonymize(app.id, files=None, commit=True)
    assert "email" not in v1.data
    assert v1.diff is None
    assert session.committed == 1


async def test_anonymize_missing_app_404() -> None:
    svc = ApplicationsService(_Session(get_results=[None]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.anonymize(uuid4())


# --------------------------------------------------------------------------- #
# _current_version (max None → 0)
# --------------------------------------------------------------------------- #
async def test_current_version_default_zero() -> None:
    session = _Session(scalar_results=[None])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    assert await svc._current_version(uuid4()) == 0


async def test_current_version_value() -> None:
    session = _Session(scalar_results=[5])
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    assert await svc._current_version(uuid4()) == 5
