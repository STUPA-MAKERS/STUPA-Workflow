"""Applications captured on behalf of an applicant (#11).

A person with ``application.create_on_behalf`` enters an application that reached the
Gremium another way, for example as a PDF or a mail. The applicant is an existing
account or a guest with a name and an e-mail. The application belongs to the
applicant exactly as if the applicant had submitted it. The capture runs the normal
create (`CreateOps.create`): the same validation, the same version 1, the same flow
start. It only adds the capture columns and a second audit entry.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import or_, select

from app.modules.applications.models import Application
from app.modules.applications.schemas import (
    ApplicantCandidateOut,
    ApplicationCreate,
    OnBehalfCreate,
)
from app.modules.applications.service.create import Capture, CreateOps
from app.search import escape_like
from app.shared.errors import ValidationProblem

if TYPE_CHECKING:
    from app.modules.flow.dispatch import ActionDispatcher

#: The most accounts that the applicant search returns.
APPLICANT_SEARCH_LIMIT = 20
#: The shortest search text. A shorter one returns no account.
APPLICANT_SEARCH_MIN = 2


class OnBehalfOps(CreateOps):
    """Capture on behalf of an applicant, and the applicant search of the dialog."""

    async def create_on_behalf(
        self,
        payload: OnBehalfCreate,
        *,
        actor: str,
        today: date,
        dispatcher: ActionDispatcher | None = None,
        draft_pepper: str | None = None,
    ) -> tuple[Application, str]:
        """Create and submit an application for the applicant in ``payload``.

        ``actor`` is the ``sub`` of the capturing person. ``today`` is the current
        date in the local timezone: the default of ``receivedOn`` and its upper
        bound.

        The application counts as confirmed at once (no magic-link verify), because a
        member entered it on purpose. Its flow starts in this call, like a logged-in
        submission.

        Raises:
            ValidationProblem: the account is unknown, inactive or has no e-mail, or
                ``receivedOn`` lies in the future. Form errors raise from the create.

        Returns:
            The application and the applicant e-mail, for the mail to the applicant.
        """
        received_on = payload.received_on or today
        if received_on > today:
            raise ValidationProblem(
                "The received date lies in the future.",
                code="received_on_in_future",
                errors=[{"field": "receivedOn", "msg": "must not lie in the future"}],
            )
        owner_sub: str | None = None
        if payload.applicant_principal_id is not None:
            owner_sub, email, name = await self._applicant_account(
                payload.applicant_principal_id
            )
        else:
            # The schema guarantees both values for a guest.
            email = str(payload.applicant_email)
            name = (payload.applicant_name or "").strip()
        intake = (payload.intake or "").strip() or None
        create = ApplicationCreate.model_validate(
            {
                "typeId": payload.type_id,
                "data": payload.data,
                "applicantEmail": email,
                "applicantName": name or None,
                "lang": payload.lang,
                "attachmentIds": payload.attachment_ids,
                "draftToken": payload.draft_token,
            }
        )
        return await self.create(
            create,
            actor=actor,
            dispatcher=dispatcher,
            email_confirmed=True,
            draft_pepper=draft_pepper,
            capture=Capture(
                owner_sub=owner_sub,
                applicant_principal_id=payload.applicant_principal_id,
                received_on=received_on,
                intake=intake,
            ),
        )

    async def _applicant_account(self, principal_id: UUID) -> tuple[str, str, str | None]:
        """Return the ``sub``, the e-mail and the name of an applicant account.

        Raises:
            ValidationProblem: the account is unknown, inactive or has no e-mail.
        """
        from app.modules.auth.models import Principal as PrincipalRow

        row = await self.session.get(PrincipalRow, principal_id)
        if row is None or not row.active or not row.email:
            raise ValidationProblem(
                "The applicant account is unknown, inactive or has no e-mail.",
                code="applicant_unavailable",
                errors=[
                    {
                        "field": "applicantPrincipalId",
                        "msg": "unknown, inactive or without e-mail",
                    }
                ],
            )
        return row.sub, str(row.email), row.display_name

    async def search_applicants(self, query: str) -> list[ApplicantCandidateOut]:
        """Search the active accounts with an e-mail by name or e-mail.

        The match is a case-insensitive substring. A text shorter than
        ``APPLICANT_SEARCH_MIN`` characters returns nothing, so the dialog never lists
        every account.
        """
        from app.modules.auth.models import Principal as PrincipalRow

        text = query.strip()
        if len(text) < APPLICANT_SEARCH_MIN:
            return []
        like = f"%{escape_like(text)}%"
        rows = (
            await self.session.scalars(
                select(PrincipalRow)
                .where(
                    PrincipalRow.active.is_(True),
                    PrincipalRow.email.is_not(None),
                    or_(
                        PrincipalRow.email.ilike(like, escape="\\"),
                        PrincipalRow.display_name.ilike(like, escape="\\"),
                    ),
                )
                .order_by(PrincipalRow.display_name, PrincipalRow.email)
                .limit(APPLICANT_SEARCH_LIMIT)
            )
        ).all()
        return [
            ApplicantCandidateOut(id=r.id, displayName=r.display_name, email=r.email)
            for r in rows
        ]
