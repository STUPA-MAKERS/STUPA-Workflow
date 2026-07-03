"""Application-type CRUD."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.modules.admin.models import ApplicationType
from app.modules.admin.schemas import (
    ApplicationTypeCreate,
    ApplicationTypeOut,
    ApplicationTypeUpdate,
)
from app.modules.admin.service.service_base import ConfigServiceBase
from app.modules.audit.actions import AuditAction
from app.shared.errors import ConflictError, NotFoundError


def _type_out(row: ApplicationType) -> ApplicationTypeOut:
    return ApplicationTypeOut(
        id=row.id,
        gremium_id=row.gremium_id,
        key=row.key,
        name_i18n=row.name_i18n,
        has_budget=row.has_budget,
        comparison_offers=row.comparison_offers,
        retention_months=row.retention_months,
        active_form_version_id=row.active_form_version_id,
    )


class ApplicationTypeOps(ConfigServiceBase):
    """Application-type CRUD."""

    async def list_application_types(self) -> list[ApplicationTypeOut]:
        rows = (
            await self.session.scalars(
                select(ApplicationType).order_by(ApplicationType.key)
            )
        ).all()
        return [_type_out(r) for r in rows]

    async def create_application_type(
        self, payload: ApplicationTypeCreate, actor: str
    ) -> ApplicationTypeOut:
        existing = (
            await self.session.scalars(
                select(ApplicationType).where(ApplicationType.key == payload.key)
            )
        ).first()
        if existing is not None:
            raise ConflictError(f"application type {payload.key!r} already exists")
        row = ApplicationType(
            key=payload.key,
            name_i18n=payload.name_i18n,
            gremium_id=payload.gremium_id,
            has_budget=payload.has_budget,
            comparison_offers=(
                payload.comparison_offers.model_dump(by_alias=True)
                if payload.comparison_offers is not None
                else None
            ),
            retention_months=payload.retention_months,
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "application_type", row.id)
        await self.session.commit()
        return _type_out(row)

    async def update_application_type(
        self, type_id: UUID, payload: ApplicationTypeUpdate, actor: str
    ) -> ApplicationTypeOut:
        row = await self._get_type(type_id)
        if payload.name_i18n is not None:
            row.name_i18n = payload.name_i18n
        if payload.gremium_id is not None:
            row.gremium_id = payload.gremium_id
        if payload.has_budget is not None:
            row.has_budget = payload.has_budget
        if payload.comparison_offers is not None:
            row.comparison_offers = payload.comparison_offers.model_dump(by_alias=True)
        # An explicitly sent retentionMonths (including null = reset to the global
        # default) is applied — only omitted fields stay unchanged.
        if "retention_months" in payload.model_fields_set:
            row.retention_months = payload.retention_months
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "application_type", row.id)
        await self.session.commit()
        return _type_out(row)

    async def delete_application_type(self, type_id: UUID, actor: str) -> None:
        """Delete an application type (form versions cascade via FK).

        409 while applications of this type exist — ``application.type_id`` has
        no ``ON DELETE``, deleting would violate the FK.
        """
        row = await self._get_type(type_id)
        row_id = row.id
        from app.modules.applications.models import Application

        in_use = await self.session.scalar(
            select(Application.id).where(Application.type_id == type_id).limit(1)
        )
        if in_use is not None:
            raise ConflictError(
                "application type still has applications and cannot be deleted"
            )
        await self.session.delete(row)
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "application_type", row_id)
        await self.session.commit()

    async def _get_type(self, type_id: UUID) -> ApplicationType:
        row = await self.session.get(ApplicationType, type_id)
        if row is None:
            raise NotFoundError(f"application type {type_id} not found")
        return row
