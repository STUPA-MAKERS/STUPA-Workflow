"""Admin-/Config-Service (T-24): versionierte Config-CRUD + RBAC + Webhooks.

Serverseitig **autoritativ**: das FE ist nur UX-Gate, hier werden Permissions
erzwungen (Router) und Eingaben streng validiert (Flow-Graph via
``validate_flow_graph``, Comparison-Offers/Events via ``config_schemas``). Jede
Config-Mutation schreibt einen Audit-Eintrag (security.md §4) in derselben
Transaktion wie die Änderung.

Form-Versionen besitzt weiterhin das ``forms``-Modul (T-11); der **eine globale
Flow** (Graph → state/transition-Zeilen) wird hier in-place gepflegt.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.gremium_roles import GremiumRoleService
from app.modules.admin.models import ApplicationType, Gremium, MailList, Webhook
from app.modules.admin.schemas import (
    ApplicationTypeCreate,
    ApplicationTypeOut,
    ApplicationTypeUpdate,
    FlowVersionCreate,
    FlowVersionOut,
    GremiumCreate,
    GremiumMailRecipients,
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
    FlowGraph,
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
            allow_vote_delegation=payload.allow_vote_delegation,
            delegation_lead_minutes=payload.delegation_lead_minutes,
            delegation_allow_external=payload.delegation_allow_external,
            quorum_percent=payload.quorum_percent,
        )
        self.session.add(row)
        await self.session.flush()
        # Pflichtrollen (Vorstand/Schriftführung) sofort anlegen (#Meetings).
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
        # ``quorumPercent`` ist explizit löschbar (→ NULL): per ``model_fields_set``
        # unterscheiden wir „nicht gesendet" von „auf null gesetzt".
        if "quorum_percent" in payload.model_fields_set:
            row.quorum_percent = payload.quorum_percent
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "gremium", row.id)
        await self.session.commit()
        return _gremium_out(row)

    async def delete_gremium(self, gremium_id: UUID, actor: str) -> None:
        """Gremium löschen (#41). Rollenzuweisungen kaskadieren (FK ON DELETE
        CASCADE). 404 bei unbekannter id."""
        row = await self.session.get(Gremium, gremium_id)
        if row is None:
            raise NotFoundError(f"gremium {gremium_id} not found")
        await self.session.delete(row)
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "gremium", gremium_id)
        await self.session.commit()

    async def _gremium_by_slug(self, slug: str) -> Gremium | None:
        return (
            await self.session.scalars(select(Gremium).where(Gremium.slug == slug))
        ).first()

    # ----------------------------------- Protokoll-Verteiler (#protocol-recipients)
    async def get_gremium_mail_recipients(
        self, gremium_id: UUID
    ) -> GremiumMailRecipients:
        """Zusätzliche Protokoll-Empfänger des Gremiums (Union aller aktiven Listen)."""
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
        """Zusätzliche Protokoll-Empfänger ersetzen (idempotentes PUT).

        Kanonisch eine ``mail_list``-Zeile (``name='protocol'``) je Gremium; alle
        Alt-Zeilen werden ersetzt. Leere Liste ⇒ keine Zusatz-Empfänger (die
        Mitglieder erhalten das Protokoll weiterhin)."""
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
    # Globaler Flow (#28: genau EIN Flow für alle Antragstypen)
    # =================================================================== #
    async def get_active_global_flow(self) -> FlowGraph | None:
        """Graph des aktiven **globalen** Flows.

        Liefert ``None``, wenn noch kein globaler Flow existiert (Editor startet
        dann mit leerem Graphen)."""
        version = await self.session.scalar(
            select(FlowVersion).where(FlowVersion.active.is_(True)).limit(1)
        )
        if version is None:
            return None
        states = (
            await self.session.scalars(
                select(State).where(State.flow_version_id == version.id)
            )
        ).all()
        transitions = (
            await self.session.scalars(
                select(Transition)
                .where(Transition.flow_version_id == version.id)
                .order_by(Transition.order)
            )
        ).all()
        key_by_id = {s.id: s.key for s in states}
        return FlowGraph.model_validate(
            {
                "states": [
                    {
                        "key": s.key,
                        "label": s.label_i18n,
                        "color": s.color,
                        "editAllowed": s.edit_allowed,
                        "isInitial": s.is_initial,
                        "kind": s.kind,
                        "config": s.config or {},
                    }
                    for s in states
                ],
                "transitions": [
                    {
                        "from": key_by_id[t.from_state_id],
                        "to": key_by_id[t.to_state_id],
                        "label": t.label_i18n or None,
                        "color": t.color,
                        "guard": t.guard,
                        "actions": t.actions or [],
                        "order": t.order,
                        "automatic": t.automatic,
                        "branch": t.branch,
                        "requiresAction": t.requires_action,
                    }
                    for t in transitions
                ],
                "layout": version.editor_layout or None,
            }
        )

    async def create_global_flow_version(
        self, payload: FlowVersionCreate, actor: str
    ) -> FlowVersionOut:
        """Den **einen** globalen Flow speichern.

        Es gibt **genau einen** Flow — **keine Versionen**: dieselbe ``flow_version``-
        Zeile wird in-place überschrieben (States/Transitions ersetzt). Alle Anträge
        (auch laufende) bleiben darauf gepinnt; ihr aktueller State wird per KEY auf den
        neuen Graphen gemappt — **gelöschte States ⇒ Initial-State**. Der Graph muss
        genau einen Initial-State haben (``validate_flow_graph``)."""
        from app.modules.applications.models import Application, StatusEvent

        try:
            validate_flow_graph(payload.graph)
        except FlowValidationError as exc:
            raise ValidationProblem(
                "Invalid flow graph.", errors=[{"field": "graph", "msg": str(exc)}]
            ) from exc

        # Aktuellen State je Antrag (per KEY) merken, bevor die alten States fallen.
        app_keys = {
            app_id: key
            for app_id, key in (
                await self.session.execute(
                    select(Application.id, State.key).join(
                        State, State.id == Application.current_state_id
                    )
                )
            ).all()
        }

        # Den einen globalen Flow wiederverwenden (oder einmalig anlegen).
        version = (
            await self.session.execute(
                select(FlowVersion)
                .order_by(FlowVersion.active.desc(), FlowVersion.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if version is None:
            version = FlowVersion(
                version=1, active=True,
                editor_layout=payload.graph.layout or {},
            )
            self.session.add(version)
            await self.session.flush()
        else:
            version.active = True
            version.editor_layout = payload.graph.layout or {}
        # Etwaige Alt-Versionen deaktivieren — es bleibt genau eine aktiv.
        await self.session.execute(
            update(FlowVersion)
            .where(FlowVersion.id != version.id)
            .values(active=False)
        )

        # States per KEY upserten: überlebende Keys behalten ihre id, damit die
        # Timeline (status_event) und current_state-Referenzen gültig bleiben — nur
        # wirklich entfernte States werden gelöscht (siehe unten).
        existing_states = (
            await self.session.execute(
                select(State).where(State.flow_version_id == version.id)
            )
        ).scalars().all()
        existing_by_key = {s.key: s for s in existing_states}
        incoming_keys = {s.key for s in payload.graph.states}

        id_by_key: dict[str, UUID] = {}
        initial_id: UUID | None = None
        for state in payload.graph.states:
            row = existing_by_key.get(state.key)
            if row is None:
                row = State(flow_version_id=version.id, key=state.key)
                self.session.add(row)
            row.label_i18n = state.label
            row.color = state.color
            row.edit_allowed = state.edit_allowed
            row.is_initial = state.is_initial
            row.kind = state.kind
            row.config = state.config
            await self.session.flush()
            id_by_key[state.key] = row.id
            if state.is_initial:
                initial_id = row.id

        removed_ids = [s.id for s in existing_states if s.key not in incoming_keys]

        # Transitions komplett neu bauen. status_event.transition_id vorher lösen,
        # sonst blockiert deren FK das Löschen (Timeline behält from/to + Notiz).
        old_transition_ids = (
            await self.session.execute(
                select(Transition.id).where(Transition.flow_version_id == version.id)
            )
        ).scalars().all()
        if old_transition_ids:
            await self.session.execute(
                update(StatusEvent)
                .where(StatusEvent.transition_id.in_(old_transition_ids))
                .values(transition_id=None)
            )
            await self.session.execute(
                delete(Transition).where(Transition.flow_version_id == version.id)
            )
            await self.session.flush()
        for order, trans in enumerate(payload.graph.transitions):
            self.session.add(
                Transition(
                    flow_version_id=version.id,
                    from_state_id=id_by_key[trans.from_],
                    to_state_id=id_by_key[trans.to],
                    label_i18n=trans.label or {},
                    color=trans.color,
                    guard=trans.guard,
                    actions=trans.actions,
                    order=trans.order if trans.order is not None else order,
                    automatic=trans.automatic,
                    branch=trans.branch,
                    requires_action=trans.requires_action,
                )
            )

        # ALLE Anträge auf den einen Flow ziehen; gelöschter State ⇒ Initial
        # (per KEY gemappt, deckt auch Anträge alter Versionen ab).
        for app_id, key in app_keys.items():
            await self.session.execute(
                update(Application)
                .where(Application.id == app_id)
                .values(
                    current_state_id=id_by_key.get(key, initial_id),
                    flow_version_id=version.id,
                )
            )
        # Anträge ohne (gemappten) State → Initial-State.
        await self.session.execute(
            update(Application)
            .where(Application.current_state_id.is_(None))
            .values(current_state_id=initial_id, flow_version_id=version.id)
        )

        # Entfernte States: Timeline-Referenzen auf Initial umbiegen, dann löschen.
        # (current_state-Referenzen sind durch das Remapping oben bereits weg.)
        if removed_ids:
            await self.session.execute(
                update(StatusEvent)
                .where(StatusEvent.from_state_id.in_(removed_ids))
                .values(from_state_id=initial_id)
            )
            await self.session.execute(
                update(StatusEvent)
                .where(StatusEvent.to_state_id.in_(removed_ids))
                .values(to_state_id=initial_id)
            )
            await self.session.flush()
            await self.session.execute(delete(State).where(State.id.in_(removed_ids)))
            await self.session.flush()

        await self._audit(
            actor, AuditAction.CONFIG_ACTIVATION, "flow_version", version.id,
            {"global": True},
        )
        await self.session.commit()
        return FlowVersionOut(
            id=version.id,
            version=version.version,
            active=True,
        )

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

    async def delete_role(self, role_id: UUID, actor: str) -> None:
        """Rolle löschen (#38). ``admin``/``member`` sind geschützt (nicht löschbar).

        Zuweisungen + Permissions kaskadieren (FK ``ON DELETE CASCADE``). Idempotent:
        unbekannte id → 404.
        """
        role = await self.session.get(Role, role_id)
        if role is None:
            raise NotFoundError(f"role {role_id} not found")
        if role.key in ("admin", "member"):
            raise ConflictError(f"role {role.key!r} is protected and cannot be deleted")
        await self._audit(actor, AuditAction.ROLE_CHANGE, "role", role.id)
        await self.session.delete(role)
        await self.session.commit()

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
            # Selbst-Aussperrung verhindern (#40): den eigenen Admin nicht auf eine
            # andere Rolle umschreiben.
            if payload.role_id != row.role_id:
                await self._guard_self_admin_removal(row, actor)
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
        # Selbst-Aussperrung verhindern (#40): den eigenen Admin nicht entziehen.
        await self._guard_self_admin_removal(row, actor)
        # Basisrolle member ist unentziehbar (#61): jeder Benutzer behält sie immer.
        role = await self.session.get(Role, row.role_id)
        if role is not None and role.key == "member" and row.gremium_id is None:
            raise ConflictError("the member role cannot be removed")
        await self.session.delete(row)
        await self._audit(actor, AuditAction.ROLE_CHANGE, "role_assignment", assignment_id)
        await self.session.commit()

    async def _guard_self_admin_removal(
        self, row: RoleAssignmentRow, actor: str
    ) -> None:
        """Verhindert, dass ein Admin sich selbst die Admin-Rolle entzieht (#40).

        ``actor`` ist der OIDC-``sub``; eine Admin-Zuweisung des eigenen Principals
        darf nicht gelöscht/umgeschrieben werden (Selbst-Aussperrung)."""
        role = await self.session.get(Role, row.role_id)
        if role is None or role.key != "admin":
            return
        principal = await self.session.get(Principal, row.principal_id)
        if principal is not None and principal.sub == actor:
            raise ConflictError("admins cannot remove their own admin role")

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

    async def set_principal_active(
        self, principal_id: UUID, active: bool, actor: str
    ) -> PrincipalOut:
        """Benutzer aktivieren/deaktivieren (#30). 404 bei unbekannter id.

        Selbst-Aussperrung verhindern (#44): den eigenen Account nicht deaktivieren
        (``actor`` ist der OIDC-``sub``)."""
        principal = await self.session.get(Principal, principal_id)
        if principal is None:
            raise NotFoundError(f"principal {principal_id} not found")
        if not active and principal.sub == actor:
            raise ConflictError("you cannot deactivate your own account")
        principal.active = active
        await self._audit(actor, AuditAction.ROLE_CHANGE, "principal", principal.id)
        await self.session.commit()
        assignments = (
            await self.session.scalars(
                select(RoleAssignmentRow).where(
                    RoleAssignmentRow.principal_id == principal_id
                )
            )
        ).all()
        return _principal_out(principal, list(assignments))

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
        allow_vote_delegation=row.allow_vote_delegation,
        delegation_lead_minutes=row.delegation_lead_minutes,
        delegation_allow_external=row.delegation_allow_external,
        quorum_percent=row.quorum_percent,
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
        active=True if row.active is None else row.active,
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
