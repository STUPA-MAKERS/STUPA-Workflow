"""TDD: BudgetService (T-17) ohne DB — Fake-Session deckt jeden Branch (kritisch, 100 %).

Die Reihenfolge der ``execute``-Ergebnisse spiegelt den Service-Ablauf wider
(s. ``tests/auth_fakes.FakeSession``: FIFO-Queue je ``execute``).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.budget.models import BudgetEntry, BudgetField, BudgetPot
from app.modules.budget.schemas import (
    AssignRequest,
    BudgetPotCreate,
    BudgetPotUpdate,
)
from app.modules.budget.service import BudgetService
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from tests.auth_fakes import fake_session, result

_GID = uuid.uuid4()
_PID = uuid.uuid4()
_AID = uuid.uuid4()
_TID = uuid.uuid4()


def _field(key: str = "extra") -> FormFieldDef:
    return FormFieldDef(key=key, type="text", label={"de": "X"})


def _field_row(key: str = "extra") -> BudgetField:
    return BudgetField(
        budget_pot_id=_PID,
        field={"key": key, "type": "text", "label": {"de": "X"}},
        order=0,
    )


def _pot(*, total: Decimal | None = Decimal("100"), gremium_id: uuid.UUID = _GID) -> BudgetPot:
    return BudgetPot(
        id=_PID, gremium_id=gremium_id, name="Topf", total=total,
        currency="EUR", period="2026", active=True,
    )


def _app(*, amount: Decimal | None = Decimal("50"), currency: str | None = "EUR") -> Application:
    a = Application(
        type_id=_TID, form_version_id=uuid.uuid4(), flow_version_id=uuid.uuid4(),
        gremium_id=_GID, budget_pot_id=None, amount=amount, currency=currency, data={},
    )
    a.id = _AID
    return a


def _type(*, has_budget: bool = True, gremium_id: uuid.UUID | None = _GID) -> ApplicationType:
    t = ApplicationType(gremium_id=gremium_id, key="t", name_i18n={}, has_budget=has_budget)
    t.id = _TID
    return t


def _entry(*, stage: str = "requested", amount: Decimal | None = Decimal("50"),
           application_id: uuid.UUID = _AID) -> BudgetEntry:
    e = BudgetEntry(
        budget_pot_id=_PID, application_id=application_id, stage=stage,
        amount=amount, currency="EUR",
    )
    e.id = uuid.uuid4()
    return e


# ------------------------------------------------------------------ create_pot
async def test_create_pot_with_fields() -> None:
    gremium = Gremium(name="G", slug="g")
    gremium.id = _GID
    db = fake_session(result(gremium))
    svc = BudgetService(db)
    out = await svc.create_pot(
        BudgetPotCreate(gremiumId=_GID, name="Topf", total=Decimal("100"), fields=[_field()])
    )
    assert out.name == "Topf"
    assert len(out.fields) == 1
    assert db.committed == 1
    # Topf + ein Feld hinzugefügt.
    assert sum(isinstance(o, BudgetPot) for o in db.added) == 1
    assert sum(isinstance(o, BudgetField) for o in db.added) == 1


async def test_create_pot_gremium_missing() -> None:
    db = fake_session(result())  # kein Gremium
    with pytest.raises(NotFoundError):
        await BudgetService(db).create_pot(BudgetPotCreate(gremiumId=_GID, name="X"))


async def test_create_pot_invalid_fields() -> None:
    db = fake_session()
    with pytest.raises(ValidationProblem):
        await BudgetService(db).create_pot(
            BudgetPotCreate(gremiumId=_GID, name="X", fields=[_field("dup"), _field("dup")])
        )


# -------------------------------------------------------------------- list_pots
async def test_list_pots_all_filters() -> None:
    db = fake_session(result(_pot()), result(_field_row()))
    out = await BudgetService(db).list_pots(gremium_id=_GID, period="2026", active=True)
    assert len(out) == 1
    assert len(out[0].fields) == 1


async def test_list_pots_no_filters_empty() -> None:
    db = fake_session(result())  # keine Töpfe
    out = await BudgetService(db).list_pots()
    assert out == []


# ---------------------------------------------------------------------- get_pot
async def test_get_pot_with_usage() -> None:
    db = fake_session(
        result(_pot()),                       # pot
        result(_field_row()),                 # fields
        result(_entry(stage="reserved")),     # entries
    )
    detail = await BudgetService(db).get_pot(_PID)
    assert detail.pot.id == _PID
    assert detail.usage.reserved == Decimal("50")
    assert detail.usage.available == Decimal("50")


async def test_get_pot_missing() -> None:
    db = fake_session(result())
    with pytest.raises(NotFoundError):
        await BudgetService(db).get_pot(_PID)


# ------------------------------------------------------------------- update_pot
async def test_update_pot_scalar_fields() -> None:
    db = fake_session(result(_pot()), result(_field_row()))
    out = await BudgetService(db).update_pot(
        _PID, BudgetPotUpdate(name="Neu", total=Decimal("200"))
    )
    assert out.name == "Neu"
    assert out.total == Decimal("200")


async def test_update_pot_replace_fields() -> None:
    db = fake_session(result(_pot()), result())  # pot, alte fields leer
    out = await BudgetService(db).update_pot(_PID, BudgetPotUpdate(fields=[_field("neu")]))
    assert [f.key for f in out.fields] == ["neu"]


async def test_update_pot_invalid_fields() -> None:
    db = fake_session(result(_pot()), result())
    with pytest.raises(ValidationProblem):
        await BudgetService(db).update_pot(
            _PID, BudgetPotUpdate(fields=[_field("d"), _field("d")])
        )


async def test_update_pot_missing() -> None:
    db = fake_session(result())
    with pytest.raises(NotFoundError):
        await BudgetService(db).update_pot(_PID, BudgetPotUpdate(name="X"))


# ---------------------------------------------------------------------- assign
async def test_assign_unassign_with_entry() -> None:
    entry = _entry()
    db = fake_session(result(_app()), result(entry))
    hook: list[int] = []

    async def trigger() -> None:
        hook.append(1)

    svc = BudgetService(db, stats_refresh=trigger)
    out = await svc.assign(_AID, AssignRequest(budgetPotId=None), actor="admin")
    assert out.budget_pot_id is None
    assert out.stage is None
    assert entry in db.deleted
    assert hook == [1]


async def test_assign_unassign_without_entry() -> None:
    db = fake_session(result(_app()), result())  # kein entry
    out = await BudgetService(db).assign(_AID, AssignRequest(budgetPotId=None), actor="admin")
    assert out.budget_pot_id is None
    assert db.deleted == []


async def test_assign_creates_entry() -> None:
    db = fake_session(
        result(_app()),     # application
        result(),           # kein bestehender entry
        result(_type()),    # type has_budget True, gremium match
        result(_pot()),     # pot
    )
    out = await BudgetService(db).assign(
        _AID, AssignRequest(budgetPotId=_PID, note="n"), actor="admin"
    )
    assert out.budget_pot_id == _PID
    assert out.stage == "requested"
    assert out.amount == Decimal("50")
    assert sum(isinstance(o, BudgetEntry) for o in db.added) == 1


async def test_assign_updates_existing_entry_and_currency_fallback() -> None:
    entry = _entry(stage="reserved")
    app = _app(currency=None)  # erzwingt Fallback auf pot.currency
    db = fake_session(result(app), result(entry), result(_type()), result(_pot()))
    out = await BudgetService(db).assign(_AID, AssignRequest(budgetPotId=_PID), actor="admin")
    assert out.currency == "EUR"  # aus pot.currency
    assert entry.stage == "requested"  # zurückgesetzt
    assert db.added == []  # bestehender entry, kein neuer


async def test_assign_blocked_no_budget() -> None:
    db = fake_session(
        result(_app()), result(), result(_type(has_budget=False)), result(_pot())
    )
    with pytest.raises(ValidationProblem):
        await BudgetService(db).assign(_AID, AssignRequest(budgetPotId=_PID), actor="admin")


async def test_assign_application_missing() -> None:
    db = fake_session(result())
    with pytest.raises(NotFoundError):
        await BudgetService(db).assign(_AID, AssignRequest(budgetPotId=_PID), actor="admin")


async def test_assign_pot_missing() -> None:
    db = fake_session(result(_app()), result(), result(_type()), result())
    with pytest.raises(NotFoundError):
        await BudgetService(db).assign(_AID, AssignRequest(budgetPotId=_PID), actor="admin")


async def test_assign_type_missing() -> None:
    db = fake_session(result(_app()), result(), result())  # type query → None
    with pytest.raises(NotFoundError):
        await BudgetService(db).assign(_AID, AssignRequest(budgetPotId=_PID), actor="admin")


# ------------------------------------------------------------------- set_stage
async def test_reserve_within_budget() -> None:
    entry = _entry(stage="requested")
    db = fake_session(
        result(entry),          # entry
        result(_app()),         # application (amount 50)
        result(_pot()),         # pot total 100
        result(),               # entries_of_pot (keine weiteren)
    )
    hook: list[int] = []

    async def trigger() -> None:
        hook.append(1)

    out = await BudgetService(db, stats_refresh=trigger).reserve(_AID, actor="admin")
    assert out.stage == "reserved"
    assert entry.stage == "reserved"
    assert hook == [1]


async def test_book_advances_to_approved_with_note() -> None:
    entry = _entry(stage="reserved")
    db = fake_session(result(entry), result(_app()), result(_pot()), result())
    out = await BudgetService(db).set_stage(_AID, "approved", actor="admin", note="ok")
    assert out.stage == "approved"
    assert entry.note == "ok"


async def test_set_stage_no_entry() -> None:
    db = fake_session(result())
    with pytest.raises(NotFoundError):
        await BudgetService(db).set_stage(_AID, "reserved", actor="admin")


async def test_set_stage_cannot_advance_backwards() -> None:
    entry = _entry(stage="approved")
    db = fake_session(result(entry))  # can_advance False → kein weiterer execute
    with pytest.raises(ConflictError):
        await BudgetService(db).set_stage(_AID, "reserved", actor="admin")


async def test_set_stage_overbook() -> None:
    entry = _entry(stage="requested", amount=Decimal("50"))
    other = _entry(stage="reserved", amount=Decimal("60"), application_id=uuid.uuid4())
    db = fake_session(
        result(entry),          # entry
        result(_app()),         # app amount 50
        result(_pot()),         # pot total 100
        result(other),          # committed others = 60 → 60+50 > 100
    )
    with pytest.raises(ConflictError):
        await BudgetService(db).reserve(_AID, actor="admin")


async def test_book_wrapper() -> None:
    entry = _entry(stage="requested")
    db = fake_session(result(entry), result(_app()), result(_pot()), result())
    out = await BudgetService(db).book(_AID, actor="admin")
    assert out.stage == "approved"


# ------------------------------------------------------- committed-excluding skip
async def test_committed_excluding_skips_self_and_uncommitted() -> None:
    entry = _entry(stage="requested", amount=Decimal("10"))
    same_app = _entry(stage="reserved", amount=Decimal("999"))  # gleiche app → ignoriert
    uncommitted = _entry(stage="requested", amount=Decimal("5"), application_id=uuid.uuid4())
    committed = _entry(stage="paid", amount=Decimal("20"), application_id=uuid.uuid4())
    db = fake_session(
        result(entry), result(_app(amount=Decimal("10"))), result(_pot()),
        result(same_app, uncommitted, committed),
    )
    out = await BudgetService(db).reserve(_AID, actor="admin")
    # nur 'committed' (20) zählt → 20+10 ≤ 100 ok.
    assert out.stage == "reserved"


# -------------------------------------------------------------- stats accessor
def test_stats_service_accessor() -> None:
    db = fake_session()
    assert BudgetService(db).stats_service() is not None
