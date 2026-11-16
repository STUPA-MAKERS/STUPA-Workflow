"""Application-types service (DB layer).

The public list holds the offerable types only. A type is offerable when it has
an active form version. `form.configure` also reveals the inactive types and the
admin fields. The list is in the order of step 1: by group, then by the position in
the group, the types without a group last (specs 001181-001183).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.application_types.models import ApplicationType, ApplicationTypeGroup
from app.modules.application_types.schemas import (
    ApplicationTypeGroupItem,
    ApplicationTypeListItem,
)
from app.shared.i18n import resolve_i18n
from app.shared.paging import Page


class ApplicationTypesService:
    """DB-backed application-type queries bound to an `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a database session."""
        self.session = session

    async def list_types(
        self,
        *,
        lang: str = "de",
        limit: int,
        offset: int,
        include_inactive: bool = False,
        admin: bool = False,
    ) -> Page[ApplicationTypeListItem]:
        """List the application types as a page (public view: offerable types only)."""
        every: Select[ApplicationType] = select(ApplicationType)
        stmt = (
            every
            if include_inactive
            else every.where(ApplicationType.active_form_version_id.is_not(None))
        )

        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (
            await self.session.scalars(
                stmt.outerjoin(
                    ApplicationTypeGroup, ApplicationTypeGroup.id == ApplicationType.group_id
                )
                .order_by(
                    ApplicationTypeGroup.position.nulls_last(),
                    ApplicationTypeGroup.created_at.nulls_last(),
                    ApplicationType.position,
                    ApplicationType.key,
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()

        items = [self._to_item(row, lang=lang, admin=admin) for row in rows]
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    @staticmethod
    def _to_item(row: ApplicationType, *, lang: str, admin: bool) -> ApplicationTypeListItem:
        """Map an ORM row to the list item with the resolved i18n name."""
        active_form_version_id: UUID | None = row.active_form_version_id
        return ApplicationTypeListItem(
            id=row.id,
            name=resolve_i18n(row.name_i18n, lang) or row.key,
            hasBudget=row.has_budget,
            active=active_form_version_id is not None,
            activeFormVersionId=active_form_version_id,
            key=row.key,
            gremiumId=row.gremium_id if admin else None,
            groupId=row.group_id,
        )

    async def list_groups(self, *, lang: str = "de") -> list[ApplicationTypeGroupItem]:
        """List every group in its order with the name and the text for `lang` (spec 001181).

        The list holds empty groups too; step 1 hides a group without an offered type.
        """
        rows = (
            await self.session.scalars(
                select(ApplicationTypeGroup).order_by(
                    ApplicationTypeGroup.position,
                    ApplicationTypeGroup.created_at,
                    ApplicationTypeGroup.id,
                )
            )
        ).all()
        return [
            ApplicationTypeGroupItem(
                id=row.id,
                name=resolve_i18n(row.name_i18n, lang) or "",
                text=resolve_i18n(row.text_i18n, lang) or "",
            )
            for row in rows
        ]
