"""Delegation-Service (#delegation-rework) — Sicherheitskern.

Eine Delegation ist **sitzungsgebunden** (``meeting_delegation``): genau eine
ausgehende Vertretung je (Sitzung, Mitglied), Gremium = Gremium der Sitzung,
optional mit Stimmrecht (exklusiver **Transfer**, kein Duplikat). Das frühere
Blanko-Zeitraum-Modell (``role_assignment.delegated_by``, T-45) ist abgelöst;
Alt-Zeilen bleiben für den RBAC-Resolver gültig, zählen aber **nicht** mehr für
das Stimmrecht.

Serverseitig erzwungene Invarianten:

* **Feature-Gates:** Sitzungs-Delegation nur, wenn das Gremium sie erlaubt
  (``allow_vote_delegation``); ``delegate_voting`` zusätzlich nur bei global
  freigeschaltetem Stimmrecht-Transfer (``delegation_voting_enabled``, 422).
* **Nur eigene Stimme:** der Delegierende muss selbst stimmberechtigtes Mitglied
  des Sitzungs-Gremiums sein (Gremium-Rolle mit ``vote.cast``, direktes
  Assignment oder OIDC-/Group-Mapping) — sonst 403.
* **Keine Ketten:** pro Sitzung tritt ein Principal entweder als Delegierender
  ODER als Empfänger auf, nie beides (422).
* **Empfänger-Kreis:** Gremium-Mitglieder und der Stellvertreter-Pool sind immer
  wählbar; sonstige Nutzer nur bei ``delegation_allow_external`` (403).
* **Deadline:** Nicht-Pool-Delegationen bis ``Sitzungsbeginn − delegation_lead_
  minutes`` (Gremium-Config); Pool-Delegationen bis Sitzungsbeginn. Immer nur
  solange die Sitzung ``planned`` ist (422). Widerruf bis Sitzungsbeginn.
* **Transfer ≠ Duplikat:** höchstens eine Stimm-Delegation je (Sitzung,
  Empfänger) (409); der Delegierende ist für Votes der Sitzung gesperrt
  (:func:`voting_delegation_check`, Nutzung wird auditiert).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import time as _time
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.gremium_roles import gremium_ids_with_permission
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import GroupMapping, RoleAssignment
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import DelegationSubstitute, MeetingDelegation
from app.modules.delegations.schemas import (
    DelegationCreate,
    DelegationOut,
    MeetingDelegationContext,
    RecipientOut,
    SubstituteCreate,
    SubstituteOut,
    VoteDelegationStatus,
)
from app.modules.livevote.models import Meeting
from app.modules.voting.models import Vote
from app.settings import Settings
from app.shared.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationProblem,
)

# Permission, die die volle (fremde) Delegations-Sicht/-Verwaltung freischaltet.
_ADMIN_PERM = "admin.roles"
# Gremium-Rollen-Permission, die den Stellvertreter-Pool pflegen darf.
_POOL_MANAGE_PERM = "session.manage"


def meeting_start_utc(meeting: Meeting, tz_name: str) -> datetime | None:
    """Sitzungsbeginn als aware-UTC; ``None`` wenn die Sitzung kein Datum hat.

    ``meeting.date``/``start_time`` sind naiv gespeichert und meinen lokale Zeit
    (``settings.local_timezone``); ohne Uhrzeit gilt Tagesbeginn (00:00 lokal).
    """
    if meeting.date is None:
        return None
    local = datetime.combine(meeting.date, meeting.start_time or _time(0, 0))
    return local.replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC)


async def _membership_with_vote_cast(
    session: AsyncSession, principal_id: UUID, gremium_id: UUID, now: datetime
) -> bool:
    """Aktive Gremium-Mitgliedschaft, deren Rolle ``vote.cast`` gewährt."""
    rows = (
        await session.execute(
            select(GremiumRole.permissions)
            .select_from(GremiumMembership)
            .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
            .where(
                GremiumMembership.principal_id == principal_id,
                GremiumMembership.gremium_id == gremium_id,
                (GremiumMembership.valid_from.is_(None))
                | (GremiumMembership.valid_from <= now),
                (GremiumMembership.valid_until.is_(None))
                | (GremiumMembership.valid_until > now),
            )
        )
    ).scalars().all()
    return any("vote.cast" in (perms or []) for perms in rows)


async def _independently_eligible(
    session: AsyncSession, principal_id: UUID, gremium_id: UUID, now: datetime
) -> bool:
    """Eigenständig stimmberechtigt im Gremium — **ohne** Delegationen.

    Quellen wie der RBAC-Resolver: Gremium-Rolle mit ``vote.cast``, direkt
    gehaltenes ``role_assignment`` mit Gremium-Scope, OIDC-Gruppe (direkt oder via
    ``group_mapping``).
    """
    if await _membership_with_vote_cast(session, principal_id, gremium_id, now):
        return True
    direct = (
        await session.execute(
            select(RoleAssignment.id)
            .where(
                RoleAssignment.principal_id == principal_id,
                RoleAssignment.delegated_by.is_(None),
                RoleAssignment.gremium_id == gremium_id,
                (RoleAssignment.valid_from.is_(None))
                | (RoleAssignment.valid_from <= now),
                (RoleAssignment.valid_until.is_(None))
                | (RoleAssignment.valid_until >= now),
            )
            .limit(1)
        )
    ).first()
    if direct is not None:
        return True
    row = (
        await session.execute(
            select(PrincipalRow.oidc_groups).where(PrincipalRow.id == principal_id)
        )
    ).first()
    oidc = {str(g) for g in ((row[0] if row else None) or [])}
    if str(gremium_id) in oidc:
        return True
    if not oidc:
        return False
    mapped = (
        await session.execute(
            select(GroupMapping.id)
            .where(
                GroupMapping.gremium_id == gremium_id,
                GroupMapping.oidc_group.in_(oidc),
            )
            .limit(1)
        )
    ).first()
    return mapped is not None


async def voting_delegation_check(
    session: AsyncSession,
    sub: str,
    meeting_id: UUID | None,
    eligible_group: str,
    now: datetime,  # noqa: ARG001 — Signatur-Konsistenz; Delegationen sind sitzungsgebunden
) -> tuple[bool, bool]:
    """Zwei-seitiges Stimmrecht-Verdikt für ``sub`` → ``(blocked, exercised)``.

    Sitzungsgebunden: nur ``meeting_delegation``-Zeilen **dieser** Sitzung zählen,
    und nur wenn das Vote-Gremium (``eligible_group`` = ``str(gremium_id)``) zum
    Delegations-Gremium passt. Votes ohne Sitzung kennen keine Delegation.

    * ausgehende Zeile mit ``delegate_voting`` → **blocked** (Transfer: nur der
      Empfänger stimmt).
    * eingehende Zeile mit ``delegate_voting`` → **exercised** (Nutzungs-Audit;
      macht einen externen Empfänger stimmberechtigt).
    """
    if meeting_id is None:
        return False, False
    try:
        gremium_id = UUID(eligible_group)
    except (ValueError, TypeError):
        return False, False
    pid_subq = select(PrincipalRow.id).where(PrincipalRow.sub == sub).scalar_subquery()
    rows = (
        await session.execute(
            select(
                MeetingDelegation.delegator_principal_id == pid_subq,
                MeetingDelegation.delegate_voting,
            ).where(
                MeetingDelegation.meeting_id == meeting_id,
                MeetingDelegation.gremium_id == gremium_id,
                or_(
                    MeetingDelegation.delegator_principal_id == pid_subq,
                    MeetingDelegation.delegate_principal_id == pid_subq,
                ),
            )
        )
    ).all()
    blocked = any(is_delegator and voting for is_delegator, voting in rows)
    exercised = any(not is_delegator and voting for is_delegator, voting in rows)
    return blocked, exercised


class DelegationService:
    """An eine ``AsyncSession`` + ``Settings`` gebundener Delegations-Service."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    # ----------------------------------------------------------------- helpers
    async def _principal_row(
        self, *, sub: str | None = None, pid: UUID | None = None
    ) -> PrincipalRow | None:
        stmt = select(PrincipalRow)
        stmt = stmt.where(PrincipalRow.sub == sub) if sub is not None else stmt.where(
            PrincipalRow.id == pid
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _names(self, ids: set[UUID]) -> dict[UUID, str | None]:
        if not ids:
            return {}
        rows = (
            await self.session.execute(
                select(
                    PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email
                ).where(PrincipalRow.id.in_(ids))
            )
        ).all()
        return {pid: (name or email) for pid, name, email in rows}

    async def _meeting(self, meeting_id: UUID) -> Meeting:
        meeting = await self.session.get(Meeting, meeting_id)
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def _gremium(self, gremium_id: UUID) -> Gremium:
        gremium = await self.session.get(Gremium, gremium_id)
        if gremium is None:
            raise NotFoundError(f"gremium {gremium_id} not found")
        return gremium

    async def _pool_substitute_ids(
        self, gremium_id: UUID, member_id: UUID
    ) -> set[UUID]:
        """Pool-Empfänger für ``member_id``: persönliche + gremium-weite Einträge."""
        rows = (
            await self.session.execute(
                select(DelegationSubstitute.substitute_principal_id).where(
                    DelegationSubstitute.gremium_id == gremium_id,
                    or_(
                        DelegationSubstitute.member_principal_id.is_(None),
                        DelegationSubstitute.member_principal_id == member_id,
                    ),
                )
            )
        ).scalars().all()
        return set(rows)

    async def _member_ids(self, gremium_id: UUID, now: datetime) -> set[UUID]:
        """Aktive Gremium-Mitglieder (beliebige Rolle)."""
        rows = (
            await self.session.execute(
                select(GremiumMembership.principal_id).where(
                    GremiumMembership.gremium_id == gremium_id,
                    (GremiumMembership.valid_from.is_(None))
                    | (GremiumMembership.valid_from <= now),
                    (GremiumMembership.valid_until.is_(None))
                    | (GremiumMembership.valid_until > now),
                )
            )
        ).scalars().all()
        return set(rows)

    def _revocable(self, meeting: Meeting, now: datetime) -> bool:
        if meeting.status != "planned":
            return False
        start = meeting_start_utc(meeting, self.settings.local_timezone)
        return start is None or now < start

    @staticmethod
    def _direction(d: MeetingDelegation, me_id: UUID | None) -> str | None:
        if me_id is None:
            return None
        if d.delegator_principal_id == me_id:
            return "outgoing"
        if d.delegate_principal_id == me_id:
            return "incoming"
        return None

    async def _out(
        self,
        rows: list[tuple[MeetingDelegation, Meeting, Gremium]],
        now: datetime,
        me_id: UUID | None = None,
    ) -> list[DelegationOut]:
        ids: set[UUID] = set()
        for d, _, _ in rows:
            ids.add(d.delegator_principal_id)
            ids.add(d.delegate_principal_id)
        names = await self._names(ids)
        return [
            DelegationOut(
                id=d.id,
                meeting_id=d.meeting_id,
                meeting_title=meeting.title,
                meeting_date=meeting.date.isoformat() if meeting.date else None,
                gremium_id=d.gremium_id,
                gremium_name=gremium.name,
                delegator_id=d.delegator_principal_id,
                delegator_name=names.get(d.delegator_principal_id),
                delegate_id=d.delegate_principal_id,
                delegate_name=names.get(d.delegate_principal_id),
                delegate_voting=d.delegate_voting,
                via_pool=d.via_pool,
                # Frisch eingefügte Zeile: ``created_at`` füllt erst der DB-Default
                # (server_default) — bis zum Re-Select gilt der Anlege-Zeitpunkt.
                created_at=d.created_at or now,
                revocable=self._revocable(meeting, now),
                direction=self._direction(d, me_id),
            )
            for d, meeting, gremium in rows
        ]

    async def _joined(self, *where) -> list[tuple[MeetingDelegation, Meeting, Gremium]]:  # noqa: ANN002
        rows = (
            await self.session.execute(
                select(MeetingDelegation, Meeting, Gremium)
                .join(Meeting, Meeting.id == MeetingDelegation.meeting_id)
                .join(Gremium, Gremium.id == MeetingDelegation.gremium_id)
                .where(*where)
                .order_by(MeetingDelegation.created_at.desc())
            )
        ).all()
        return [(d, m, g) for d, m, g in rows]

    # ------------------------------------------------------------------ create
    async def create(self, payload: DelegationCreate, actor: Principal) -> DelegationOut:
        """Sitzungs-Delegation anlegen. 403 (Gate/Empfänger-Kreis/kein Stimmrecht),
        404 (Sitzung/Empfänger), 409 (Doppel), 422 (Fenster/Ketten/Selbst)."""
        now = datetime.now(UTC)
        meeting = await self._meeting(payload.meeting_id)
        gremium = await self._gremium(meeting.gremium_id)

        if not gremium.allow_vote_delegation:
            raise ForbiddenError("Delegation is not enabled for this gremium.")
        if payload.delegate_voting and not self.settings.delegation_voting_enabled:
            raise ValidationProblem(
                "Voting-right delegation is disabled.",
                errors=[{"field": "delegateVoting", "msg": "disabled by configuration"}],
            )
        if meeting.status != "planned":
            raise ValidationProblem(
                "Meeting has already started.",
                errors=[{"field": "meetingId", "msg": "meeting is not planned"}],
            )

        me = await self._principal_row(sub=actor.sub)
        if me is None:
            raise ForbiddenError("Delegator principal not found.")
        delegate = await self._principal_row(pid=payload.delegate_id)
        if delegate is None:
            raise NotFoundError(f"principal {payload.delegate_id} not found")
        if delegate.id == me.id:
            raise ValidationProblem(
                "Cannot delegate to yourself.",
                errors=[{"field": "delegateId", "msg": "must differ from delegator"}],
            )

        # Nur die eigene Stimme ist delegierbar: der Delegierende muss eigenständig
        # stimmberechtigtes Mitglied des Sitzungs-Gremiums sein.
        if not await _independently_eligible(self.session, me.id, gremium.id, now):
            raise ForbiddenError(
                "Only voting members of the meeting's gremium may delegate."
            )

        # Empfänger-Kreis: Mitglied | Pool | extern (nur wenn freigeschaltet).
        pool_ids = await self._pool_substitute_ids(gremium.id, me.id)
        member_ids = await self._member_ids(gremium.id, now)
        via_pool = delegate.id in pool_ids
        if (
            not via_pool
            and delegate.id not in member_ids
            and not gremium.delegation_allow_external
        ):
            raise ForbiddenError(
                "Recipient must be a gremium member or a designated substitute."
            )

        # Deadline: Pool bis Sitzungsbeginn, sonst Beginn − Vorlauf (Gremium-Config).
        start = meeting_start_utc(meeting, self.settings.local_timezone)
        if start is not None:
            deadline = (
                start
                if via_pool
                else start - timedelta(minutes=gremium.delegation_lead_minutes)
            )
            if now >= deadline:
                raise ValidationProblem(
                    "Delegation deadline for this meeting has passed.",
                    errors=[{"field": "meetingId", "msg": "deadline passed"}],
                )

        # Keine Ketten: je Sitzung ist man entweder Delegierender oder Empfänger.
        existing = (
            await self.session.execute(
                select(
                    MeetingDelegation.delegator_principal_id,
                    MeetingDelegation.delegate_principal_id,
                    MeetingDelegation.delegate_voting,
                ).where(MeetingDelegation.meeting_id == meeting.id)
            )
        ).all()
        for delegator_id, delegate_id, voting in existing:
            if delegator_id == me.id:
                raise ConflictError(
                    "You already delegated for this meeting.", code="conflict"
                )
            if delegate_id == me.id:
                raise ValidationProblem(
                    "You receive a delegation for this meeting and cannot delegate on.",
                    errors=[{"field": "meetingId", "msg": "no re-delegation chains"}],
                )
            if delegator_id == delegate.id:
                raise ValidationProblem(
                    "Recipient has delegated their own vote for this meeting.",
                    errors=[{"field": "delegateId", "msg": "no re-delegation chains"}],
                )
            if payload.delegate_voting and voting and delegate_id == delegate.id:
                raise ConflictError(
                    "Recipient already carries a delegated vote for this meeting.",
                    code="conflict",
                )

        row = MeetingDelegation(
            meeting_id=meeting.id,
            gremium_id=gremium.id,
            delegator_principal_id=me.id,
            delegate_principal_id=delegate.id,
            delegate_voting=payload.delegate_voting,
            via_pool=via_pool,
            created_by=actor.sub,
        )
        self.session.add(row)
        await self.session.flush()
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_GRANT,
            target_type="meeting_delegation",
            target_id=str(row.id),
            data={
                "meetingId": str(meeting.id),
                "gremiumId": str(gremium.id),
                "delegateId": str(delegate.id),
                "delegateVoting": payload.delegate_voting,
                "viaPool": via_pool,
            },
        )
        await self.session.commit()
        return (await self._out([(row, meeting, gremium)], now, me.id))[0]

    # -------------------------------------------------------------------- list
    async def list(
        self, actor: Principal, meeting_id: UUID | None = None
    ) -> list[DelegationOut]:
        """Eigene (ausgehende **und** eingehende) Delegationen; Admins alle."""
        now = datetime.now(UTC)
        me = await self._principal_row(sub=actor.sub)
        where = []
        if meeting_id is not None:
            where.append(MeetingDelegation.meeting_id == meeting_id)
        if not actor.has(_ADMIN_PERM):
            if me is None:
                return []
            where.append(
                or_(
                    MeetingDelegation.delegator_principal_id == me.id,
                    MeetingDelegation.delegate_principal_id == me.id,
                )
            )
        return await self._out(
            await self._joined(*where), now, me.id if me else None
        )

    # ------------------------------------------------------------------ revoke
    async def revoke(self, delegation_id: UUID, actor: Principal) -> None:
        """Delegation widerrufen (Hard-Delete → sofort wirksam). 404/403/422.

        Delegierender: bis Sitzungsbeginn (Sitzung ``planned``). Admin: immer.
        """
        row = await self.session.get(MeetingDelegation, delegation_id)
        if row is None:
            raise NotFoundError(f"delegation {delegation_id} not found")
        me = await self._principal_row(sub=actor.sub)
        is_owner = me is not None and row.delegator_principal_id == me.id
        if not is_owner and not actor.has(_ADMIN_PERM):
            raise ForbiddenError("Only the delegator (or an admin) may revoke.")
        if not actor.has(_ADMIN_PERM):
            meeting = await self._meeting(row.meeting_id)
            if not self._revocable(meeting, datetime.now(UTC)):
                raise ValidationProblem(
                    "Meeting has already started; delegation can no longer be revoked.",
                    errors=[{"field": "id", "msg": "meeting started"}],
                )
        await self.session.delete(row)
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_REVOKE,
            target_type="meeting_delegation",
            target_id=str(delegation_id),
            data={"meetingId": str(row.meeting_id)},
        )
        await self.session.commit()

    # --------------------------------------------------------- meeting context
    async def meeting_context(
        self, meeting_id: UUID, actor: Principal
    ) -> MeetingDelegationContext:
        """Kontext für den »Vertretung einrichten«-Dialog einer Sitzung."""
        now = datetime.now(UTC)
        meeting = await self._meeting(meeting_id)
        gremium = await self._gremium(meeting.gremium_id)
        me = await self._principal_row(sub=actor.sub)

        start = meeting_start_utc(meeting, self.settings.local_timezone)
        deadline = (
            start - timedelta(minutes=gremium.delegation_lead_minutes)
            if start is not None
            else None
        )
        meeting_started = meeting.status != "planned" or (
            start is not None and now >= start
        )

        my_delegation: DelegationOut | None = None
        incoming: list[DelegationOut] = []
        recipients: list[RecipientOut] = []
        can_delegate = False
        if me is not None:
            can_delegate = gremium.allow_vote_delegation and await _independently_eligible(
                self.session, me.id, gremium.id, now
            )
            rows = await self._joined(
                MeetingDelegation.meeting_id == meeting.id,
                or_(
                    MeetingDelegation.delegator_principal_id == me.id,
                    MeetingDelegation.delegate_principal_id == me.id,
                ),
            )
            outs = await self._out(rows, now, me.id)
            for (d, _, _), out in zip(rows, outs, strict=True):
                if d.delegator_principal_id == me.id:
                    my_delegation = out
                else:
                    incoming.append(out)

            member_ids = await self._member_ids(gremium.id, now)
            pool_ids = await self._pool_substitute_ids(gremium.id, me.id)
            ids = (member_ids | pool_ids) - {me.id}
            names = await self._names(ids)
            recipients = sorted(
                (
                    RecipientOut(
                        principal_id=pid,
                        display_name=names.get(pid),
                        via_pool=pid in pool_ids,
                        is_member=pid in member_ids,
                    )
                    for pid in ids
                ),
                key=lambda r: (not r.via_pool, (r.display_name or "").lower()),
            )

        return MeetingDelegationContext(
            meeting_id=meeting.id,
            gremium_id=gremium.id,
            allow_vote_delegation=gremium.allow_vote_delegation,
            voting_delegation_enabled=self.settings.delegation_voting_enabled,
            delegation_allow_external=gremium.delegation_allow_external,
            deadline=deadline,
            deadline_passed=deadline is not None and now >= deadline,
            meeting_started=meeting_started,
            can_delegate=can_delegate,
            my_delegation=my_delegation,
            incoming=incoming,
            recipients=recipients,
        )

    # -------------------------------------------------------------- recipients
    async def recipients(
        self, meeting_id: UUID, q: str, actor: Principal
    ) -> list[RecipientOut]:
        """Typeahead: erlaubte Empfänger; bei ``delegation_allow_external``
        zusätzlich plattformweite Suche nach Name/Mail."""
        now = datetime.now(UTC)
        meeting = await self._meeting(meeting_id)
        gremium = await self._gremium(meeting.gremium_id)
        me = await self._principal_row(sub=actor.sub)
        if me is None:
            return []
        member_ids = await self._member_ids(gremium.id, now)
        pool_ids = await self._pool_substitute_ids(gremium.id, me.id)
        ids = (member_ids | pool_ids) - {me.id}
        names = await self._names(ids)
        needle = q.strip().lower()
        out = [
            RecipientOut(
                principal_id=pid,
                display_name=names.get(pid),
                via_pool=pid in pool_ids,
                is_member=pid in member_ids,
            )
            for pid in ids
            if not needle or needle in (names.get(pid) or "").lower()
        ]
        if gremium.delegation_allow_external and needle:
            rows = (
                await self.session.execute(
                    select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email)
                    .where(
                        PrincipalRow.active.is_(True),
                        or_(
                            PrincipalRow.display_name.ilike(f"%{needle}%"),
                            PrincipalRow.email.ilike(f"%{needle}%"),
                        ),
                    )
                    .limit(10)
                )
            ).all()
            seen = {r.principal_id for r in out} | {me.id}
            out.extend(
                RecipientOut(
                    principal_id=pid,
                    display_name=name or email,
                    via_pool=False,
                    is_member=False,
                )
                for pid, name, email in rows
                if pid not in seen
            )
        out.sort(key=lambda r: (not r.via_pool, not r.is_member, (r.display_name or "").lower()))
        return out[:20]

    # ------------------------------------------------------------- vote status
    async def vote_status(self, vote_id: UUID, actor: Principal) -> VoteDelegationStatus:
        """Delegations-Sicht des Aufrufers auf eine Abstimmung (FE-Banner)."""
        vote = await self.session.get(Vote, vote_id)
        if vote is None:
            raise NotFoundError(f"vote {vote_id} not found")
        empty = VoteDelegationStatus(blocked=False, exercising=False)
        if vote.meeting_id is None:
            return empty
        me = await self._principal_row(sub=actor.sub)
        if me is None:
            return empty
        try:
            gremium_id = UUID(vote.eligible_group)
        except (ValueError, TypeError):
            return empty
        rows = (
            await self.session.execute(
                select(MeetingDelegation).where(
                    MeetingDelegation.meeting_id == vote.meeting_id,
                    MeetingDelegation.gremium_id == gremium_id,
                    MeetingDelegation.delegate_voting.is_(True),
                    or_(
                        MeetingDelegation.delegator_principal_id == me.id,
                        MeetingDelegation.delegate_principal_id == me.id,
                    ),
                )
            )
        ).scalars().all()
        blocked = False
        exercising = False
        delegated_to: UUID | None = None
        delegated_by: UUID | None = None
        for d in rows:
            if d.delegator_principal_id == me.id:
                blocked = True
                delegated_to = d.delegate_principal_id
            else:
                exercising = True
                delegated_by = d.delegator_principal_id
        names = await self._names({i for i in (delegated_to, delegated_by) if i})
        return VoteDelegationStatus(
            blocked=blocked,
            delegated_to_name=names.get(delegated_to) if delegated_to else None,
            exercising=exercising,
            delegated_by_name=names.get(delegated_by) if delegated_by else None,
        )

    # ------------------------------------------------------- substitute pool
    async def _require_pool_manage(self, gremium_id: UUID, actor: Principal) -> None:
        if actor.has(_ADMIN_PERM):
            return
        allowed = await gremium_ids_with_permission(
            self.session, actor.sub, _POOL_MANAGE_PERM
        )
        if gremium_id not in allowed:
            raise ForbiddenError("Managing the substitute pool requires admin.roles "
                                 "or the gremium's session.manage permission.")

    async def substitutes_list(
        self, gremium_id: UUID, _actor: Principal
    ) -> list[SubstituteOut]:
        """Pool eines Gremiums — sichtbar für jeden eingeloggten Nutzer
        (Empfänger-Wahl; Pflege ist separat gegatet)."""
        await self._gremium(gremium_id)
        rows = (
            await self.session.execute(
                select(DelegationSubstitute)
                .where(DelegationSubstitute.gremium_id == gremium_id)
                .order_by(DelegationSubstitute.created_at)
            )
        ).scalars().all()
        ids: set[UUID] = set()
        for r in rows:
            ids.add(r.substitute_principal_id)
            if r.member_principal_id is not None:
                ids.add(r.member_principal_id)
        names = await self._names(ids)
        return [
            SubstituteOut(
                id=r.id,
                gremium_id=r.gremium_id,
                member_id=r.member_principal_id,
                member_name=names.get(r.member_principal_id)
                if r.member_principal_id
                else None,
                substitute_id=r.substitute_principal_id,
                substitute_name=names.get(r.substitute_principal_id),
            )
            for r in rows
        ]

    async def substitute_create(
        self, payload: SubstituteCreate, actor: Principal
    ) -> SubstituteOut:
        """Pool-Eintrag anlegen — ``admin.roles`` oder Gremium-``session.manage``."""
        await self._require_pool_manage(payload.gremium_id, actor)
        await self._gremium(payload.gremium_id)
        substitute = await self._principal_row(pid=payload.substitute_id)
        if substitute is None:
            raise NotFoundError(f"principal {payload.substitute_id} not found")
        if payload.member_id is not None:
            member = await self._principal_row(pid=payload.member_id)
            if member is None:
                raise NotFoundError(f"principal {payload.member_id} not found")
            if member.id == substitute.id:
                raise ValidationProblem(
                    "Substitute must differ from the member.",
                    errors=[{"field": "substituteId", "msg": "must differ from member"}],
                )
        dup = (
            await self.session.execute(
                select(DelegationSubstitute.id).where(
                    DelegationSubstitute.gremium_id == payload.gremium_id,
                    DelegationSubstitute.substitute_principal_id == substitute.id,
                    DelegationSubstitute.member_principal_id.is_(None)
                    if payload.member_id is None
                    else DelegationSubstitute.member_principal_id == payload.member_id,
                )
            )
        ).first()
        if dup is not None:
            raise ConflictError("Substitute entry already exists.", code="conflict")
        row = DelegationSubstitute(
            gremium_id=payload.gremium_id,
            member_principal_id=payload.member_id,
            substitute_principal_id=substitute.id,
            created_by=actor.sub,
        )
        self.session.add(row)
        await self.session.flush()
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_SUBSTITUTE_ADD,
            target_type="delegation_substitute",
            target_id=str(row.id),
            data={
                "gremiumId": str(payload.gremium_id),
                "memberId": str(payload.member_id) if payload.member_id else None,
                "substituteId": str(substitute.id),
            },
        )
        await self.session.commit()
        names = await self._names(
            {substitute.id} | ({payload.member_id} if payload.member_id else set())
        )
        return SubstituteOut(
            id=row.id,
            gremium_id=row.gremium_id,
            member_id=row.member_principal_id,
            member_name=names.get(row.member_principal_id)
            if row.member_principal_id
            else None,
            substitute_id=row.substitute_principal_id,
            substitute_name=names.get(row.substitute_principal_id),
        )

    async def substitute_delete(self, substitute_id: UUID, actor: Principal) -> None:
        """Pool-Eintrag löschen — gleiche Rechte wie Anlegen."""
        row = await self.session.get(DelegationSubstitute, substitute_id)
        if row is None:
            raise NotFoundError(f"substitute {substitute_id} not found")
        await self._require_pool_manage(row.gremium_id, actor)
        await self.session.delete(row)
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_SUBSTITUTE_REMOVE,
            target_type="delegation_substitute",
            target_id=str(substitute_id),
            data={"gremiumId": str(row.gremium_id)},
        )
        await self.session.commit()
