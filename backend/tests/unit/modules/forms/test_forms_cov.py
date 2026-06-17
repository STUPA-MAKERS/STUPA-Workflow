"""Erschöpfende Unit-Coverage für ``app.modules.forms.service`` und
``app.modules.forms.validation`` (ohne DB/Docker/Netz).

Der Service wird gegen einen leichtgewichtigen ``AsyncSession``-Fake gefahren, der
``scalars``/``scalar`` aus einer Ergebnis-Queue zieht (wie ``auth_fakes``) und beim
``flush`` IDs vergibt (wie ``flow_fakes``) — beides wird hier gebraucht: das
``create_form_version`` nutzt ``version.id`` nach dem Flush.

Die reine Engine deckt vor allem die noch offenen ``positions``-/``positions_total``-
Zweige ab (leere/fehlerhafte Strukturen, fehlende bevorzugte Angebote).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

import pytest

from app.modules.admin.models import ApplicationType
from app.modules.budget.models import BudgetField, BudgetPot
from app.modules.forms.models import FormField, FormVersion
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import (
    FormsService,
    _field_def_to_row_kwargs,
    _row_to_field_def,
)
from app.modules.forms.validation import (
    FieldError,
    _offer_value,
    _split_sections,
    _validate_value,
    extract_promoted,
    positions_total,
)
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError, ValidationProblem


# --------------------------------------------------------------------------- #
# Fakes (nur in dieser Datei; tests/_support bleibt unangetastet)
# --------------------------------------------------------------------------- #
class _Result:
    """Minimaler ``Result``-Ersatz für ``scalars``/``scalar``."""

    def __init__(self, items: Iterable[Any] = ()) -> None:
        self._items = list(items)

    def all(self) -> list[Any]:
        return list(self._items)

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None


class _Session:
    """``AsyncSession``-Stub.

    * ``scalars``/``scalar`` ziehen aus ``_results`` (in Reihenfolge),
    * ``execute`` zählt Statements (UPDATE-Deaktivierung), liefert leeres Result,
    * ``get`` zieht aus ``_gets``,
    * ``flush`` vergibt IDs an frisch hinzugefügte Objekte (DB-Ersatz).
    """

    def __init__(
        self, results: Iterable[Any] = (), gets: Iterable[Any] = ()
    ) -> None:
        self._results = list(results)
        self._gets = list(gets)
        self.added: list[Any] = []
        self.statements: list[Any] = []
        self.flushed = 0
        self.committed = 0

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return _Result()

    async def scalars(self, _stmt: Any) -> _Result:
        return self._results.pop(0) if self._results else _Result()

    async def scalar(self, _stmt: Any) -> Any:
        return self._results.pop(0) if self._results else None

    async def get(self, _model: Any, _ident: Any) -> Any:
        return self._gets.pop(0) if self._gets else None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self) -> None:
        self.committed += 1


def _app_type(
    *,
    has_budget: bool = False,
    gremium_id: uuid.UUID | None = None,
    active_form_version_id: uuid.UUID | None = None,
) -> ApplicationType:
    at = ApplicationType()
    at.id = uuid.uuid4()
    at.has_budget = has_budget
    at.gremium_id = gremium_id
    at.active_form_version_id = active_form_version_id
    return at


def _form_version(
    *, version: int = 1, active: bool = True, description: dict | None = None
) -> FormVersion:
    fv = FormVersion(
        application_type_id=uuid.uuid4(),
        version=version,
        active=active,
        description_i18n=description,
    )
    fv.id = uuid.uuid4()
    return fv


def _form_field_row(
    key: str,
    type_: str,
    *,
    order: int = 0,
    label: dict | None = None,
    required: bool = False,
    validation: dict | None = None,
    options: list[dict] | None = None,
    visible_if: dict | None = None,
    compute: dict | None = None,
    is_promoted: bool = False,
    promote_target: str | None = None,
) -> FormField:
    return FormField(
        form_version_id=uuid.uuid4(),
        key=key,
        type=type_,
        label_i18n=label or {"de": key},
        help_i18n=None,
        required=required,
        validation=validation or {},
        visible_if=visible_if,
        compute=compute,
        options=options,
        order=order,
        is_pii=False,
        is_promoted=is_promoted,
        promote_target=promote_target,
    )


def _budget_field_row(field: dict, *, order: int = 0) -> BudgetField:
    bf = BudgetField(budget_pot_id=uuid.uuid4(), field=field, order=order)
    return bf


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# service: _row_to_field_def / _field_def_to_row_kwargs
# --------------------------------------------------------------------------- #
def test_row_to_field_def_roundtrip_with_validation_and_options() -> None:
    row = _form_field_row(
        "amount",
        "currency",
        required=True,
        validation={"min": 0},
        is_promoted=True,
        promote_target="amount",
    )
    fd = _row_to_field_def(row)
    assert fd.key == "amount"
    assert fd.type == "currency"
    assert fd.required is True
    assert fd.is_promoted is True
    assert fd.promote_target == "amount"
    assert fd.validation is not None and fd.validation.min == 0


def test_row_to_field_def_empty_validation_becomes_none() -> None:
    # `row.validation or None`: leeres dict {} ist falsy → None.
    row = _form_field_row("t", "text", validation={})
    fd = _row_to_field_def(row)
    assert fd.validation is None


def test_field_def_to_row_kwargs_validation_none_branch() -> None:
    # FormFieldDef ohne validation → kwargs.validation == {} (None-Zweig).
    field = FormFieldDef.model_validate({"key": "t", "type": "text", "label": {"de": "T"}})
    kw = _field_def_to_row_kwargs(field, 3)
    assert kw["validation"] == {}
    assert kw["options"] is None
    assert kw["order"] == 3


def test_field_def_to_row_kwargs_with_validation_and_options() -> None:
    field = FormFieldDef.model_validate(
        {
            "key": "s",
            "type": "select",
            "label": {"de": "S"},
            "validation": {"minLen": 1},
            "options": [{"value": "a", "label": {"de": "A"}}],
        }
    )
    kw = _field_def_to_row_kwargs(field, 0)
    assert kw["validation"] == {"minLen": 1}
    assert kw["options"] == [{"value": "a", "label": {"de": "A"}}]


# --------------------------------------------------------------------------- #
# service: _get_type
# --------------------------------------------------------------------------- #
def test_get_type_not_found_raises() -> None:
    svc = FormsService(_Session(gets=[None]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError, match="application type"):
        _run(svc._get_type(uuid.uuid4()))


def test_get_type_found_returns_type() -> None:
    at = _app_type()
    svc = FormsService(_Session(gets=[at]))  # type: ignore[arg-type]
    assert _run(svc._get_type(at.id)) is at


# --------------------------------------------------------------------------- #
# service: _fields_of_version
# --------------------------------------------------------------------------- #
def test_fields_of_version_maps_rows() -> None:
    rows = [_form_field_row("title", "text"), _form_field_row("amount", "currency", order=1)]
    svc = FormsService(_Session(results=[_Result(rows)]))  # type: ignore[arg-type]
    out = _run(svc._fields_of_version(uuid.uuid4()))
    assert [f.key for f in out] == ["title", "amount"]


# --------------------------------------------------------------------------- #
# service: _pot_fields — alle 404-Zweige + Erfolg
# --------------------------------------------------------------------------- #
def test_pot_fields_pot_not_found() -> None:
    at = _app_type(has_budget=True, gremium_id=uuid.uuid4())
    svc = FormsService(_Session(gets=[None]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError, match="budget pot .* not found"):
        _run(svc._pot_fields(at, uuid.uuid4()))


def test_pot_fields_type_without_budget() -> None:
    gremium_id = uuid.uuid4()
    at = _app_type(has_budget=False, gremium_id=gremium_id)
    pot = BudgetPot()
    pot.id = uuid.uuid4()
    pot.gremium_id = gremium_id
    svc = FormsService(_Session(gets=[pot]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError, match="does not support budget pots"):
        _run(svc._pot_fields(at, pot.id))


def test_pot_fields_type_gremium_none() -> None:
    at = _app_type(has_budget=True, gremium_id=None)
    pot = BudgetPot()
    pot.id = uuid.uuid4()
    pot.gremium_id = uuid.uuid4()
    svc = FormsService(_Session(gets=[pot]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError, match="not available for this application type"):
        _run(svc._pot_fields(at, pot.id))


def test_pot_fields_cross_gremium_rejected() -> None:
    at = _app_type(has_budget=True, gremium_id=uuid.uuid4())
    pot = BudgetPot()
    pot.id = uuid.uuid4()
    pot.gremium_id = uuid.uuid4()  # fremdes Gremium
    svc = FormsService(_Session(gets=[pot]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError, match="not available for this application type"):
        _run(svc._pot_fields(at, pot.id))


def test_pot_fields_success_maps_budget_fields() -> None:
    g = uuid.uuid4()
    at = _app_type(has_budget=True, gremium_id=g)
    pot = BudgetPot()
    pot.id = uuid.uuid4()
    pot.gremium_id = g
    rows = [
        _budget_field_row({"key": "cc", "type": "text", "label": {"de": "CC"}}),
        _budget_field_row({"key": "note", "type": "textarea", "label": {"de": "N"}}, order=1),
    ]
    svc = FormsService(_Session(results=[_Result(rows)], gets=[pot]))  # type: ignore[arg-type]
    out = _run(svc._pot_fields(at, pot.id))
    assert [f.key for f in out] == ["cc", "note"]


# --------------------------------------------------------------------------- #
# service: get_effective_form
# --------------------------------------------------------------------------- #
def test_get_effective_form_no_active_version_raises() -> None:
    at = _app_type(active_form_version_id=None)
    svc = FormsService(_Session(gets=[at]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError, match="no active form version"):
        _run(svc.get_effective_form(at.id))


def test_get_effective_form_active_version_main_only() -> None:
    ver_id = uuid.uuid4()
    at = _app_type(active_form_version_id=ver_id)
    field_rows = [_form_field_row("desc", "textarea")]
    svc = FormsService(
        _Session(results=[_Result(field_rows)], gets=[at])  # type: ignore[arg-type]
    )
    out = _run(svc.get_effective_form(at.id))
    assert out.application_type_id == at.id
    assert out.form_version_id == ver_id
    assert out.budget_pot_id is None
    assert [s.key for s in out.sections] == ["main"]
    # System-Titel wird vorangestellt + Standard-Label aufgelöst.
    assert out.sections[0].label == {"de": "Antrag", "en": "Application"}
    assert out.sections[0].fields[0].key == "title"


def test_get_effective_form_pinned_version_overrides_active() -> None:
    # form_version_id übersteuert active_form_version_id (gepinnte Form).
    pinned = uuid.uuid4()
    at = _app_type(active_form_version_id=uuid.uuid4())
    svc = FormsService(
        _Session(results=[_Result([_form_field_row("a", "text")])], gets=[at])  # type: ignore[arg-type]
    )
    out = _run(svc.get_effective_form(at.id, form_version_id=pinned))
    assert out.form_version_id == pinned


def test_get_effective_form_with_budget_pot_adds_section() -> None:
    g = uuid.uuid4()
    at = _app_type(has_budget=True, gremium_id=g, active_form_version_id=uuid.uuid4())
    pot = BudgetPot()
    pot.id = uuid.uuid4()
    pot.gremium_id = g
    type_fields = _Result([_form_field_row("a", "text")])
    pot_fields = _Result([_budget_field_row({"key": "cc", "type": "text", "label": {"de": "CC"}})])
    svc = FormsService(
        _Session(results=[type_fields, pot_fields], gets=[at, pot])  # type: ignore[arg-type]
    )
    out = _run(svc.get_effective_form(at.id, budget_pot_id=pot.id))
    assert [s.key for s in out.sections] == ["main", "budget"]
    assert out.sections[1].label == {
        "de": "Topf-spezifische Felder",
        "en": "Budget-specific fields",
    }
    assert out.budget_pot_id == pot.id


def test_get_effective_form_section_marker_label_preserved() -> None:
    # Sektion mit eigenem Marker-Label: s.label != None → wird direkt durchgereicht.
    ver_id = uuid.uuid4()
    at = _app_type(active_form_version_id=ver_id)
    rows = [
        _form_field_row("title", "text"),
        _form_field_row("step2", "section", order=1, label={"de": "Schritt 2", "en": "Step 2"}),
        _form_field_row("b", "currency", order=2),
    ]
    svc = FormsService(_Session(results=[_Result(rows)], gets=[at]))  # type: ignore[arg-type]
    out = _run(svc.get_effective_form(at.id))
    assert [s.key for s in out.sections] == ["main", "step2"]
    assert out.sections[1].label == {"de": "Schritt 2", "en": "Step 2"}


# --------------------------------------------------------------------------- #
# service: create_form_version
# --------------------------------------------------------------------------- #
def test_create_form_version_bad_definition_422() -> None:
    svc = FormsService(_Session())  # type: ignore[arg-type]
    payload = FormVersionCreate(
        fields=[
            FormFieldDef(key="dup", type="text", label={"de": "A"}),
            FormFieldDef(key="dup", type="number", label={"de": "B"}),
        ]
    )
    with pytest.raises(ValidationProblem) as ei:
        _run(svc.create_form_version(uuid.uuid4(), payload))
    assert ei.value.status == 422
    assert ei.value.errors is not None
    assert ei.value.errors[0].field == "fields"


def test_create_form_version_activate_true() -> None:
    at = _app_type()
    # gets: _get_type (validate-after), und nochmal _get_type für active set.
    sess = _Session(results=[2], gets=[at, at])  # _next_version → max=2
    svc = FormsService(sess)  # type: ignore[arg-type]
    payload = FormVersionCreate(
        fields=[FormFieldDef(key="title", type="text", label={"de": "T"})],
        activate=True,
        description={"de": "Beschreibung"},
    )
    out = _run(svc.create_form_version(at.id, payload))
    assert out.version == 3  # max 2 + 1
    assert out.active is True
    assert out.description == {"de": "Beschreibung"}
    assert [f.key for f in out.fields] == ["title"]
    # active=True → ein UPDATE-Deaktivierungs-Statement + Typ verweist auf neue Version.
    assert len(sess.statements) == 1
    assert at.active_form_version_id is not None
    assert sess.committed == 1
    # FormVersion + ein FormField wurden hinzugefügt.
    assert any(isinstance(o, FormVersion) for o in sess.added)
    assert sum(isinstance(o, FormField) for o in sess.added) == 1


def test_create_form_version_activate_false_first_version() -> None:
    at = _app_type()
    sess = _Session(results=[None], gets=[at])  # _next_version → keine vorherige → 1
    svc = FormsService(sess)  # type: ignore[arg-type]
    payload = FormVersionCreate(
        fields=[FormFieldDef(key="title", type="text", label={"de": "T"})],
        activate=False,
    )
    out = _run(svc.create_form_version(at.id, payload))
    assert out.version == 1
    assert out.active is False
    assert out.description is None
    # activate=False → kein UPDATE-Statement, active_form_version_id bleibt None.
    assert sess.statements == []
    assert at.active_form_version_id is None


# --------------------------------------------------------------------------- #
# service: set_form_active
# --------------------------------------------------------------------------- #
def test_set_form_active_true_activates_latest() -> None:
    at = _app_type()
    latest = _form_version(version=4, active=False)
    draft_fields = _Result([_form_field_row("a", "text")])
    # get-Queue: set_form_active._get_type, get_form_draft._get_type.
    # results: scalar(latest) [activate], scalar(version) [draft], scalars(fields) [draft]
    sess = _Session(
        results=[latest, latest, draft_fields],
        gets=[at, at],
    )
    svc = FormsService(sess)  # type: ignore[arg-type]
    out = _run(svc.set_form_active(at.id, True))
    assert latest.active is True
    assert at.active_form_version_id == latest.id
    assert out.application_type_id == at.id
    assert out.version == 4
    # ein UPDATE-Deaktivierungs-Statement.
    assert len(sess.statements) == 1
    assert sess.committed == 1


def test_set_form_active_true_no_version_raises() -> None:
    at = _app_type()
    sess = _Session(results=[None], gets=[at])  # scalar(latest) → None
    svc = FormsService(sess)  # type: ignore[arg-type]
    with pytest.raises(ValidationProblem, match="No form version to activate"):
        _run(svc.set_form_active(at.id, True))
    # commit erfolgt erst nach erfolgreicher Aktivierung → hier nicht.
    assert sess.committed == 0


def test_set_form_active_false_clears_active_version() -> None:
    at = _app_type(active_form_version_id=uuid.uuid4())
    version = _form_version(version=2, active=False)
    draft_fields = _Result([])
    # get-Queue: set._get_type, draft._get_type. results: scalar(version), scalars(fields)
    sess = _Session(results=[version, draft_fields], gets=[at, at])
    svc = FormsService(sess)  # type: ignore[arg-type]
    out = _run(svc.set_form_active(at.id, False))
    assert at.active_form_version_id is None
    assert out.version == 2
    assert len(sess.statements) == 1


# --------------------------------------------------------------------------- #
# service: get_form_draft
# --------------------------------------------------------------------------- #
def test_get_form_draft_no_version_returns_empty() -> None:
    at = _app_type()
    sess = _Session(results=[None], gets=[at])  # scalar(version) → None
    svc = FormsService(sess)  # type: ignore[arg-type]
    out = _run(svc.get_form_draft(at.id))
    assert out.application_type_id == at.id
    assert out.fields == []
    assert out.form_version_id is None
    assert out.version is None
    assert out.active is False


def test_get_form_draft_with_version_returns_fields() -> None:
    at = _app_type()
    version = _form_version(version=5, active=True, description={"de": "D"})
    fields = _Result([_form_field_row("a", "text"), _form_field_row("b", "number", order=1)])
    sess = _Session(results=[version, fields], gets=[at])
    svc = FormsService(sess)  # type: ignore[arg-type]
    out = _run(svc.get_form_draft(at.id))
    assert out.form_version_id == version.id
    assert out.version == 5
    assert out.active is True
    assert out.description == {"de": "D"}
    assert [f.key for f in out.fields] == ["a", "b"]


def test_get_form_draft_type_not_found() -> None:
    sess = _Session(gets=[None])
    svc = FormsService(sess)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        _run(svc.get_form_draft(uuid.uuid4()))


# --------------------------------------------------------------------------- #
# service: _next_version
# --------------------------------------------------------------------------- #
def test_next_version_from_existing_max() -> None:
    sess = _Session(results=[7])
    svc = FormsService(sess)  # type: ignore[arg-type]
    assert _run(svc._next_version(uuid.uuid4())) == 8


def test_next_version_no_versions_defaults_to_one() -> None:
    sess = _Session(results=[None])
    svc = FormsService(sess)  # type: ignore[arg-type]
    assert _run(svc._next_version(uuid.uuid4())) == 1


# --------------------------------------------------------------------------- #
# validation: _split_sections — trailing marker leaves no empty section (174->176)
# --------------------------------------------------------------------------- #
def _fd(key: str, type_: str, **kw: Any) -> FormFieldDef:
    kw.setdefault("label", {"de": key})
    return FormFieldDef.model_validate({"key": key, "type": type_, **kw})


def test_split_sections_trailing_marker_no_empty_section() -> None:
    # [a, section X]: nach der Schleife ist cur_fields leer UND sections nicht leer
    # → finaler Block wird NICHT angehängt (174-Bedingung beidseitig geprüft).
    out = _split_sections([_fd("a", "text"), _fd("x", "section", label={"de": "X"})])
    assert [s.key for s in out] == ["main"]
    assert [f.key for f in out[0].fields] == ["a"]


def test_split_sections_empty_input_yields_one_main() -> None:
    # Leere Eingabe: cur_fields leer, sections leer → `not sections` greift → ein main.
    out = _split_sections([])
    assert [s.key for s in out] == ["main"]
    assert out[0].fields == []


def test_split_sections_marker_without_label() -> None:
    # Marker mit leerem (falsy) Label → cur_label bleibt None.
    out = _split_sections(
        [_fd("a", "text"), _fd("step", "section", label={}), _fd("b", "text")]
    )
    assert [s.key for s in out] == ["main", "step"]
    assert out[1].label is None


# --------------------------------------------------------------------------- #
# validation: _offer_value — alle Zweige
# --------------------------------------------------------------------------- #
def test_offer_value_none_and_bool_return_none() -> None:
    assert _offer_value({"value": None}) is None
    assert _offer_value({"value": True}) is None
    assert _offer_value({}) is None  # fehlend → None


def test_offer_value_unparseable_returns_none() -> None:
    assert _offer_value({"value": "abc"}) is None


def test_offer_value_non_finite_returns_none() -> None:
    assert _offer_value({"value": "NaN"}) is None
    assert _offer_value({"value": float("inf")}) is None


def test_offer_value_valid_decimal() -> None:
    assert _offer_value({"value": "12.50"}) == Decimal("12.50")
    assert _offer_value({"value": 7}) == Decimal("7")


# --------------------------------------------------------------------------- #
# validation: _validate_positions — alle Fehlerzweige
# --------------------------------------------------------------------------- #
def _pos_field(**kw: Any) -> FormFieldDef:
    return _fd("positions", "positions", **kw)


def test_positions_not_a_list() -> None:
    errors: list[FieldError] = []
    _validate_value(_pos_field(), "nope", errors)
    assert errors and errors[0].msg == "must be a list of positions"


def test_positions_position_not_dict() -> None:
    errors: list[FieldError] = []
    _validate_value(_pos_field(validation={"minPositions": 1}), ["notadict"], errors)
    assert any(e.msg == "must be an object" for e in errors)


def test_positions_missing_label() -> None:
    errors: list[FieldError] = []
    value = [{"offers": [{"label": "A", "value": 5, "preferred": True}]}]
    _validate_value(_pos_field(validation={"minOffers": 1}), value, errors)
    assert any(e.msg == "position needs a label" for e in errors)


def test_positions_blank_label() -> None:
    errors: list[FieldError] = []
    value = [{"label": "   ", "offers": [{"label": "A", "value": 5, "preferred": True}]}]
    _validate_value(_pos_field(validation={"minOffers": 1}), value, errors)
    assert any(e.msg == "position needs a label" for e in errors)


def test_positions_offers_not_a_list() -> None:
    errors: list[FieldError] = []
    value = [{"label": "P", "offers": "nope"}]
    _validate_value(_pos_field(), value, errors)
    assert any(e.msg == "offers must be a list" for e in errors)


def test_positions_offer_not_dict() -> None:
    errors: list[FieldError] = []
    value = [{"label": "P", "offers": ["notadict", {"label": "A", "value": 5, "preferred": True}]}]
    _validate_value(_pos_field(validation={"minOffers": 1}), value, errors)
    assert any(e.msg == "must be an object" for e in errors)


def test_positions_offer_missing_label() -> None:
    errors: list[FieldError] = []
    value = [{"label": "P", "offers": [{"value": 5, "preferred": True}]}]
    _validate_value(_pos_field(validation={"minOffers": 1}), value, errors)
    assert any(e.msg == "offer needs a label" for e in errors)


def test_positions_offer_value_invalid_is_finite_error() -> None:
    errors: list[FieldError] = []
    value = [{"label": "P", "offers": [{"label": "A", "value": "abc", "preferred": True}]}]
    _validate_value(_pos_field(validation={"minOffers": 1}), value, errors)
    assert any(e.msg == "offer value must be a finite number" for e in errors)


def test_positions_offer_value_zero_error() -> None:
    errors: list[FieldError] = []
    value = [{"label": "P", "offers": [{"label": "A", "value": 0, "preferred": True}]}]
    _validate_value(_pos_field(validation={"minOffers": 1}), value, errors)
    assert any(e.msg == "offer value must be greater than 0" for e in errors)


def test_positions_too_many_preferred() -> None:
    errors: list[FieldError] = []
    value = [
        {
            "label": "P",
            "offers": [
                {"label": "A", "value": 5, "preferred": True},
                {"label": "B", "value": 6, "preferred": True},
            ],
        }
    ]
    _validate_value(_pos_field(validation={"minOffers": 1}), value, errors)
    assert any("exactly one offer must be marked preferred" in e.msg for e in errors)


def test_positions_valid_no_errors() -> None:
    errors: list[FieldError] = []
    value = [
        {
            "label": "P",
            "offers": [
                {"label": "A", "value": 5, "preferred": True},
                {"label": "B", "value": 6, "preferred": False},
            ],
        }
    ]
    _validate_value(_pos_field(validation={"minOffers": 1}), value, errors)
    assert errors == []


def test_positions_empty_offers_skips_preferred_check() -> None:
    # offers == [] → preferred-Check (``if offers and ...``) wird übersprungen,
    # nur die min_offers-Verletzung greift.
    errors: list[FieldError] = []
    value = [{"label": "P", "offers": []}]
    _validate_value(_pos_field(validation={"minOffers": 1}), value, errors)
    msgs = [e.msg for e in errors]
    assert any("at least 1 comparison offer" in m for m in msgs)
    assert not any("exactly one offer" in m for m in msgs)


# --------------------------------------------------------------------------- #
# validation: positions_total — alle Zweige
# --------------------------------------------------------------------------- #
def test_positions_total_not_a_list() -> None:
    assert positions_total("nope") is None
    assert positions_total(None) is None


def test_positions_total_skips_non_dict_positions() -> None:
    value = [
        "notadict",
        {"label": "P", "offers": [{"label": "A", "value": 100, "preferred": True}]},
    ]
    assert positions_total(value) == Decimal("100")


def test_positions_total_position_without_preferred() -> None:
    # Position ohne bevorzugtes Angebot → keine Summierung, found bleibt False.
    value = [{"label": "P", "offers": [{"label": "A", "value": 100, "preferred": False}]}]
    assert positions_total(value) is None


def test_positions_total_preferred_with_invalid_value_breaks_without_add() -> None:
    # Bevorzugtes Angebot mit ungültigem Wert: num is None → break ohne found.
    value = [{"label": "P", "offers": [{"label": "A", "value": "abc", "preferred": True}]}]
    assert positions_total(value) is None


def test_positions_total_offers_missing_key() -> None:
    # pos.get("offers") None → `or []` greift; keine bevorzugte Position.
    value = [{"label": "P"}]
    assert positions_total(value) is None


def test_positions_total_non_dict_offer_skipped() -> None:
    value = [
        {
            "label": "P",
            "offers": ["notadict", {"label": "A", "value": 50, "preferred": True}],
        }
    ]
    assert positions_total(value) == Decimal("50")


# --------------------------------------------------------------------------- #
# validation: extract_promoted — positions total None branch (484->486)
# --------------------------------------------------------------------------- #
def test_extract_promoted_positions_total_none_no_amount() -> None:
    # Positions-Feld ohne bevorzugte Position → total None → kein amount-Eintrag.
    fields = [_pos_field()]
    data = {
        "positions": [
            {"label": "P", "offers": [{"label": "A", "value": 5, "preferred": False}]}
        ]
    }
    assert extract_promoted(fields, data) == {}


def test_extract_promoted_positions_multiple_additive() -> None:
    # Zwei positions-Felder summieren additiv in amount.
    fields = [_fd("a", "positions"), _fd("b", "positions")]
    data = {
        "a": [{"label": "P", "offers": [{"label": "X", "value": 100, "preferred": True}]}],
        "b": [{"label": "Q", "offers": [{"label": "Y", "value": 50, "preferred": True}]}],
    }
    assert extract_promoted(fields, data) == {"amount": Decimal("150")}
