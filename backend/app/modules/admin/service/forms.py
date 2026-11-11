"""The write of a form version with its config revision.

The write is in `admin` and not in `forms`, because it records a config revision, and
`forms` imports no higher module (§S/backend/python/000651). The services that write
the flow and the site configuration are in `admin` for the same reason.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from app.modules.audit.actions import AuditAction
from app.modules.config_revision.service import ENTITY_FORM, ConfigRevisionService
from app.modules.forms.models import FormField, FormVersion
from app.modules.forms.schemas import FormVersionCreate, FormVersionOut
from app.modules.forms.service import FormsService, field_def_to_row_kwargs
from app.modules.forms.validation import FormDefinitionError, validate_definition
from app.shared.errors import ValidationProblem


class FormVersionWriter(FormsService):
    """The forms service plus the write of a new form version."""

    async def create_form_version(
        self,
        type_id: UUID,
        payload: FormVersionCreate,
        actor: str,
        *,
        action: AuditAction = AuditAction.CONFIG_CHANGE,
        extra_data: dict[str, Any] | None = None,
    ) -> FormVersionOut:
        """Create a new form version and validate the definition.

        The service activates the new version when ``payload.activate`` is set. The old
        versions stay unchanged. The service also writes a ``config_revision`` snapshot
        and a linked audit entry. ``action`` and ``extra_data`` carry the restore and
        revert path.

        The service validates the input before any DB access, so a broken definition gives 422,
        not 500.

        Raises:
            ValidationProblem: The form definition is invalid.
            NotFoundError: The application type does not exist.
        """
        try:
            validate_definition(payload.fields)
        except FormDefinitionError as exc:
            raise ValidationProblem(
                "Invalid form definition.", errors=[{"field": "fields", "msg": str(exc)}]
            ) from exc
        await self._get_type(type_id)

        next_version = await self._next_version(type_id)

        version = FormVersion(
            application_type_id=type_id,
            version=next_version,
            active=payload.activate,
            description_i18n=payload.description,
        )
        if payload.activate:
            await self.session.execute(
                update(FormVersion)
                .where(
                    FormVersion.application_type_id == type_id,
                    FormVersion.active.is_(True),
                )
                .values(active=False)
            )
        self.session.add(version)
        await self.session.flush()

        for order, field in enumerate(payload.fields):
            self.session.add(
                FormField(form_version_id=version.id, **field_def_to_row_kwargs(field, order))
            )

        if payload.activate:
            app_type = await self._get_type(type_id)
            app_type.active_form_version_id = version.id

        await ConfigRevisionService(self.session).record(
            entity_type=ENTITY_FORM,
            entity_id=str(type_id),
            snapshot={
                "fields": [f.model_dump(by_alias=True) for f in payload.fields],
                "description": payload.description,
            },
            actor=actor,
            action=action,
            extra_data=extra_data,
        )
        await self.session.commit()
        return FormVersionOut(
            id=version.id,
            applicationTypeId=type_id,
            version=next_version,
            active=payload.activate,
            fields=payload.fields,
            description=payload.description,
        )

    async def _next_version(self, type_id: UUID) -> int:
        current_max = await self.session.scalar(
            select(FormVersion.version)
            .where(FormVersion.application_type_id == type_id)
            .order_by(FormVersion.version.desc())
            .limit(1)
        )
        return (current_max or 0) + 1
