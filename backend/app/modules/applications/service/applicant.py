"""Correction of the applicant PII (name and email)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.modules.applications.models import Applicant
from app.modules.applications.schemas import ApplicantOut, ApplicantPatch
from app.modules.applications.service.service_base import ApplicationsServiceBase
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.shared.errors import ConflictError, NotFoundError


class ApplicantOps(ApplicationsServiceBase):
    """Update the applicant row of one application."""

    async def update_applicant(
        self, application_id: UUID, payload: ApplicantPatch, *, actor: str
    ) -> ApplicantOut:
        """Correct the applicant name or email.

        An omitted field stays unchanged. The audit entry names the changed
        fields but never their values.

        Raises:
            NotFoundError: The application is unconfirmed or gone, or it has no
                applicant row (404).
            ConflictError: The applicant is anonymized (409, ``applicant_anonymized``).
        """
        # Same invisible-until-confirmed rule as the other principal routes; an
        # unconfirmed guest submission must not become an existence oracle.
        await self._get_app(application_id, allow_unconfirmed=False)
        applicant = (
            await self.session.execute(
                select(Applicant).where(Applicant.application_id == application_id)
            )
        ).scalar_one_or_none()
        if applicant is None:
            raise NotFoundError(f"applicant for application {application_id} not found")
        # Writing a name or an email back would undo a GDPR Art. 17 erasure.
        if applicant.anonymized_at is not None:
            raise ConflictError(
                "The applicant is anonymized and cannot be restored.",
                code="applicant_anonymized",
            )

        changed: list[str] = []
        if payload.email is not None and str(payload.email) != applicant.email:
            applicant.email = str(payload.email)
            changed.append("email")
        if payload.name is not None and payload.name != applicant.name:
            applicant.name = payload.name
            changed.append("name")

        if changed:
            await audit_record(
                self.session,
                actor=actor,
                action=AuditAction.APPLICANT_UPDATE,
                target_type="applicant",
                target_id=str(applicant.id),
                data={"applicationId": str(application_id), "fields": changed},
            )
        await self.session.commit()
        return ApplicantOut(email=applicant.email, name=applicant.name, anonymized=False)
