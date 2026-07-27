"""Regression (AUD-044): two requests create the same mail_template.key at the same time.

Both requests pass the existing-is-None check for a new key. The second commit then
violates UNIQUE(mail_template.key). The service must map that to a ConflictError (409)
and not let an uncaught IntegrityError (500) through. An uncaught IntegrityError breaks
the problem+json contract.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.notifications.models import MailTemplate
from app.modules.notifications.schemas import (
    MailTemplateCreate,
    MailTemplateUpsert,
)
from app.modules.notifications.service import NotificationService
from app.settings import load_settings
from app.shared.errors import ConflictError
from tests._support.notifications_fakes import FakeSession

SETTINGS = load_settings()


class RaceSession(FakeSession):
    """FakeSession whose `commit()` simulates a UNIQUE violation.

    The violation stands for a concurrent insert that won the race. The session also
    counts the `rollback()` calls.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.rolled_back = 0

    async def commit(self) -> None:
        raise IntegrityError("INSERT", {}, Exception("duplicate key value"))

    async def rollback(self) -> None:
        self.rolled_back += 1


def _service(session: FakeSession) -> NotificationService:
    return NotificationService(session, queue=None, settings=SETTINGS)  # type: ignore[arg-type]


async def test_create_template_race_maps_to_conflict() -> None:
    # _get_template_by_key sees no collision on the read, but the commit loses the race.
    session = RaceSession(scalars=[[]])
    with pytest.raises(ConflictError):
        await _service(session).create_template(
            MailTemplateCreate(
                key="welcome", subjectI18n={"de": "x"}, bodyI18n={"de": "y"}
            )
        )
    assert session.rolled_back == 1


async def test_upsert_template_insert_race_maps_to_conflict() -> None:
    # The catalogue key status_update is allowed. The read finds nothing, so the insert
    # branch runs. Its commit then loses the race against a concurrent insert.
    session = RaceSession(scalars=[[]])
    with pytest.raises(ConflictError):
        await _service(session).upsert_template(
            MailTemplateUpsert(
                key="status_update",
                subjectI18n={"de": "x"},
                bodyI18n={"de": "y"},
            )
        )
    assert session.rolled_back == 1


async def test_upsert_template_update_race_reraises() -> None:
    # Update branch on an existing row: a UNIQUE violation here is not a key conflict.
    # The service must not answer with a false 409, so the IntegrityError passes through.
    existing = MailTemplate(
        key="status_update",
        subject_i18n={"de": "alt"},
        body_i18n={"de": "alt"},
        body_html_i18n={},
        placeholders={},
    )
    existing.id = uuid.uuid4()
    session = RaceSession(scalars=[[existing]])
    with pytest.raises(IntegrityError):
        await _service(session).upsert_template(
            MailTemplateUpsert(
                key="status_update",
                subjectI18n={"de": "neu"},
                bodyI18n={"de": "neu"},
            )
        )
    assert session.rolled_back == 1
