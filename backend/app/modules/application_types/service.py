"""Application-types service (DB layer).

Publicly only offerable types are listed (an active form version exists);
``form.configure`` additionally reveals inactive types and admin fields.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import ApplicationType
from app.modules.application_types.schemas import ApplicationTypeListItem
from app.shared.i18n import resolve_i18n
from app.shared.paging import Page


class ApplicationTypesService:
    """DB-backed application-type queries bound to an ``AsyncSession``."""

    def __init__(self, session: AsyncSession) -> None:
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
        """List application types, paged (public: offerable types only)."""
        stmt: Select[tuple[ApplicationType]] = select(ApplicationType)
        if not include_inactive:
            stmt = stmt.where(ApplicationType.active_form_version_id.is_not(None))

        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (
            await self.session.scalars(
                stmt.order_by(ApplicationType.key).limit(limit).offset(offset)
            )
        ).all()

        items = [self._to_item(row, lang=lang, admin=admin) for row in rows]
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    @staticmethod
    def _to_item(row: ApplicationType, *, lang: str, admin: bool) -> ApplicationTypeListItem:
        """Map an ORM row to the list DTO with resolved i18n name."""
        active_form_version_id: UUID | None = row.active_form_version_id
        return ApplicationTypeListItem(
            id=row.id,
            name=resolve_i18n(row.name_i18n, lang) or row.key,
            hasBudget=row.has_budget,
            active=active_form_version_id is not None,
            activeFormVersionId=active_form_version_id,
            key=row.key if admin else None,
            gremiumId=row.gremium_id if admin else None,
        )
