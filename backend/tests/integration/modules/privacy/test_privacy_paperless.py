"""The Paperless documents in the erasure and in the data export (real Postgres).

§ F/administration/privacy/002532 an erasure of an Antrag, of an address and of an
account lists each filed document with its number and its link, and the documents stay.
§ F/administration/privacy/002533 the data export names them with the number.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.service import ApplicationsService
from app.modules.paperless.models import PaperlessFiling, PaperlessSettings
from app.modules.privacy.models import ErasureRequest
from tests.integration.modules.applications.test_applications_service import (
    _create_payload,
    _seed_type,
)
from tests.integration.modules.privacy.test_privacy import _seed_principal
from tests.integration.modules.privacy.test_privacy_router import (
    _as_dpo,
    app,
    client,
    session,
)

__all__ = ["app", "client", "session"]

pytestmark = pytest.mark.integration

_FILED = datetime(2026, 11, 20, 9, 12, tzinfo=UTC)
_BASE = "https://paperless.test"


async def _filed_application(session: AsyncSession) -> tuple[uuid.UUID, str]:
    """Write an Antrag with two filed documents (41, 42) and one open job.

    Returns:
        The id of the Antrag and the address of the applicant.
    """
    app_type, _, _ = await _seed_type(session)
    application, email = await ApplicationsService(session).create(_create_payload(app_type.id))
    session.add(PaperlessSettings(id=1, base_url=_BASE, token="secret-token"))
    session.add_all(
        [
            PaperlessFiling(
                kind=kind,
                element_id=application.id,
                source_id=uuid.uuid4(),
                source_at=_FILED,
                application_id=application.id,
                title=title,
                state=state,
                document_id=number,
                filed_at=filed_at,
            )
            for kind, title, state, number, filed_at in (
                ("application", "Antrag", "filed", 41, _FILED),
                ("attachment", "Antrag – angebot.pdf", "filed", 42, _FILED.replace(hour=10)),
                ("attachment", "Antrag – offen.pdf", "pending", None, None),
            )
        ]
    )
    await session.commit()
    return application.id, email


_DOCUMENTS = [
    {
        "documentId": 41,
        "title": "Antrag",
        "url": f"{_BASE}/documents/41/details",
        "filedAt": "2026-11-20T09:12:00Z",
    },
    {
        "documentId": 42,
        "title": "Antrag – angebot.pdf",
        "url": f"{_BASE}/documents/42/details",
        "filedAt": "2026-11-20T10:12:00Z",
    },
]


async def _filings(session: AsyncSession) -> int:
    return len((await session.scalars(select(PaperlessFiling))).all())


async def test_the_erasure_of_an_antrag_lists_its_paperless_documents(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    application_id, _ = await _filed_application(session)
    other = ErasureRequest(subject_type="principal", status="open", email="nobody@example.org")
    request = ErasureRequest(subject_type="applicant", application_id=application_id, status="open")
    session.add_all([request, other])
    await session.commit()

    _as_dpo(app)
    listed = {row["id"]: row for row in client.get("/api/admin/privacy/erasures").json()}
    assert listed[str(request.id)]["paperlessDocuments"] == _DOCUMENTS
    assert listed[str(other.id)]["paperlessDocuments"] == []

    done = client.post(f"/api/admin/privacy/erasures/{request.id}/execute")
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "executed"
    assert done.json()["paperlessDocuments"] == _DOCUMENTS
    assert "secret-token" not in done.text
    # The platform deletes no filing: the list stays after the erasure.
    assert await _filings(session) == 3
    after = {row["id"]: row for row in client.get("/api/admin/privacy/erasures").json()}
    assert after[str(request.id)]["paperlessDocuments"] == _DOCUMENTS


async def test_the_erasure_of_an_account_lists_the_documents_of_its_antraege(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    _, email = await _filed_application(session)
    principal = await _seed_principal(session, email=email.upper())
    request = ErasureRequest(
        subject_type="principal", principal_id=principal.id, email=email, status="open"
    )
    session.add(request)
    await session.commit()

    _as_dpo(app)
    listed = client.get("/api/admin/privacy/erasures").json()
    assert [row["paperlessDocuments"] for row in listed] == [_DOCUMENTS]

    erased = client.post(f"/api/admin/privacy/principals/{principal.id}/erase")
    assert erased.status_code == 200, erased.text
    assert erased.json() == {"paperlessDocuments": _DOCUMENTS}
    assert await _filings(session) == 3


async def test_the_erasure_of_an_address_lists_the_documents(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    _, email = await _filed_application(session)

    _as_dpo(app)
    erased = client.post("/api/admin/privacy/erase-email", json={"email": email})
    assert erased.status_code == 200, erased.text
    assert erased.json()["applications"] == 1
    assert erased.json()["paperlessDocuments"] == _DOCUMENTS
    again = client.post("/api/admin/privacy/erase-email", json={"email": email})
    assert again.json()["paperlessDocuments"] == []


async def test_the_data_export_names_the_paperless_documents(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    application_id, email = await _filed_application(session)

    _as_dpo(app)
    exported = client.get("/api/admin/privacy/export", params={"email": email})
    assert exported.status_code == 200, exported.text
    rows = list(
        load_workbook(BytesIO(exported.content))["Paperless-Dokumente"].iter_rows(values_only=True)
    )
    assert [row[:3] for row in rows[1:]] == [
        (str(application_id), 41, "Antrag"),
        (str(application_id), 42, "Antrag – angebot.pdf"),
    ]
    assert all("2026" in str(row[3]) for row in rows[1:])
    empty = client.get("/api/admin/privacy/export", params={"email": "nobody@example.org"})
    assert load_workbook(BytesIO(empty.content))["Paperless-Dokumente"].max_row == 1
