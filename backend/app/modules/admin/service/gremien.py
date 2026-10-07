"""Gremium CRUD plus the per-gremium protocol mail-recipient list."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, distinct, func, or_, select

from app.modules.admin.gremium_roles import GremiumRoleService, _time_valid_clause
from app.modules.admin.models import (
    ApplicationType,
    CdVariant,
    Gremium,
    GremiumMembership,
    GremiumRole,
    MailList,
)
from app.modules.admin.schemas import (
    GremiumAdminOut,
    GremiumCreate,
    GremiumMailRecipients,
    GremiumOut,
    GremiumPublicPreview,
    GremiumUpdate,
)
from app.modules.admin.service.service_base import ConfigServiceBase
from app.modules.audit.actions import AuditAction
from app.modules.auth.models import Principal as PrincipalRow
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem


def _gremium_out(row: Gremium) -> GremiumOut:
    return GremiumOut(
        id=row.id,
        name=row.name,
        slug=row.slug,
        cd_variant_id=row.cd_variant_id,
        default_lang=row.default_lang,
        allow_vote_delegation=row.allow_vote_delegation,
        delegation_lead_minutes=row.delegation_lead_minutes,
        delegation_allow_external=row.delegation_allow_external,
        quorum_percent=row.quorum_percent,
        protocols_public=bool(row.protocols_public),
    )


class GremiumOps(ConfigServiceBase):
    """Gremium CRUD and the protocol recipient list."""

    async def list_gremien(self) -> list[GremiumOut]:
        rows = (await self.session.scalars(select(Gremium).order_by(Gremium.name))).all()
        return [_gremium_out(r) for r in rows]

    async def list_gremien_admin(self) -> list[GremiumAdminOut]:
        """List the gremien with the number of members and of gremium roles.

        Two grouped counts give the numbers for all gremien at once, so the admin
        list needs no request per gremium.

        The member count holds the current members only: a membership that is valid
        now (``valid_from``/``valid_until``, the same rule as RBAC) of an active
        principal. The membership list marks each row with the same rule (``active``),
        and the members page counts only the active rows.
        """
        rows = (await self.session.scalars(select(Gremium).order_by(Gremium.name))).all()
        now = datetime.now(UTC)
        member_rows = (
            await self.session.execute(
                select(
                    GremiumMembership.gremium_id,
                    func.count(distinct(GremiumMembership.principal_id)),
                )
                .join(PrincipalRow, PrincipalRow.id == GremiumMembership.principal_id)
                .where(_time_valid_clause(now), PrincipalRow.active.is_(True))
                .group_by(GremiumMembership.gremium_id)
            )
        ).all()
        role_rows = (
            await self.session.execute(
                select(GremiumRole.gremium_id, func.count(GremiumRole.id)).group_by(
                    GremiumRole.gremium_id
                )
            )
        ).all()
        members: dict[UUID, int] = {gid: int(n) for gid, n in member_rows}
        roles: dict[UUID, int] = {gid: int(n) for gid, n in role_rows}
        return [
            GremiumAdminOut(
                **_gremium_out(r).model_dump(),
                member_count=members.get(r.id, 0),
                role_count=roles.get(r.id, 0),
            )
            for r in rows
        ]

    async def create_gremium(self, payload: GremiumCreate, actor: str) -> GremiumOut:
        if await self._gremium_by_slug(payload.slug) is not None:
            raise ConflictError(f"gremium slug {payload.slug!r} already exists")
        await self._require_cd_variant(payload.cd_variant_id)
        row = Gremium(
            name=payload.name,
            slug=payload.slug,
            cd_variant_id=payload.cd_variant_id,
            default_lang=payload.default_lang,
            allow_vote_delegation=payload.allow_vote_delegation,
            delegation_lead_minutes=payload.delegation_lead_minutes,
            delegation_allow_external=payload.delegation_allow_external,
            quorum_percent=payload.quorum_percent,
            protocols_public=payload.protocols_public,
        )
        self.session.add(row)
        await self.session.flush()
        # Every new gremium gets the forced roles chair and secretary.
        await GremiumRoleService(self.session).ensure_forced_roles(row.id)
        await self._audit(
            actor,
            AuditAction.CONFIG_CHANGE,
            "gremium",
            row.id,
            {"protocolsPublic": row.protocols_public} if row.protocols_public else None,
        )
        await self.session.commit()
        return _gremium_out(row)

    async def gremium_protocols_public(self, gremium_id: UUID) -> bool:
        """Return the flag ``protocols_public`` of a gremium, False when it is missing."""
        value = await self.session.scalar(
            select(Gremium.protocols_public).where(Gremium.id == gremium_id)
        )
        return bool(value)

    async def gremium_public_preview(self, gremium_id: UUID) -> GremiumPublicPreview:
        """Count the protocols that a switch to public would publish.

        Raises:
            NotFoundError: No gremium has this id (404).
        """
        if await self.session.get(Gremium, gremium_id) is None:
            raise NotFoundError(f"gremium {gremium_id} not found")
        from app.modules.protocol.models import Protocol

        base = (
            select(func.count())
            .select_from(Protocol)
            .where(
                Protocol.gremium_id == gremium_id,
                Protocol.status == "final",
                Protocol.public_withheld.is_(False),
            )
        )
        final_count = int(await self.session.scalar(base) or 0)
        missing_count = int(
            await self.session.scalar(
                base.where(
                    or_(
                        Protocol.public_content.is_(None),
                        Protocol.public_pdf_storage_key.is_(None),
                    )
                )
            )
            or 0
        )
        return GremiumPublicPreview(final_count=final_count, missing_count=missing_count)

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
        # cdVariantId is clearable to null, so "not sent" and "set to null" differ.
        if "cd_variant_id" in payload.model_fields_set:
            await self._require_cd_variant(payload.cd_variant_id)
            row.cd_variant_id = payload.cd_variant_id
        if payload.default_lang is not None:
            row.default_lang = payload.default_lang
        if payload.allow_vote_delegation is not None:
            row.allow_vote_delegation = payload.allow_vote_delegation
        if payload.delegation_lead_minutes is not None:
            row.delegation_lead_minutes = payload.delegation_lead_minutes
        if payload.delegation_allow_external is not None:
            row.delegation_allow_external = payload.delegation_allow_external
        # quorumPercent is clearable to NULL. model_fields_set separates the case
        # "not sent" from the case "set to null".
        if "quorum_percent" in payload.model_fields_set:
            row.quorum_percent = payload.quorum_percent
        data: dict[str, object] | None = None
        if (
            payload.protocols_public is not None
            and payload.protocols_public != bool(row.protocols_public)
        ):
            # The audit entry names the old and the new value of the publication
            # flag, because the switch publishes or hides protocols at once.
            data = {
                "field": "protocolsPublic",
                "old": bool(row.protocols_public),
                "new": payload.protocols_public,
            }
            row.protocols_public = payload.protocols_public
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "gremium", row.id, data)
        await self.session.commit()
        return _gremium_out(row)

    async def delete_gremium(self, gremium_id: UUID, actor: str) -> None:
        """Delete a gremium.

        Role assignments cascade through the FK ``ON DELETE CASCADE``.

        Raises:
            NotFoundError: No gremium has this id (404).
            ConflictError: An application type of this gremium still has
                applications, or the gremium decides the running vote of an
                application (`gremium_decides_vote`) (409).
        """
        row = await self.session.get(Gremium, gremium_id)
        if row is None:
            raise NotFoundError(f"gremium {gremium_id} not found")
        # application_type.gremium_id cascades, but application.type_id is RESTRICT.
        # A delete of a gremium whose types still hold applications breaks the FK and
        # ends in a 500. This pre-check returns 409 instead, so no audit entry is
        # written for a doomed delete.
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
        # The Gremium decides a running vote (`application.vote_gremium_id`). A delete
        # would leave the application in its vote state without a deciding Gremium.
        deciding = await self.session.scalar(
            select(Application.id).where(Application.vote_gremium_id == gremium_id).limit(1)
        )
        if deciding is not None:
            raise ConflictError(
                "The Gremium decides a running vote of an application. Move the "
                "application out of its vote state first.",
                code="gremium_decides_vote",
            )
        await self.session.delete(row)
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "gremium", gremium_id)
        await self.session.commit()

    async def _require_cd_variant(self, variant_id: UUID | None) -> None:
        """Check the CD variant server-side. The client id is untrusted.

        Raises:
            ValidationProblem: No CD variant has this id (422).
        """
        if variant_id is None:
            return
        if await self.session.get(CdVariant, variant_id) is None:
            raise ValidationProblem(
                "Unknown CD variant.",
                errors=[{"field": "cdVariantId", "msg": f"{variant_id} does not exist"}],
            )

    async def _gremium_by_slug(self, slug: str) -> Gremium | None:
        return (
            await self.session.scalars(select(Gremium).where(Gremium.slug == slug))
        ).first()

    async def get_gremium_mail_recipients(
        self, gremium_id: UUID
    ) -> GremiumMailRecipients:
        """Return the extra protocol recipients (union of all active mail lists)."""
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

        A gremium keeps one canonical ``mail_list`` row with ``name='protocol'``.
        The method deletes all old rows first. An empty list means no extra
        recipients. The members still receive the protocol.
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
