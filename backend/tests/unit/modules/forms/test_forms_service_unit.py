"""Unit tests without a DB for the FormsService paths that run before any session use.

`create_form_version` validates the definition **before** it touches the DB. A broken
definition ends as 422 (`ValidationProblem`), not as 500. The test never touches the
session, so it needs no DB.
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
    svc = FormsService(None)  # type: ignore[arg-type]  — validation runs before session use
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