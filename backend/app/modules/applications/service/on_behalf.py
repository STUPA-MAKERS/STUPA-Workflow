"""Applications captured on behalf of an applicant (#11).

A person with ``application.create_on_behalf`` enters an application that reached the
Gremium another way, for example as a PDF or a mail. The applicant is an existing
account or a guest with a name and an e-mail. The application belongs to the
applicant exactly as if the applicant had submitted it. The capture runs the normal
create (`CreateOps.create`): the same validation, the same version 1, the same flow
start. It only adds the capture columns and a second audit entry.
"""

from __future__ import annotations

from datetime import date, timedelta
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
#: The oldest allowed received date, in days before today (review of #11): a typo
#: such as 2016 instead of 2026 must not move an application years back.
RECEIVED_ON_MAX_AGE_DAYS = 365


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

        A guest whose e-mail belongs to an active account (compared without case)
        becomes an applicant account: the application belongs to that account. The
        caller reads the outcome from ``created_by`` of the result.

        Raises:
            ValidationProblem: the account is unknown, inactive or has no e-mail, or
                ``receivedOn`` lies in the future or more than a year back. Form
                errors raise from the create.

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
        if received_on < today - timedelta(days=RECEIVED_ON_MAX_AGE_DAYS):
            raise ValidationProblem(
                "The received date lies more than one year in the past.",
                code="received_on_too_old",
                errors=[{"field": "receivedOn", "msg": "must not lie more than a year back"}],
            )
        owner_sub: str | None = None
        matched = False
        principal_id = payload.applicant_principal_id
        if principal_id is not None:
            owner_sub, email, name = await self._applicant_account(principal_id)
        else:
            # The schema guarantees both values for a guest.
            email = str(payload.applicant_email)
            name = (payload.applicant_name or "").strip()
            # User decision 2026-10-06: an e-mail of an active account makes the
            # application an account application of that account. The account then
            # owns it through `created_by` and reads it with the normal login, and no
            # second access path (a guest magic link) exists for the same person.
            match = await self._active_account_by_email(email)
            if match is not None:
                principal_id, owner_sub, email, name = match
                matched = True
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
                applicant_principal_id=principal_id,
                received_on=received_on,
                intake=intake,
                matched_by_email=matched,
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

    async def _active_account_by_email(
        self, email: str
    ) -> tuple[UUID, str, str, str | None] | None:
        """Return the active account of an e-mail (CITEXT, so without case), or None.

        Returns:
            The principal id, the ``sub``, the stored e-mail and the name.
        """
        from app.modules.auth.models import Principal as PrincipalRow

        row = (
            await self.session.scalars(
                select(PrincipalRow)
                .where(PrincipalRow.email == email, PrincipalRow.active.is_(True))
                .order_by(PrincipalRow.last_login.desc().nulls_last())
                .limit(1)
            )
        ).first()
        if row is None or not row.email:
            return None
        return row.id, row.sub, str(row.email), row.display_name

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
