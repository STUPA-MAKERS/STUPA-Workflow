"""Regression (AUD-044): nebenläufiges Anlegen desselben mail_template.key

Zwei gleichzeitige Requests für einen neuen Key passieren beide den
existing-is-None-Check; der zweite Commit verletzt UNIQUE(mail_template.key)
und muss als ConflictError (409) statt eines ungefangenen IntegrityError (500)
durchschlagen — sonst bricht der problem+json-Contract.
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
    """FakeSession, deren erstes `commit()` einen UNIQUE-Verstoß simuliert
    (das nebenläufige Insert hat gewonnen) und `rollback()` mitzählt."""

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
    # _get_template_by_key → keine Kollision beim Read, aber Commit verliert das Rennen.
    session = RaceSession(scalars=[[]])
    with pytest.raises(ConflictError):
        await _service(session).create_template(
            MailTemplateCreate(
                key="welcome", subjectI18n={"de": "x"}, bodyI18n={"de": "y"}
            )
        )
    assert session.rolled_back == 1


async def test_upsert_template_insert_race_maps_to_conflict() -> None:
    # Katalog-Key (status_update) ist zulässig; Read findet nichts → Insert-Zweig,
    # aber der Commit verliert das Rennen gegen ein nebenläufiges Insert.
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
    # Update-Zweig (Bestandszeile): ein UNIQUE-Verstoß ist hier kein
    # Key-Konflikt → kein falsches 409, der IntegrityError schlägt durch.
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
