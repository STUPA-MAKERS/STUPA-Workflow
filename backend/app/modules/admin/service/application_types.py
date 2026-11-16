"""Application-type CRUD, the groups of Antragsarten and their manual order.

The groups and the order are specs 001180 and 001183. A move swaps a row with its
neighbour and numbers the siblings 0..n again, so gaps and equal positions of old rows
heal on the first move.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update

from app.modules.admin.schemas import (
    ApplicationTypeCreate,
    ApplicationTypeGroupCreate,
    ApplicationTypeGroupOut,
    ApplicationTypeGroupUpdate,
    ApplicationTypeOut,
    ApplicationTypeUpdate,
)
from app.modules.admin.service.service_base import ConfigServiceBase
from app.modules.application_types.models import ApplicationType, ApplicationTypeGroup
from app.modules.audit.actions import AuditAction
from app.modules.forms.models import FormVersion
from app.modules.site_config.features import Feature, feature_on
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem


def _set_pdf_signatures(row: ApplicationType, wanted: bool | None) -> None:
    """Set the switch for the signature section of the Antrag PDF; ``None`` keeps it."""
    if wanted is not None:
        row.pdf_signatures = wanted


def _type_out(row: ApplicationType, version: int | None = None) -> ApplicationTypeOut:
    """Map a type row to its DTO. ``version`` is the number of the active form version."""
    return ApplicationTypeOut(
        id=row.id,
        gremium_id=row.gremium_id,
        key=row.key,
        name_i18n=row.name_i18n,
        has_budget=row.has_budget,
        pdf_signatures=row.pdf_signatures,
        comparison_offers=row.comparison_offers,
        retention_months=row.retention_months,
        group_id=row.group_id,
        position=row.position,
        active_form_version_id=row.active_form_version_id,
        active_form_version=version,
    )


def _group_out(row: ApplicationTypeGroup) -> ApplicationTypeGroupOut:
    """Map a group row to its DTO."""
    return ApplicationTypeGroupOut(
        id=row.id, name_i18n=row.name_i18n, text_i18n=row.text_i18n, position=row.position
    )


def _swap[T: (ApplicationType, ApplicationTypeGroup)](rows: list[T], row: T, by: int) -> bool:
    """Move ``row`` by one place in ``rows`` and number the list 0..n again.

    ``rows`` is in the current order. A move past either end changes nothing and
    returns ``False``.
    """
    index = rows.index(row)
    target = index + by
    if target < 0 or target >= len(rows):
        return False
    swapped = {index: rows[target], target: rows[index]}
    for position, item in enumerate(swapped.get(i, r) for i, r in enumerate(rows)):
        item.position = position
    return True


class ApplicationTypeOps(ConfigServiceBase):
    """Application-type CRUD, the groups of Antragsarten and their order."""

    async def list_application_types(self) -> list[ApplicationTypeOut]:
        """List every type with the number of its active form version.

        One outer join gives the version numbers, so the list needs no request
        per type.
        """
        rows = (
            await self.session.execute(
                select(ApplicationType, FormVersion.version)
                .outerjoin(FormVersion, FormVersion.id == ApplicationType.active_form_version_id)
                .order_by(ApplicationType.position, ApplicationType.key)
            )
        ).all()
        return [_type_out(row, version) for row, version in rows]

    async def create_application_type(
        self, payload: ApplicationTypeCreate, actor: str
    ) -> ApplicationTypeOut:
        """Create an application type.

        Raises:
            ConflictError: The key exists already.
        """
        existing = (
            await self.session.scalars(
                select(ApplicationType).where(ApplicationType.key == payload.key)
            )
        ).first()
        if existing is not None:
            raise ConflictError(
                f"application type {payload.key!r} already exists",
                code="application_type_exists",
            )
        await self._check_budget_on(payload.has_budget)
        if payload.group_id is not None:
            await self._get_group(payload.group_id)
        row = ApplicationType(
            key=payload.key,
            name_i18n=payload.name_i18n,
            gremium_id=payload.gremium_id,
            has_budget=payload.has_budget,
            pdf_signatures=payload.pdf_signatures,
            comparison_offers=(
                payload.comparison_offers.model_dump(by_alias=True)
                if payload.comparison_offers is not None
                else None
            ),
            retention_months=payload.retention_months,
            group_id=payload.group_id,
            position=await self._next_type_position(payload.group_id),
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "application_type", row.id)
        await self.session.commit()
        return _type_out(row)

    async def _check_budget_on(self, wants_budget: bool) -> None:
        """Refuse a new budget of an Antragsart while `Budget` is off.

        Raises:
            ValidationProblem: The type would get a budget and the feature is off.
        """
        if wants_budget and not await feature_on(self.session, Feature.BUDGET):
            raise ValidationProblem(
                "An Antragsart cannot have a budget while Budget is switched off.",
                errors=[{"field": "hasBudget", "msg": "feature_disabled"}],
            )

    async def update_application_type(
        self, type_id: UUID, payload: ApplicationTypeUpdate, actor: str
    ) -> ApplicationTypeOut:
        """Update an application type.

        A sent ``retentionMonths`` applies always, and a sent null resets it to the
        global default. An omitted field stays unchanged.
        """
        row = await self._get_type(type_id)
        await self._check_budget_on(bool(payload.has_budget) and not row.has_budget)
        if payload.name_i18n is not None:
            row.name_i18n = payload.name_i18n
        if payload.gremium_id is not None:
            row.gremium_id = payload.gremium_id
        if payload.has_budget is not None:
            row.has_budget = payload.has_budget
        _set_pdf_signatures(row, payload.pdf_signatures)
        if payload.comparison_offers is not None:
            row.comparison_offers = payload.comparison_offers.model_dump(by_alias=True)
        if "retention_months" in payload.model_fields_set:
            row.retention_months = payload.retention_months
        if "group_id" in payload.model_fields_set and payload.group_id != row.group_id:
            if payload.group_id is not None:
                await self._get_group(payload.group_id)
            await self._place(
                row.id, payload.group_id, await self._next_type_position(payload.group_id)
            )
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "application_type", row.id)
        await self.session.commit()
        return _type_out(row, await self._active_version(row))

    async def delete_application_type(self, type_id: UUID, actor: str) -> None:
        """Delete an application type.

        The form versions cascade through the foreign key. The method raises a
        409 while applications of this type exist. ``application.type_id`` has
        no ``ON DELETE``, so the delete would violate the foreign key.

        Raises:
            ConflictError: Applications of this type still exist.
            NotFoundError: The application type does not exist.
        """
        row = await self._get_type(type_id)
        row_id = row.id
        from app.modules.applications.models import Application

        in_use = await self.session.scalar(
            select(Application.id).where(Application.type_id == type_id).limit(1)
        )
        if in_use is not None:
            raise ConflictError(
                "application type still has applications and cannot be deleted",
                code="application_type_in_use",
            )
        await self.session.delete(row)
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "application_type", row_id)
        await self.session.commit()

    async def move_application_type(
        self, type_id: UUID, by: int, actor: str
    ) -> list[ApplicationTypeOut]:
        """Move a type one place up or down inside its group (spec 001183).

        Returns:
            Every type in the new order, as the list route answers.
        """
        row = await self._get_type(type_id)
        siblings = list(
            (
                await self.session.scalars(
                    select(ApplicationType)
                    .where(
                        ApplicationType.group_id.is_(None)
                        if row.group_id is None
                        else ApplicationType.group_id == row.group_id
                    )
                    .order_by(ApplicationType.position, ApplicationType.key)
                )
            ).all()
        )
        if _swap(siblings, row, by):
            await self._audit(actor, AuditAction.CONFIG_CHANGE, "application_type", row.id)
            await self.session.flush()
        return await self.list_application_types()

    async def list_application_type_groups(self) -> list[ApplicationTypeGroupOut]:
        """List the groups of Antragsarten in their order (spec 001183)."""
        return [_group_out(row) for row in await self._groups()]

    async def create_application_type_group(
        self, payload: ApplicationTypeGroupCreate, actor: str
    ) -> ApplicationTypeGroupOut:
        """Create a group at the end of the order (specs 001180, 001183)."""
        last = await self.session.scalar(select(func.max(ApplicationTypeGroup.position)))
        row = ApplicationTypeGroup(
            name_i18n=payload.name_i18n,
            text_i18n=payload.text_i18n,
            position=0 if last is None else last + 1,
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "application_type_group", row.id)
        await self.session.flush()
        return _group_out(row)

    async def update_application_type_group(
        self, group_id: UUID, payload: ApplicationTypeGroupUpdate, actor: str
    ) -> ApplicationTypeGroupOut:
        """Change the name or the text of a group. An omitted field stays unchanged."""
        row = await self._get_group(group_id)
        values = {
            key: value
            for key, value in (("name_i18n", payload.name_i18n), ("text_i18n", payload.text_i18n))
            if value is not None
        }
        if values:
            await self.session.execute(
                update(ApplicationTypeGroup)
                .where(ApplicationTypeGroup.id == row.id)
                .values(**values)
            )
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "application_type_group", row.id)
        await self.session.flush()
        return _group_out(row)

    async def delete_application_type_group(self, group_id: UUID, actor: str) -> None:
        """Delete a group. Its types stay and go to the end of the types without a group.

        The foreign key sets ``group_id`` to NULL. The types get positions after the
        types that have no group already, so they keep their order among themselves
        (spec 001180).
        """
        row = await self._get_group(group_id)
        row_id = row.id
        moved = (
            await self.session.scalars(
                select(ApplicationType)
                .where(ApplicationType.group_id == row_id)
                .order_by(ApplicationType.position, ApplicationType.key)
            )
        ).all()
        start = await self._next_type_position(None)
        for offset, item in enumerate(moved):
            await self._place(item.id, None, start + offset)
        await self.session.delete(row)
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "application_type_group", row_id)
        await self.session.flush()

    async def move_application_type_group(
        self, group_id: UUID, by: int, actor: str
    ) -> list[ApplicationTypeGroupOut]:
        """Move a group one place up or down (spec 001183).

        Returns:
            Every group in the new order.
        """
        row = await self._get_group(group_id)
        groups = await self._groups()
        if _swap(groups, row, by):
            await self._audit(actor, AuditAction.CONFIG_CHANGE, "application_type_group", row.id)
            await self.session.flush()
        return [_group_out(item) for item in sorted(groups, key=lambda g: g.position)]

    async def _groups(self) -> list[ApplicationTypeGroup]:
        """Return every group in its order; equal positions fall back to the create time."""
        return list(
            (
                await self.session.scalars(
                    select(ApplicationTypeGroup).order_by(
                        ApplicationTypeGroup.position,
                        ApplicationTypeGroup.created_at,
                        ApplicationTypeGroup.id,
                    )
                )
            ).all()
        )

    async def _next_type_position(self, group_id: UUID | None) -> int:
        """Return the position after the last type of a group, or of the types without one."""
        last = await self.session.scalar(
            select(func.max(ApplicationType.position)).where(
                ApplicationType.group_id.is_(None)
                if group_id is None
                else ApplicationType.group_id == group_id
            )
        )
        return 0 if last is None else last + 1

    async def _place(self, type_id: UUID, group_id: UUID | None, position: int) -> None:
        """Put a type into a group (or none) at a position.

        An ORM ``UPDATE`` keeps the loaded rows of the session in step with the database.
        """
        await self.session.execute(
            update(ApplicationType)
            .where(ApplicationType.id == type_id)
            .values(group_id=group_id, position=position)
        )

    async def _get_group(self, group_id: UUID) -> ApplicationTypeGroup:
        row = await self.session.get(ApplicationTypeGroup, group_id)
        if row is None:
            raise NotFoundError(f"application type group {group_id} not found")
        return row

    async def _active_version(self, row: ApplicationType) -> int | None:
        """Return the number of the active form version of a type, or ``None``."""
        if row.active_form_version_id is None:
            return None
        return await self.session.scalar(
            select(FormVersion.version).where(FormVersion.id == row.active_form_version_id)
        )

    async def _get_type(self, type_id: UUID) -> ApplicationType:
        row = await self.session.get(ApplicationType, type_id)
        if row is None:
            raise NotFoundError(f"application type {type_id} not found")
        return row
