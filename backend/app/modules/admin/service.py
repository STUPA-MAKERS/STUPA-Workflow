"""Admin-/Config-Service (T-24): versionierte Config-CRUD + RBAC + Webhooks.

Serverseitig **autoritativ**: das FE ist nur UX-Gate, hier werden Permissions
erzwungen (Router) und Eingaben streng validiert (Flow-Graph via
``validate_flow_graph``, Comparison-Offers/Events via ``config_schemas``). Jede
Config-Mutation schreibt einen Audit-Eintrag (security.md §4) in derselben
Transaktion wie die Änderung.

Form-Versionen besitzt weiterhin das ``forms``-Modul (T-11); Flow-Versionen werden
hier analog angelegt (Graph → state/transition-Zeilen, max. eine ``active`` je Typ).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import ApplicationType, Gremium, Webhook
from app.modules.admin.schemas import (
    ApplicationTypeCreate,
    ApplicationTypeOut,
    ApplicationTypeUpdate,
    FlowVersionCreate,
    FlowVersionOut,
    GremiumCreate,
    GremiumOut,
    GremiumUpdate,
    GroupMappingCreate,
    GroupMappingOut,
    GroupMappingUpdate,
    PrincipalOut,
    RoleAssignmentCreate,
    RoleAssignmentOut,
    RoleAssignmentUpdate,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    WebhookCreate,
    WebhookOut,
    WebhookUpdate,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import GroupMapping, Principal, Role, RolePermission
from app.modules.auth.models import RoleAssignment as RoleAssignmentRow
from app.modules.flow.models import FlowVersion, State, Transition
from app.shared.config_schemas import (
    EventName,
    FlowValidationError,
    validate_flow_graph,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from app.shared.permissions import PERMISSION_CATALOGUE


def _parse_dt(value: str | None) -> datetime | None:
    """ISO-8601 → **tz-aware UTC** ``datetime``.

    ``role_assignment.valid_from``/``valid_until`` sind seit Migration 0015
    ``timestamptz`` — wir speichern konsequent aware-UTC (statt naiv), damit das
    Gültigkeitsfenster (Vertretung/Delegation) ohne den defensiven ``_as_aware``-
    Fallback im RBAC-Resolver korrekt vergleicht. Naive Eingaben werden als UTC
    interpretiert, aware Eingaben nach UTC normalisiert.
    """
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationProblem(
            "Invalid datetime.", errors=[{"field": "validFrom/validUntil", "msg": str(exc)}]
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class ConfigService:
    """An eine ``AsyncSession`` gebundene Admin-Config-Operationen."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # =================================================================== #
    # Gremium
    # =================================================================== #
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
        )
        self.session.add(row)
        await self.session.flush()
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
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "gremium", row.id)
        await self.session.commit()
        return _gremium_out(row)

    async def _gremium_by_slug(self, slug: str) -> Gremium | None:
        return (
            await self.session.scalars(select(Gremium).where(Gremium.slug == slug))
        ).first()

    # =================================================================== #
    # Application-Type
    # =================================================================== #
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
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "application_type", row.id)
        await self.session.commit()
        return _type_out(row)

    async def _get_type(self, type_id: UUID) -> ApplicationType:
        row = await self.session.get(ApplicationType, type_id)
        if row is None:
            raise NotFoundError(f"application type {type_id} not found")
        return row

    # =================================================================== #
    # Flow-Version (Graph → state/transition; max. eine active je Typ)
    # =================================================================== #
    async def create_flow_version(
        self, type_id: UUID, payload: FlowVersionCreate, actor: str
    ) -> FlowVersionOut:
        # Graph vor DB-Zugriff strukturell prüfen → 422 (ein Initial, erreichbar,
        # Guard-/Action-Whitelist), statt 500 (api.md §2, flows §9.5).
        try:
            validate_flow_graph(payload.graph)
        except FlowValidationError as exc:
            raise ValidationProblem(
                "Invalid flow graph.", errors=[{"field": "graph", "msg": str(exc)}]
            ) from exc
        await self._get_type(type_id)

        next_version = await self._next_flow_version(type_id)
        version = FlowVersion(
            application_type_id=type_id,
            version=next_version,
            active=payload.activate,
            editor_layout=payload.graph.layout or {},
        )
        if payload.activate:
            await self.session.execute(
                update(FlowVersion)
                .where(
                    FlowVersion.application_type_id == type_id,
                    FlowVersion.active.is_(True),
                )
                .values(active=False)
            )
        self.session.add(version)
        await self.session.flush()

        id_by_key: dict[str, UUID] = {}
        for state in payload.graph.states:
            row = State(
                flow_version_id=version.id,
                key=state.key,
                label_i18n=state.label,
                color=state.color,
                category=state.category or "open",
                edit_allowed=state.edit_allowed,
                is_initial=state.is_initial,
            )
            self.session.add(row)
            await self.session.flush()
            id_by_key[state.key] = row.id

        for order, trans in enumerate(payload.graph.transitions):
            self.session.add(
                Transition(
                    flow_version_id=version.id,
                    from_state_id=id_by_key[trans.from_],
                    to_state_id=id_by_key[trans.to],
                    label_i18n=trans.label or {},
                    guard=trans.guard,
                    actions=trans.actions,
                    order=trans.order if trans.order is not None else order,
                )
            )

        if payload.activate:
            app_type = await self._get_type(type_id)
            app_type.active_flow_version_id = version.id

        action = (
            AuditAction.CONFIG_ACTIVATION if payload.activate else AuditAction.CONFIG_CHANGE
        )
        await self._audit(
            actor, action, "flow_version", version.id, {"version": next_version}
        )
        await self.session.commit()
        return FlowVersionOut(
            id=version.id,
            application_type_id=type_id,
            version=next_version,
            active=payload.activate,
        )

    async def _next_flow_version(self, type_id: UUID) -> int:
        current = await self.session.scalar(
            select(FlowVersion.version)
            .where(FlowVersion.application_type_id == type_id)
            .order_by(FlowVersion.version.desc())
            .limit(1)
        )
        return (current or 0) + 1

    # =================================================================== #
    # Rollen / RBAC
    # =================================================================== #
    async def list_roles(self) -> list[RoleOut]:
        roles = (await self.session.scalars(select(Role).order_by(Role.key))).all()
        perms = (await self.session.scalars(select(RolePermission))).all()
        by_role: dict[UUID, list[str]] = {}
        for p in perms:
            by_role.setdefault(p.role_id, []).append(p.permission)
        return [
            RoleOut(
                id=r.id,
                key=r.key,
                label=r.name_i18n,
                permissions=sorted(by_role.get(r.id, [])),
            )
            for r in roles
        ]

    async def create_role(self, payload: RoleCreate, actor: str) -> RoleOut:
        existing = (
            await self.session.scalars(select(Role).where(Role.key == payload.key))
        ).first()
        if existing is not None:
            raise ConflictError(f"role {payload.key!r} already exists")
        role = Role(key=payload.key, name_i18n=payload.label)
        self.session.add(role)
        await self.session.flush()
        for perm in set(payload.permissions):
            self.session.add(RolePermission(role_id=role.id, permission=perm))
        await self._audit(actor, AuditAction.ROLE_CHANGE, "role", role.id)
        await self.session.commit()
        return RoleOut(
            id=role.id,
            key=role.key,
            label=role.name_i18n,
            permissions=sorted(set(payload.permissions)),
        )

    async def update_role(
        self, role_id: UUID, payload: RoleUpdate, actor: str
    ) -> RoleOut:
        role = await self.session.get(Role, role_id)
        if role is None:
            raise NotFoundError(f"role {role_id} not found")
        if payload.label is not None:
            role.name_i18n = payload.label
        if payload.permissions is not None:
            await self.session.execute(
                delete(RolePermission).where(RolePermission.role_id == role_id)
            )
            for perm in set(payload.permissions):
                self.session.add(RolePermission(role_id=role_id, permission=perm))
        await self._audit(actor, AuditAction.ROLE_CHANGE, "role", role.id)
        await self.session.commit()
        perms = (
            await self.session.scalars(
                select(RolePermission.permission).where(
                    RolePermission.role_id == role_id
                )
            )
        ).all()
        return RoleOut(
            id=role.id, key=role.key, label=role.name_i18n, permissions=sorted(perms)
        )

    # --------------------------------------------------------- assignments #
    async def list_role_assignments(self) -> list[RoleAssignmentOut]:
        rows = (await self.session.scalars(select(RoleAssignmentRow))).all()
        return [_assignment_out(r) for r in rows]

    async def create_role_assignment(
        self, payload: RoleAssignmentCreate, actor: str
    ) -> RoleAssignmentOut:
        if await self.session.get(Principal, payload.principal_id) is None:
            raise NotFoundError(f"principal {payload.principal_id} not found")
        if await self.session.get(Role, payload.role_id) is None:
            raise NotFoundError(f"role {payload.role_id} not found")
        row = RoleAssignmentRow(
            principal_id=payload.principal_id,
            role_id=payload.role_id,
            gremium_id=payload.gremium_id,
            granted_by=actor,
            valid_from=_parse_dt(payload.valid_from),
            valid_until=_parse_dt(payload.valid_until),
            delegate_voting=payload.delegate_voting,
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, AuditAction.ROLE_CHANGE, "role_assignment", row.id)
        await self.session.commit()
        return _assignment_out(row)

    async def update_role_assignment(
        self, assignment_id: UUID, payload: RoleAssignmentUpdate, actor: str
    ) -> RoleAssignmentOut:
        row = await self.session.get(RoleAssignmentRow, assignment_id)
        if row is None:
            raise NotFoundError(f"role assignment {assignment_id} not found")
        if payload.role_id is not None:
            if await self.session.get(Role, payload.role_id) is None:
                raise NotFoundError(f"role {payload.role_id} not found")
            row.role_id = payload.role_id
        if payload.gremium_id is not None:
            row.gremium_id = payload.gremium_id
        if payload.valid_from is not None:
            row.valid_from = _parse_dt(payload.valid_from)
        if payload.valid_until is not None:
            row.valid_until = _parse_dt(payload.valid_until)
        if payload.delegate_voting is not None:
            row.delegate_voting = payload.delegate_voting
        await self._audit(actor, AuditAction.ROLE_CHANGE, "role_assignment", row.id)
        await self.session.commit()
        return _assignment_out(row)

    async def delete_role_assignment(self, assignment_id: UUID, actor: str) -> None:
        """Rolle entziehen (#72): die Zuweisung löschen + auditieren."""
        row = await self.session.get(RoleAssignmentRow, assignment_id)
        if row is None:
            raise NotFoundError(f"role assignment {assignment_id} not found")
        await self.session.delete(row)
        await self._audit(actor, AuditAction.ROLE_CHANGE, "role_assignment", assignment_id)
        await self.session.commit()

    # ----------------------------------------------------- principals/perms #
    async def search_principals(
        self, query: str | None, limit: int = 50
    ) -> list[PrincipalOut]:
        """Principals (Benutzer) per OIDC-`sub`/Name/E-Mail suchen (#72).

        Ohne `query` werden die ersten `limit` Principals geliefert; mit `query` ein
        case-insensitives Teilstring-Match (CITEXT-E-Mail ist ohnehin ci). Inkl. der
        Rollenzuweisungen je Principal (ein Folge-Query, kein N+1)."""
        stmt = select(Principal)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    Principal.sub.ilike(like),
                    Principal.email.ilike(like),
                    Principal.display_name.ilike(like),
                )
            )
        stmt = stmt.order_by(Principal.display_name, Principal.sub).limit(limit)
        rows = (await self.session.scalars(stmt)).all()
        ids = [r.id for r in rows]
        by_principal: dict[UUID, list[RoleAssignmentRow]] = {}
        if ids:
            assignments = (
                await self.session.scalars(
                    select(RoleAssignmentRow).where(
                        RoleAssignmentRow.principal_id.in_(ids)
                    )
                )
            ).all()
            for a in assignments:
                by_principal.setdefault(a.principal_id, []).append(a)
        return [_principal_out(r, by_principal.get(r.id, [])) for r in rows]

    def list_permissions(self) -> list[str]:
        """Katalog wählbarer Permission-Keys fürs Rollen-/Rechte-UI (api.md §1)."""
        return list(PERMISSION_CATALOGUE)

    # ------------------------------------------------------ group-mappings #
    async def list_group_mappings(self) -> list[GroupMappingOut]:
        rows = (await self.session.scalars(select(GroupMapping))).all()
        return [_mapping_out(r) for r in rows]

    async def create_group_mapping(
        self, payload: GroupMappingCreate, actor: str
    ) -> GroupMappingOut:
        if await self.session.get(Role, payload.role_id) is None:
            raise NotFoundError(f"role {payload.role_id} not found")
        row = GroupMapping(
            oidc_group=payload.oidc_group,
            role_id=payload.role_id,
            gremium_id=payload.gremium_id,
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, AuditAction.ROLE_CHANGE, "group_mapping", row.id)
        await self.session.commit()
        return _mapping_out(row)

    async def update_group_mapping(
        self, mapping_id: UUID, payload: GroupMappingUpdate, actor: str
    ) -> GroupMappingOut:
        row = await self.session.get(GroupMapping, mapping_id)
        if row is None:
            raise NotFoundError(f"group mapping {mapping_id} not found")
        if payload.role_id is not None:
            if await self.session.get(Role, payload.role_id) is None:
                raise NotFoundError(f"role {payload.role_id} not found")
            row.role_id = payload.role_id
        if payload.oidc_group is not None:
            row.oidc_group = payload.oidc_group
        if payload.gremium_id is not None:
            row.gremium_id = payload.gremium_id
        await self._audit(actor, AuditAction.ROLE_CHANGE, "group_mapping", row.id)
        await self.session.commit()
        return _mapping_out(row)

    # =================================================================== #
    # Webhooks
    # =================================================================== #
    async def list_webhooks(self) -> list[WebhookOut]:
        rows = (
            await self.session.scalars(select(Webhook).order_by(Webhook.name))
        ).all()
        return [_webhook_out(r) for r in rows]

    async def create_webhook(self, payload: WebhookCreate, actor: str) -> WebhookOut:
        row = Webhook(
            name=payload.name,
            url=payload.url,
            events=list(payload.events),
            active=payload.active,
            secret=secrets.token_bytes(32),
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, AuditAction.WEBHOOK_CONFIG, "webhook", row.id)
        await self.session.commit()
        return _webhook_out(row)

    async def update_webhook(
        self, webhook_id: UUID, payload: WebhookUpdate, actor: str
    ) -> WebhookOut:
        row = await self.session.get(Webhook, webhook_id)
        if row is None:
            raise NotFoundError(f"webhook {webhook_id} not found")
        if payload.name is not None:
            row.name = payload.name
        if payload.url is not None:
            row.url = payload.url
        if payload.events is not None:
            row.events = list(payload.events)
        if payload.active is not None:
            row.active = payload.active
        await self._audit(actor, AuditAction.WEBHOOK_CONFIG, "webhook", row.id)
        await self.session.commit()
        return _webhook_out(row)

    # =================================================================== #
    # intern
    # =================================================================== #
    async def _audit(
        self,
        actor: str,
        action: AuditAction,
        target_type: str,
        target_id: UUID,
        data: dict | None = None,
    ) -> None:
        await audit_record(
            self.session,
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            data=data or {},
        )


# --------------------------------------------------------------------------- #
# Mapper
# --------------------------------------------------------------------------- #
def _gremium_out(row: Gremium) -> GremiumOut:
    return GremiumOut(
        id=row.id,
        name=row.name,
        slug=row.slug,
        cd_variant=row.cd_variant,
        default_lang=row.default_lang,
    )


def _type_out(row: ApplicationType) -> ApplicationTypeOut:
    return ApplicationTypeOut(
        id=row.id,
        gremium_id=row.gremium_id,
        key=row.key,
        name_i18n=row.name_i18n,
        has_budget=row.has_budget,
        comparison_offers=row.comparison_offers,
        active_form_version_id=row.active_form_version_id,
        active_flow_version_id=row.active_flow_version_id,
    )


def _assignment_out(row: RoleAssignmentRow) -> RoleAssignmentOut:
    return RoleAssignmentOut(
        id=row.id,
        principal_id=row.principal_id,
        role_id=row.role_id,
        gremium_id=row.gremium_id,
        granted_by=row.granted_by,
        valid_from=_iso(row.valid_from),
        valid_until=_iso(row.valid_until),
        delegate_voting=row.delegate_voting,
    )


def _principal_out(
    row: Principal, assignments: list[RoleAssignmentRow]
) -> PrincipalOut:
    return PrincipalOut(
        id=row.id,
        sub=row.sub,
        email=row.email,
        display_name=row.display_name,
        last_login=_iso(row.last_login),
        assignments=[_assignment_out(a) for a in assignments],
    )


def _mapping_out(row: GroupMapping) -> GroupMappingOut:
    return GroupMappingOut(
        id=row.id,
        oidc_group=row.oidc_group,
        role_id=row.role_id,
        gremium_id=row.gremium_id,
    )


def _webhook_out(row: Webhook) -> WebhookOut:
    return WebhookOut(
        id=row.id,
        name=row.name,
        url=row.url,
        events=cast("list[EventName]", list(row.events)),
        active=row.active,
    )
