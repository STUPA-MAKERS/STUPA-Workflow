"""Unit (ohne DB): FormsService-Pfade, die vor jedem Session-Zugriff greifen.

`create_form_version` validiert die Definition **vor** dem DB-Zugriff → eine defekte
Definition endet als 422 (`ValidationProblem`), nicht als 500. Die Session wird dabei
nie berührt, daher kein DB nötig.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ValidationProblem


def test_create_form_version_bad_definition_is_422_before_db() -> None:
    svc = FormsService(None)  # type: ignore[arg-type]  — Session wird vor Validierung nie genutzt
    payload = FormVersionCreate(
        fields=[
            FormFieldDef(key="dup", type="text", label={"de": "A"}),
            FormFieldDef(key="dup", type="number", label={"de": "B"}),
        ]
    )
    with pytest.raises(ValidationProblem) as ei:
        asyncio.run(svc.create_form_version(uuid4(), payload, "sub"))
    assert ei.value.status == 422
    assert ei.value.errors is not None
    assert ei.value.errors[0].field == "fields"