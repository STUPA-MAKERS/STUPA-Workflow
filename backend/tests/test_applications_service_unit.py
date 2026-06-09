"""Unit (ohne echte DB): ApplicationsService-Pfade, die vor Schreibzugriffen greifen.

* 404, wenn der Antrag fehlt.
* 409 (Edit-Lock), wenn der aktuelle State ``edit_allowed=False`` ist — **vor** jeder
  Versions-/Schreiboperation.
* ``_amount_currency``/``_state_out`` Hilfslogik (promoted-Sync, State-Serialisierung).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from app.modules.applications.service import (
    ApplicationsService,
    _amount_currency,
    _scrub_diff,
    _state_out,
    _whitelist,
)
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ConflictError, NotFoundError


class _Obj:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


class _GetSession:
    """Minimaler AsyncSession-Stub: ``get(model, pk)`` aus einer Typ→Objekt-Map."""

    def __init__(self, by_type: dict[type, Any]) -> None:
        self._by_type = by_type

    async def get(self, model: type, _pk: Any) -> Any:  # noqa: ANN401
        return self._by_type.get(model)


def _service(by_type: dict[type, Any]) -> ApplicationsService:
    return ApplicationsService(_GetSession(by_type))  # type: ignore[arg-type]


def test_get_missing_application_404() -> None:
    from app.modules.applications.models import Application

    svc = _service({Application: None})
    with pytest.raises(NotFoundError):
        asyncio.run(svc.get(uuid4(), include_pii=False))


def test_patch_locked_state_409_before_write() -> None:
    from app.modules.applications.models import Application
    from app.modules.flow.models import State

    app = _Obj(id=uuid4(), current_state_id=uuid4(), data={"a": 1})
    locked = _Obj(edit_allowed=False)
    svc = _service({Application: app, State: locked})
    with pytest.raises(ConflictError):
        asyncio.run(svc.patch(uuid4(), {"a": 2}, changed_by="applicant"))


def test_patch_missing_application_404() -> None:
    from app.modules.applications.models import Application

    svc = _service({Application: None})
    with pytest.raises(NotFoundError):
        asyncio.run(svc.patch(uuid4(), {}, changed_by="x"))


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def test_amount_currency_extracts_promoted() -> None:
    fields = [
        FormFieldDef.model_validate(
            {
                "key": "cost",
                "type": "currency",
                "label": {"de": "Kosten"},
                "isPromoted": True,
                "promoteTarget": "amount",
            }
        )
    ]
    amount, currency = _amount_currency(fields, {"cost": "42.50"})
    assert amount == Decimal("42.50")
    assert currency == "EUR"


def test_amount_currency_none_when_absent() -> None:
    fields = [FormFieldDef(key="title", type="text", label={"de": "Titel"})]
    assert _amount_currency(fields, {"title": "x"}) == (None, None)


def test_whitelist_drops_unknown_keys() -> None:
    fields = [
        FormFieldDef(key="title", type="text", label={"de": "Titel"}),
        FormFieldDef(key="amount", type="currency", label={"de": "Betrag"}),
    ]
    clean = _whitelist(fields, {"title": "x", "amount": "1", "junk": "y" * 100, "evil": 1})
    assert clean == {"title": "x", "amount": "1"}


def test_scrub_diff_removes_pii_keys() -> None:
    diff = {
        "added": {"note": "secret", "title": "x"},
        "removed": {"note": "old"},
        "changed": {"note": {"old": "a", "new": "b"}, "title": {"old": "x", "new": "y"}},
    }
    scrubbed = _scrub_diff(diff, {"note"})
    assert scrubbed == {
        "added": {"title": "x"},
        "removed": {},
        "changed": {"title": {"old": "x", "new": "y"}},
    }


def test_state_out_none() -> None:
    assert _state_out(None) is None


def test_state_out_maps_fields() -> None:
    state = _Obj(
        id=uuid4(),
        key="draft",
        label_i18n={"de": "Entwurf"},
        color="#4a90d9",
        edit_allowed=True,
        kind="normal",
    )
    out = _state_out(state)  # type: ignore[arg-type]
    assert out is not None
    assert out.key == "draft"
    assert out.color == "#4a90d9"
    assert out.edit_allowed is True
    assert out.kind == "normal"
    assert out.label == {"de": "Entwurf"}
