"""Gremium CRUD plus the per-gremium protocol mail-recipient list."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select

from app.modules.admin.gremium_roles import GremiumRoleService
from app.modules.admin.models import ApplicationType, Gremium, MailList
from app.modules.admin.schemas import (
    GremiumCreate,
    GremiumMailRecipients,
    GremiumOut,
    GremiumUpdate,
)
from app.modules.admin.service.service_base import ConfigServiceBase
from app.modules.audit.actions import AuditAction
from app.shared.errors import ConflictError, NotFoundError


def _gremium_out(row: Gremium) -> GremiumOut:
    return GremiumOut(
        id=row.id,
        name=row.name,
        slug=row.slug,
        cd_variant=row.cd_variant,
        default_lang=row.default_lang,
        allow_vote_delegation=row.allow_vote_delegation,
        delegation_lead_minutes=row.delegation_lead_minutes,
        delegation_allow_external=row.delegation_allow_external,
        quorum_percent=row.quorum_percent,
    )


class GremiumOps(ConfigServiceBase):
    """Gremium CRUD and the protocol recipient list."""

    async def list_gremien(self) -> list[GremiumOut]:
        rows = (await self.session.scalars(select(Gremium).order_by(Gremium.name))).all()
        return [_gremium_out(r) for r in rows]

    async def create_gremium(self, payload: GremiumCreate, actor: str) -> GremiumOut:
        if await self._gremium_by_slug(payload.slug) is not None:
            raise ConflictError(f"gremium slug {payload.slug!r} already exists")
        row = Gremium(
            name=payload.name,
            slug=payload.slug,
            cd_variant=payload.cd_variant,
            default_lang=payload.default_lang,
            allow_vote_delegation=payload.allow_vote_delegation,
            delegation_lead_minutes=payload.delegation_lead_minutes,
            delegation_allow_external=payload.delegation_allow_external,
            quorum_percent=payload.quorum_percent,
        )
        self.session.add(row)
        await self.session.flush()
        # Forced roles (chair/secretary) are created together with the gremium.
        await GremiumRoleService(self.session).ensure_forced_roles(row.id)
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "gremium", row.id)
        await self.session.commit()
        return _gremium_out(row)

    async def update_gremium(
        self, gremium_id: UUID, payload: GremiumUpdate, actor: str
    ) -> GremiumOut:
        row = await self.session.get(Gremium, gremium_id)
        if row is None:
            raise NotFoundError(f"gremium {gremium_id} not found")
        if payload.slug is not None and payload.slug != row.slug:
            if await self._gremium_by_slug(payload.slug) is not None:
                raise ConflictError(f"gremium slug {payload.slug!r} already exists")
            row.slug = payload.slug
        if payload.name is not None:
            row.name = payload.name
        if payload.cd_variant is not None:
            row.cd_variant = payload.cd_variant
        if payload.default_lang is not None:
            row.default_lang = payload.default_lang
        if payload.allow_vote_delegation is not None:
            row.allow_vote_delegation = payload.allow_vote_delegation
        if payload.delegation_lead_minutes is not None:
            row.delegation_lead_minutes = payload.delegation_lead_minutes
        if payload.delegation_allow_external is not None:
            row.delegation_allow_external = payload.delegation_allow_external
        # quorumPercent is explicitly clearable (→ NULL): model_fields_set
        # distinguishes "not sent" from "set to null".
        if "quorum_percent" in payload.model_fields_set:
            row.quorum_percent = payload.quorum_percent
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "gremium", row.id)
        await self.session.commit()
        return _gremium_out(row)

    async def delete_gremium(self, gremium_id: UUID, actor: str) -> None:
        """Delete a gremium; role assignments cascade (FK ON DELETE CASCADE).

        404 for unknown ids.
        """
        row = await self.session.get(Gremium, gremium_id)
        if row is None:
            raise NotFoundError(f"gremium {gremium_id} not found")
        # application_type.gremium_id cascades, but application.type_id is RESTRICT:
        # deleting a gremium whose types still have applications would violate the FK
        # (500). Pre-check and return 409 so no audit entry is written for a doomed
        # delete.
        from app.modules.applications.models import Application

        in_use = await self.session.scalar(
            select(Application.id)
            .join(ApplicationType, Application.type_id == ApplicationType.id)
            .where(ApplicationType.gremium_id == gremium_id)
            .limit(1)
        )
        if in_use is not None:
            raise ConflictError(
                "gremium has application types with existing applications "
                "and cannot be deleted"
            )
        await self.session.delete(row)
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "gremium", gremium_id)
        await self.session.commit()

    async def _gremium_by_slug(self, slug: str) -> Gremium | None:
        return (
            await self.session.scalars(select(Gremium).where(Gremium.slug == slug))
        ).first()

    async def get_gremium_mail_recipients(
        self, gremium_id: UUID
    ) -> GremiumMailRecipients:
        """Extra protocol recipients of the gremium (union of all active lists)."""
        if await self.session.get(Gremium, gremium_id) is None:
            raise NotFoundError(f"gremium {gremium_id} not found")
        lists = (
            await self.session.scalars(
                select(MailList.recipients).where(
                    MailList.gremium_id == gremium_id, MailList.active.is_(True)
                )
            )
        ).all()
        seen: dict[str, None] = {}
        for recipients in lists:
            for addr in recipients or []:
                seen.setdefault(addr, None)
        return GremiumMailRecipients(recipients=list(seen))

    async def set_gremium_mail_recipients(
        self, gremium_id: UUID, payload: GremiumMailRecipients, actor: str
    ) -> GremiumMailRecipients:
        """Replace the extra protocol recipients (idempotent PUT).

        Canonically one ``mail_list`` row (``name='protocol'``) per gremium; all
        old rows are replaced. Empty list ⇒ no extra recipients (members still
        receive the protocol).
        """
        if await self.session.get(Gremium, gremium_id) is None:
            raise NotFoundError(f"gremium {gremium_id} not found")
        await self.session.execute(
            delete(MailList).where(MailList.gremium_id == gremium_id)
        )
        if payload.recipients:
            self.session.add(
                MailList(
                    gremium_id=gremium_id,
                    name="protocol",
                    recipients=payload.recipients,
                    active=True,
                )
            )
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "gremium", gremium_id)
        await self.session.commit()
        return GremiumMailRecipients(recipients=payload.recipients)
