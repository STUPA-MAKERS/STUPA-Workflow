"""The Paperless documents that an erasure and the data export name.

A copy in Paperless stays after the anonymization in the platform, and the platform
never deletes it (§F/integrations/paperless/002522). So an erasure lists each filed
document of the erased data for the admin (§F/administration/privacy/002532), and the
data export names them for the person (§F/administration/privacy/002533). The documents
of a person are the filed documents of the Anträge whose applicant has the address of
the person, as the data export finds the Anträge.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Applicant
from app.modules.auth.models import Principal
from app.modules.paperless.filings import filed_for_applications
from app.modules.paperless.schemas import FiledDocumentOut
from app.modules.privacy.models import ErasureRequest

Documents = tuple[FiledDocumentOut, ...]


async def _applications_of(session: AsyncSession, emails: Sequence[str]) -> dict[str, list[UUID]]:
    """The Anträge of each address, by the address in lower case."""
    if not emails:
        return {}
    rows = (
        await session.execute(
            select(Applicant.email, Applicant.application_id)
            .where(Applicant.email.in_(emails))
            .order_by(Applicant.application_id)
        )
    ).all()
    return {
        key: [app_id for email, app_id in rows if str(email).lower() == key]
        for key in {str(email).lower() for email, _ in rows}
    }


async def documents_of_email(session: AsyncSession, email: str | None) -> Documents:
    """The filed documents of the Anträge of one address, in the order of the filing."""
    if not email:
        return ()
    app_ids = (await _applications_of(session, [email])).get(email.lower(), [])
    filed = await filed_for_applications(session, app_ids)
    return tuple(document for app_id in app_ids for document in filed.get(app_id, ()))


async def documents_of_principal(session: AsyncSession, principal_id: UUID) -> Documents:
    """The filed documents of the Anträge of the address of one account."""
    email = await session.scalar(select(Principal.email).where(Principal.id == principal_id))
    return await documents_of_email(session, email)


async def documents_of_requests(
    session: AsyncSession, requests: Sequence[ErasureRequest]
) -> dict[UUID, Documents]:
    """The filed documents of each erasure request.

    A request of an applicant names the documents of its Antrag. A request of an account
    names the documents of the Anträge of the address of the request.
    """
    emails = sorted(
        {r.email.lower() for r in requests if r.subject_type == "principal" and r.email}
    )
    by_email = await _applications_of(session, emails)
    wanted = {
        r.id: (
            [r.application_id]
            if r.subject_type == "applicant" and r.application_id is not None
            else by_email.get((r.email or "").lower(), [])
            if r.subject_type == "principal"
            else []
        )
        for r in requests
    }
    filed = await filed_for_applications(
        session, sorted({app_id for ids in wanted.values() for app_id in ids})
    )
    return {
        request_id: tuple(document for app_id in ids for document in filed.get(app_id, ()))
        for request_id, ids in wanted.items()
    }


async def export_rows(session: AsyncSession, email: str) -> list[dict[str, Any]]:
    """The rows of the sheet `Paperless-Dokumente` of the data export of one address."""
    app_ids = (await _applications_of(session, [email])).get(email.lower(), [])
    filed = await filed_for_applications(session, app_ids)
    return [
        {
            "applicationId": app_id,
            "documentId": document.document_id,
            "title": document.title,
            "filedAt": document.filed_at,
        }
        for app_id in app_ids
        for document in filed.get(app_id, ())
    ]
