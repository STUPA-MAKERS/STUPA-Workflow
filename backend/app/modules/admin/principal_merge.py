"""Account merge: merge an old principal into a new one ("Konten zusammenführen").

The OIDC provider moved from Keycloak to authentik. Each principal from the Keycloak
time has an old ``sub``, so the history shows one person as two people. An admin with
``admin.users.merge`` merges the old principal (the source) into the new one (the
target):

- ``preview`` counts per area what the merge rewrites, combines and removes, and lists
  the real conflicts. It writes nothing.
- ``merge`` runs the same checks under row locks and applies the merge in ONE
  transaction. A real conflict refuses the whole merge with 409 ``merge_conflict``.

What the merge does with each reference:

- It rewrites every column that stores the ``sub`` or the id of the source to the target.
  That covers applications (creator, archiver, capturer, share links), versions, the timeline,
  comments, ballots and the voted markers of secret votes, delegations, the substitute
  pool, attendance, meetings (creator, minute-taker, keeper periods), protocols, budget
  bookings and invoices, config versions, role assignments, privacy requests, backups,
  the stored audit checks, tickets (with the mentions of the notes) and to-dos (cards,
  comments with their mentions, events, links). The mentions of the application
  comments move too.
- It moves the personal to-do board of the source to the target. When the target has
  one already, the cards of the source board move into it (``todos/merge.py``).
- It combines harmless duplicates: a notification preference, a pool entry, an
  equal attendance or a to-do assignment that the target already has. The row
  of the target wins, the row of the source goes. A pool entry in which one account
  substitutes for the other goes too, because a person never substitutes for themselves.
- It removes the sessions and the OAuth codes and tokens of the source, its feed token,
  its role assignments and its gremium memberships. Rights never move: the roles come
  from the OIDC group mappings and the bootstrap, so the target gets its own at its
  next login. The memberships come from the OIDC groups only, so the
  target keeps its own and the next login of the target syncs them again.
- It never touches the audit log (append-only and hash-chained) or the config
  revisions (append-only). Their displays resolve the old ``sub`` through
  ``principal.merged_into`` (``auth/identity.py``).
- It never reads ``secret_ballot``. A secret ballot has no identity, and the merge must
  not link one to a voter. Only the voted marker (the identity, no choice) moves.

Privileges: the merge moves ownership (applications, delegations, the pool). It
therefore refuses with 409 ``merge_privileges`` when the source holds an effective
right (global role, or gremium role per gremium) that the target does not hold, unless
the acting admin holds every such right. Without this rule a holder of
``admin.users.merge`` could merge the old account of an admin into their own account.
It also refuses an erased account (``principal_erased``) and a deactivated target
(``merge_target_inactive``).

The source stays as a locked reference: ``merged_into`` names the target, ``active`` is
false, and a login with its ``sub`` fails (``auth/service.upsert_principal``). Earlier
merges into the source move on to the target, so a chain never has more than one step.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    case,
    delete,
    exists,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.engine import CursorResult, Result
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from app.db import Base
from app.modules.admin.membership_sync import sync_principal_memberships
from app.modules.admin.models import (
    Gremium,
    GremiumMembership,
    GremiumRole,
    SiteConfigVersion,
)
from app.modules.admin.schemas import (
    MergeArea,
    MergeAreaOut,
    MergeConflictKind,
    MergeConflictOut,
    MergePermissionOut,
    MergePreviewOut,
    MergePrincipalOut,
    MergeResultOut,
)
from app.modules.applications.models import (
    Application,
    ApplicationDecision,
    ApplicationShare,
    Comment,
    GuestApplicationSettings,
    StatusEvent,
    SubmissionVersion,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry, AuditVerification
from app.modules.audit.service import AuditService
from app.modules.auth.models import AuthSession, LoginSettings, RoleAssignment
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oauth_models import OAuthAuthorizationCode, OAuthToken
from app.modules.auth.rbac import resolve_principal
from app.modules.backup.models import Backup
from app.modules.budget.tree_models import BudgetExpense, FiscalYear, Invoice
from app.modules.delegations.models import (
    DelegationSubstitute,
    MeetingDelegation,
)
from app.modules.forms.models import FormVersion
from app.modules.livevote.models import (
    Meeting,
    MeetingAgendaItem,
    MeetingAttendance,
    MeetingGuest,
    MeetingSettings,
    ProtocolKeeperPeriod,
)
from app.modules.notifications.models import NotificationPreference
from app.modules.privacy.models import ErasureRequest
from app.modules.protocol.models import Protocol
from app.modules.tickets.models import Ticket, TicketEvent, TicketNote, TicketSenderBlock
from app.modules.todos.merge import fold_personal_board, rewrite_mentions
from app.modules.todos.models import (
    TodoAssignee,
    TodoBoard,
    TodoCard,
    TodoComment,
    TodoEvent,
    TodoLink,
)
from app.modules.voting.models import Ballot, Vote, VotedMarker
from app.shared.errors import ConflictError, FieldError, NotFoundError, ValidationProblem

#: The key of the admin role in an effective-rights set: it holds every right.
ALL_RIGHTS = "*"

#: SQLSTATE deadlock_detected and serialization_failure: a retry can succeed.
_RETRY_SQLSTATES = frozenset({"40P01", "40001"})

#: The display order of the areas. It matches the ``MergeArea`` literal.
AREAS: tuple[MergeArea, ...] = (
    "applications",
    "versions",
    "timeline",
    "comments",
    "votes",
    "delegations",
    "substitutes",
    "attendance",
    "meetings",
    "budget",
    "config",
    "notifications",
    "roles",
    "privacy",
    "backups",
    "sessions",
    "memberships",
    "calendar",
    "tickets",
    "todos",
)

#: Every text column that stores the ``sub`` of a principal, by area. The merge
#: rewrites each one to the target ``sub``. ``Ballot.voter_sub`` covers the own and the
#: represented ballots, because a delegate votes under the ``sub`` of the delegator.
#: ``VotedMarker`` is the identity half of a secret vote; the merge never reads the
#: choice half. ``audit_entry.actor`` and ``config_revision.created_by`` are NOT here,
#: because a trigger keeps their table append-only. Their displays resolve the old
#: ``sub`` through ``principal.merged_into`` (``auth/identity.py``).
SUB_COLUMNS: tuple[tuple[MergeArea, InstrumentedAttribute[Any]], ...] = (
    ("applications", Application.created_by),
    ("applications", Application.archived_by),
    ("applications", Application.captured_by),
    ("applications", ApplicationShare.created_by),
    ("applications", ApplicationDecision.decided_by),
    ("versions", SubmissionVersion.changed_by),
    ("timeline", StatusEvent.actor),
    ("comments", Comment.author),
    ("votes", Ballot.voter_sub),
    ("votes", VotedMarker.voter_sub),
    ("delegations", MeetingDelegation.created_by),
    ("substitutes", DelegationSubstitute.created_by),
    ("meetings", Meeting.created_by),
    ("meetings", ProtocolKeeperPeriod.handed_over_by),
    ("meetings", MeetingAgendaItem.done_by),
    ("meetings", Protocol.author),
    ("budget", BudgetExpense.actor),
    ("budget", Invoice.actor),
    ("budget", FiscalYear.closed_by),
    ("config", SiteConfigVersion.created_by),
    ("config", GuestApplicationSettings.updated_by),
    ("config", MeetingSettings.updated_by),
    ("config", LoginSettings.updated_by),
    ("roles", RoleAssignment.granted_by),
    ("roles", RoleAssignment.delegated_by),
    ("privacy", ErasureRequest.requested_by),
    ("privacy", ErasureRequest.handled_by),
    ("backups", Backup.created_by),
    ("backups", AuditVerification.triggered_by),
)

#: Every principal id column without a uniqueness rule, by area. The merge rewrites
#: each one to the target id. ``erasure_request.principal_id`` stays on the source,
#: because the request is the proof of what happened to that account.
ID_COLUMNS: tuple[tuple[MergeArea, InstrumentedAttribute[Any]], ...] = (
    ("delegations", MeetingDelegation.delegator_principal_id),
    ("delegations", MeetingDelegation.delegate_principal_id),
    ("meetings", Meeting.protokollant_id),
    ("meetings", ProtocolKeeperPeriod.principal_id),
    ("meetings", MeetingGuest.decided_by),
    ("config", FormVersion.created_by),
    ("tickets", Ticket.reporter_principal_id),
    ("tickets", Ticket.assignee_id),
    ("tickets", TicketNote.author_id),
    ("tickets", TicketEvent.actor_id),
    ("tickets", TicketSenderBlock.created_by),
    ("todos", TodoCard.created_by),
    ("todos", TodoComment.author_id),
    ("todos", TodoEvent.actor_id),
    ("todos", TodoLink.created_by),
)

#: The rows of the source that the merge deletes, by area. Rights never move to the
#: target, because that is a privilege escalation. The target gets its own roles from
#: the OIDC group mappings and the bootstrap at its next login.
REMOVED_ROWS: tuple[tuple[MergeArea, InstrumentedAttribute[Any]], ...] = (
    ("roles", RoleAssignment.principal_id),
    ("sessions", AuthSession.principal_id),
    ("sessions", OAuthAuthorizationCode.principal_id),
    ("sessions", OAuthToken.principal_id),
)


#: The principal columns with a uniqueness rule. ``_combined_tables`` drops the
#: duplicates of the source and rewrites the rest.
COMBINED_COLUMNS: tuple[InstrumentedAttribute[Any], ...] = (
    NotificationPreference.principal_id,
    MeetingAttendance.principal_id,
    DelegationSubstitute.member_principal_id,
    DelegationSubstitute.substitute_principal_id,
    TodoAssignee.principal_id,
    TicketSenderBlock.principal_id,
)

#: The principal columns that the merge leaves alone, with the reason. A guard test
#: fails when a model gains a principal column that no list names.
EXCLUDED_COLUMNS: dict[str, str] = {
    "principal.merged_into": "the merge reference itself; `_source_row` re-points it",
    "audit_entry.actor": "append-only hash chain; the display follows merged_into",
    "config_revision.created_by": "append-only (trigger); the display follows merged_into",
    "erasure_request.principal_id": "the proof of the request; an open one blocks",
    "gremium_membership.principal_id": "derived from OIDC; the sync deletes the rows",
    "todo_board.owner_id": "one personal board per person; `_todos` moves or folds it",
}


@dataclass
class _Counts:
    rewritten: int = 0
    combined: int = 0
    removed: int = 0


@dataclass
class _Tally:
    by_area: dict[MergeArea, _Counts] = field(
        default_factory=lambda: {a: _Counts() for a in AREAS}
    )

    def add(
        self, area: MergeArea, *, rewritten: int = 0, combined: int = 0, removed: int = 0
    ) -> None:
        c = self.by_area[area]
        c.rewritten += rewritten
        c.combined += combined
        c.removed += removed

    def out(self) -> list[MergeAreaOut]:
        return [
            MergeAreaOut(
                area=a, rewritten=c.rewritten, combined=c.combined, removed=c.removed
            )
            for a, c in self.by_area.items()
        ]

    def data(self) -> dict[str, dict[str, int]]:
        """Return the non-zero counts for the audit entry (counts only, no PII)."""
        return {
            a: {k: v for k, v in vars(c).items() if v}
            for a, c in self.by_area.items()
            if c.rewritten or c.combined or c.removed
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _principal_out(row: PrincipalRow) -> MergePrincipalOut:
    return MergePrincipalOut(
        id=row.id,
        display_name=row.display_name,
        email=row.email,
        last_login=_iso(row.last_login),
    )


def _table(column: InstrumentedAttribute[Any]) -> type[Base]:
    """Return the mapped class of a column, as a DML target."""
    return cast("type[Base]", column.class_)


def _rowcount(result: Result[Any]) -> int:
    return cast(CursorResult[Any], result).rowcount


class PrincipalMergeService:
    """Preview and run the merge of an old principal into a new one."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a database session."""
        self.session = session

    async def _load(
        self, source_id: UUID, target_id: UUID, *, lock: bool
    ) -> tuple[PrincipalRow, PrincipalRow]:
        """Load both principals and check the preconditions.

        With ``lock`` the rows are locked ``FOR UPDATE`` in id order, so two merges
        that touch the same accounts cannot deadlock.

        Raises:
            ValidationProblem: The source and the target are the same (422).
            NotFoundError: One of the principals does not exist (404).
            ConflictError: The source is already merged (``principal_already_merged``)
                or the target is merged (``merge_target_merged``) (409).
        """
        if source_id == target_id:
            raise ValidationProblem(
                "An account cannot be merged into itself.",
                code="merge_same_principal",
                errors=[{"field": "targetId", "msg": "equals the source"}],
            )
        stmt = (
            select(PrincipalRow)
            .where(PrincipalRow.id.in_([source_id, target_id]))
            .order_by(PrincipalRow.id)
        )
        if lock:
            stmt = stmt.with_for_update()
        rows = {r.id: r for r in (await self.session.scalars(stmt)).all()}
        source = rows.get(source_id)
        target = rows.get(target_id)
        if source is None:
            raise NotFoundError(f"principal {source_id} not found")
        if target is None:
            raise NotFoundError(f"principal {target_id} not found")
        if source.merged_into is not None:
            raise ConflictError(
                "This account is already merged.", code="principal_already_merged"
            )
        if target.merged_into is not None:
            raise ConflictError(
                "The target account is merged into another account.",
                code="merge_target_merged",
            )
        if target.active is False:
            raise ConflictError(
                "The target account is deactivated.", code="merge_target_inactive"
            )
        if await self._erased([source.id, target.id]):
            raise ConflictError(
                "An erased account cannot be merged.", code="principal_erased"
            )
        return source, target

    async def _erased(self, ids: list[UUID]) -> bool:
        """Tell whether one of the principals was erased (GDPR Art. 17).

        Two marks count: an executed erasure request for the principal, and the audit
        entry ``principal_erased`` that ``PrincipalService.erase`` writes (also for a
        direct erasure without a request).
        """
        requests = await self._count(
            select(func.count())
            .select_from(ErasureRequest)
            .where(
                ErasureRequest.status == "executed",
                ErasureRequest.subject_type == "principal",
                ErasureRequest.principal_id.in_(ids),
            )
        )
        if requests:
            return True
        entries = await self._count(
            select(func.count())
            .select_from(AuditEntry)
            .where(
                AuditEntry.action == AuditAction.PRINCIPAL_ERASED.value,
                AuditEntry.target_type == "principal",
                AuditEntry.target_id.in_([str(i) for i in ids]),
            )
        )
        return bool(entries)

    async def _effective(self, row: PrincipalRow | None, now: datetime) -> frozenset[str]:
        """Return the effective rights of a principal as the RBAC resolver sees them today.

        A global permission is its key. A gremium permission is ``key@<gremium id>``.
        The ``admin`` role holds every right and gives the single key ``*``.
        """
        if row is None:
            return frozenset()
        principal = await resolve_principal(self.session, row, now)
        if "admin" in principal.roles:
            return frozenset({ALL_RIGHTS})
        keys = set(principal.permissions)
        rows = (
            await self.session.execute(
                select(GremiumMembership.gremium_id, GremiumRole.permissions)
                .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
                .where(
                    GremiumMembership.principal_id == row.id,
                    or_(
                        GremiumMembership.valid_from.is_(None),
                        GremiumMembership.valid_from <= now,
                    ),
                    or_(
                        GremiumMembership.valid_until.is_(None),
                        GremiumMembership.valid_until > now,
                    ),
                )
            )
        ).all()
        for gremium_id, perms in rows:
            keys.update(f"{p}@{gremium_id}" for p in perms or [])
        return frozenset(keys)

    async def _privileges(
        self, source: PrincipalRow, target: PrincipalRow, actor: str
    ) -> tuple[list[MergePermissionOut], bool]:
        """Return the rights of the source that the target lacks, and whether the actor holds them.

        Returns:
            The extra rights (sorted, with the gremium name), and True when the acting
            admin holds every one of them (or there is none).
        """
        now = datetime.now(UTC)
        have_source = await self._effective(source, now)
        have_target = await self._effective(target, now)
        if ALL_RIGHTS in have_target:
            return [], True
        extra = sorted(have_source - have_target)
        if not extra:
            return [], True
        actor_row = await self.session.scalar(
            select(PrincipalRow).where(PrincipalRow.sub == actor)
        )
        have_actor = await self._effective(actor_row, now)
        covered = ALL_RIGHTS in have_actor or set(extra) <= have_actor
        gremium_ids = {UUID(k.split("@", 1)[1]) for k in extra if "@" in k}
        names: dict[UUID, str] = {}
        if gremium_ids:
            names = {
                gid: name
                for gid, name in (
                    await self.session.execute(
                        select(Gremium.id, Gremium.name).where(Gremium.id.in_(gremium_ids))
                    )
                ).all()
            }
        out: list[MergePermissionOut] = []
        for key in extra:
            if "@" in key:
                perm, gid = key.split("@", 1)
                out.append(MergePermissionOut(key=perm, gremium=names.get(UUID(gid))))
            else:
                out.append(MergePermissionOut(key="admin" if key == ALL_RIGHTS else key))
        return out, covered

    async def _conflicts(
        self, source: PrincipalRow, target: PrincipalRow
    ) -> list[MergeConflictOut]:
        """Find every real conflict. Each one names the vote or the meeting.

        The conflicts are: two ballots in the same vote (the open ``ballot`` and the
        secret ``voted_marker`` each count); both accounts delegated their seat, or
        both received a vote transfer, in the same meeting; one account is delegator
        and the other delegate in the same meeting, because after the merge one person
        would be both, which the no-chain rule forbids; a different attendance in the
        same meeting (an equal one is a harmless duplicate); an open erasure request,
        because its execution would erase the account that it names.
        """
        out: list[MergeConflictOut] = []

        async def add(kind: MergeConflictKind, stmt: Select[Any]) -> None:
            for (label,) in (await self.session.execute(stmt)).all():
                out.append(MergeConflictOut(kind=kind, label=label))

        old_sub, new_sub = source.sub, target.sub
        old, new = source.id, target.id
        vote_label = func.coalesce(Vote.question, Meeting.title)

        for model in (Ballot, VotedMarker):
            a, b = aliased(model), aliased(model)
            await add(
                "ballot_same_vote",
                select(vote_label)
                .select_from(Vote)
                .outerjoin(Meeting, Meeting.id == Vote.meeting_id)
                .where(
                    exists().where(a.vote_id == Vote.id, a.voter_sub == old_sub),
                    exists().where(b.vote_id == Vote.id, b.voter_sub == new_sub),
                )
                .order_by(Vote.created_at),
            )

        def meeting_where(*conds: ColumnElement[bool]) -> Select[Any]:
            return select(Meeting.title).where(*conds).order_by(Meeting.date, Meeting.title)

        def deleg(**cols: object) -> ColumnElement[bool]:
            d = aliased(MeetingDelegation)
            conds: list[ColumnElement[bool]] = [d.meeting_id == Meeting.id]
            for name, value in cols.items():
                conds.append(getattr(d, name) == value)
            return exists().where(*conds)

        await add(
            "delegation_same_meeting",
            meeting_where(
                deleg(delegator_principal_id=old), deleg(delegator_principal_id=new)
            ),
        )
        await add(
            "delegation_vote_twice",
            meeting_where(
                deleg(delegate_principal_id=old, delegate_voting=True),
                deleg(delegate_principal_id=new, delegate_voting=True),
            ),
        )
        await add(
            "delegation_chain",
            meeting_where(
                or_(
                    and_(
                        deleg(delegator_principal_id=old),
                        deleg(delegate_principal_id=new),
                    ),
                    and_(
                        deleg(delegator_principal_id=new),
                        deleg(delegate_principal_id=old),
                    ),
                )
            ),
        )
        a_old, a_new = aliased(MeetingAttendance), aliased(MeetingAttendance)
        await add(
            "attendance_differs",
            select(Meeting.title)
            .join(a_old, and_(a_old.meeting_id == Meeting.id, a_old.principal_id == old))
            .join(a_new, and_(a_new.meeting_id == Meeting.id, a_new.principal_id == new))
            .where(a_old.status != a_new.status)
            .order_by(Meeting.date, Meeting.title),
        )
        open_erasures = await self._count(
            select(func.count())
            .select_from(ErasureRequest)
            .where(
                ErasureRequest.status == "open",
                ErasureRequest.principal_id.in_([old, new]),
            )
        )
        out.extend(MergeConflictOut(kind="erasure_open") for _ in range(open_erasures))
        return out

    async def _count(self, stmt: Select[Any]) -> int:
        return int(await self.session.scalar(stmt) or 0)

    async def _plain_columns(
        self, source: PrincipalRow, target: PrincipalRow, tally: _Tally, *, apply: bool
    ) -> None:
        """Delete the removed rows, then rewrite the plain columns.

        The delete runs first, so a removed row (an own role assignment) is never
        rewritten.
        """
        for area, column in REMOVED_ROWS:
            table = _table(column)
            if apply:
                n = _rowcount(
                    await self.session.execute(delete(table).where(column == source.id))
                )
            else:
                n = await self._count(
                    select(func.count()).select_from(table).where(column == source.id)
                )
            tally.add(area, removed=n)
        for area, column in SUB_COLUMNS:
            await self._rewrite(area, column, source.sub, target.sub, tally, apply=apply)
        for area, column in ID_COLUMNS:
            await self._rewrite(area, column, source.id, target.id, tally, apply=apply)

    async def _rewrite(
        self,
        area: MergeArea,
        column: InstrumentedAttribute[Any],
        old: object,
        new: object,
        tally: _Tally,
        *,
        apply: bool,
    ) -> None:
        table = _table(column)
        if apply:
            n = _rowcount(
                await self.session.execute(
                    update(table)
                    .where(column == old)
                    .values({column.key: new})
                    .execution_options(synchronize_session=False)
                )
            )
        else:
            n = await self._count(select(func.count()).select_from(table).where(column == old))
        tally.add(area, rewritten=n)

    async def _combine(
        self,
        area: MergeArea,
        column: InstrumentedAttribute[Any],
        old: UUID,
        new: UUID,
        duplicate: ColumnElement[bool],
        tally: _Tally,
        *,
        apply: bool,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Drop the source rows that ``duplicate`` marks, then rewrite the rest.

        ``duplicate`` is a condition on the source row (``column == old``): the target
        already has the same row. ``extra`` sets more columns on the rewritten rows.
        """
        table = _table(column)
        dup = and_(column == old, duplicate)
        if apply:
            combined = _rowcount(
                await self.session.execute(
                    delete(table).where(dup).execution_options(synchronize_session=False)
                )
            )
            rewritten = _rowcount(
                await self.session.execute(
                    update(table)
                    .where(column == old)
                    .values({column.key: new, **(extra or {})})
                    .execution_options(synchronize_session=False)
                )
            )
        else:
            combined = await self._count(select(func.count()).select_from(table).where(dup))
            total = await self._count(
                select(func.count()).select_from(table).where(column == old)
            )
            rewritten = total - combined
        tally.add(area, rewritten=rewritten, combined=combined)

    async def _combined_tables(
        self, source: PrincipalRow, target: PrincipalRow, tally: _Tally, *, apply: bool
    ) -> None:
        """Combine the rows of the tables with a uniqueness rule.

        The row of the target wins for a notification kind, an attendance, a pool
        entry, a to-do assignment and a sender block. A different attendance is a
        conflict and never reaches this step. A moved self report ``absent`` becomes a
        lead entry, because the NOT VALID check ``self_status`` refuses such a row on
        every change; the status stays, so it matches the protocol PDF. A pool entry in
        which one account substitutes for the other means nothing after the merge and
        goes.
        """
        old, new = source.id, target.id

        np = aliased(NotificationPreference)
        await self._combine(
            "notifications",
            NotificationPreference.principal_id,
            old,
            new,
            exists().where(
                np.principal_id == new, np.kind == NotificationPreference.kind
            ),
            tally,
            apply=apply,
        )

        att = aliased(MeetingAttendance)
        await self._combine(
            "attendance",
            MeetingAttendance.principal_id,
            old,
            new,
            exists().where(
                att.principal_id == new, att.meeting_id == MeetingAttendance.meeting_id
            ),
            tally,
            apply=apply,
            extra={
                "source": case(
                    (
                        and_(
                            MeetingAttendance.source == "self",
                            MeetingAttendance.status == "absent",
                        ),
                        "lead",
                    ),
                    else_=MeetingAttendance.source,
                )
            },
        )

        ds = DelegationSubstitute
        self_entry = or_(
            and_(ds.member_principal_id == old, ds.substitute_principal_id == new),
            and_(ds.member_principal_id == new, ds.substitute_principal_id == old),
        )
        if apply:
            n = _rowcount(
                await self.session.execute(
                    delete(ds).where(self_entry).execution_options(synchronize_session=False)
                )
            )
        else:
            n = await self._count(select(func.count()).select_from(ds).where(self_entry))
        tally.add("substitutes", combined=n)
        other = aliased(DelegationSubstitute)
        await self._combine(
            "substitutes",
            ds.member_principal_id,
            old,
            new,
            exists().where(
                other.gremium_id == ds.gremium_id,
                other.member_principal_id == new,
                other.substitute_principal_id == ds.substitute_principal_id,
            ),
            tally,
            apply=apply,
        )
        ta = aliased(TodoAssignee)
        await self._combine(
            "todos",
            TodoAssignee.principal_id,
            old,
            new,
            exists().where(ta.principal_id == new, ta.card_id == TodoAssignee.card_id),
            tally,
            apply=apply,
        )
        tsb = aliased(TicketSenderBlock)
        await self._combine(
            "tickets",
            TicketSenderBlock.principal_id,
            old,
            new,
            exists().where(tsb.principal_id == new),
            tally,
            apply=apply,
        )

        other = aliased(DelegationSubstitute)
        await self._combine(
            "substitutes",
            ds.substitute_principal_id,
            old,
            new,
            exists().where(
                other.gremium_id == ds.gremium_id,
                other.member_principal_id.is_not_distinct_from(ds.member_principal_id),
                other.substitute_principal_id == new,
            ),
            tally,
            apply=apply,
        )

    async def _chat_mentions(
        self, source: PrincipalRow, target: PrincipalRow, tally: _Tally, *, apply: bool
    ) -> None:
        """Replace the source by the target in the mentions of the comments and notes.

        The application comments count in the area ``comments``, the ticket notes in
        ``tickets``. The to-do comments are part of `_todos`.
        """
        comments = await rewrite_mentions(
            self.session, source.id, target.id, apply=apply, table="comment"
        )
        tally.add("comments", rewritten=comments)
        notes = await rewrite_mentions(
            self.session, source.id, target.id, apply=apply, table="ticket_note"
        )
        tally.add("tickets", rewritten=notes)

    async def _todos(
        self, source: PrincipalRow, target: PrincipalRow, tally: _Tally, *, apply: bool
    ) -> None:
        """Move the personal board and the mentions of the source to the target.

        Without a personal board of the target the board of the source changes its
        owner. With one, ``fold_personal_board`` moves the cards of the source board
        into it and deletes the source board (one combined row).
        """
        mentions = await rewrite_mentions(self.session, source.id, target.id, apply=apply)
        tally.add("todos", rewritten=mentions)
        rows = (
            await self.session.execute(
                select(TodoBoard.id, TodoBoard.owner_id).where(
                    TodoBoard.kind == "personal",
                    TodoBoard.owner_id.in_([source.id, target.id]),
                )
            )
        ).all()
        boards = {owner: board_id for board_id, owner in rows}
        mine = boards.get(source.id)
        if mine is None:
            return
        theirs = boards.get(target.id)
        if theirs is None:
            tally.add("todos", rewritten=1)
            if apply:
                await self.session.execute(
                    update(TodoBoard)
                    .where(TodoBoard.id == mine)
                    .values(owner_id=target.id)
                    .execution_options(synchronize_session=False)
                )
            return
        if apply:
            moved = await fold_personal_board(self.session, mine, theirs)
        else:
            moved = await self._count(
                select(func.count()).select_from(TodoCard).where(TodoCard.board_id == mine)
            )
        tally.add("todos", rewritten=moved, combined=1)

    async def _source_row(
        self, source: PrincipalRow, target: PrincipalRow, tally: _Tally, *, apply: bool
    ) -> datetime | None:
        """Lock the source as a reference to the target. Return the merge time.

        Earlier merges into the source move on to the target, so a chain is one step
        only. The membership sync treats a merged principal as without groups and
        deletes its memberships, each with its own audit entry.
        """
        memberships = await self._count(
            select(func.count())
            .select_from(GremiumMembership)
            .where(GremiumMembership.principal_id == source.id)
        )
        tally.add("memberships", removed=memberships)
        tally.add("calendar", removed=1 if source.calendar_token else 0)
        if not apply:
            return None
        now = datetime.now(UTC)
        await self.session.execute(
            update(PrincipalRow)
            .where(PrincipalRow.merged_into == source.id)
            .values(merged_into=target.id)
            .execution_options(synchronize_session=False)
        )
        source.merged_into = target.id
        source.merged_at = now
        source.active = False
        source.calendar_token = None
        await self.session.flush()
        await sync_principal_memberships(self.session, source)
        return now

    async def preview(
        self, source_id: UUID, target_id: UUID, *, actor: str
    ) -> MergePreviewOut:
        """Count what a merge would do and list the conflicts. Write nothing.

        ``actor`` is the ``sub`` of the admin. The extra rights of the source block the
        merge (``canMerge`` false) unless the admin holds them all.
        """
        source, target = await self._load(source_id, target_id, lock=False)
        conflicts = await self._conflicts(source, target)
        extra, covered = await self._privileges(source, target, actor)
        tally = _Tally()
        await self._plain_columns(source, target, tally, apply=False)
        await self._combined_tables(source, target, tally, apply=False)
        await self._todos(source, target, tally, apply=False)
        await self._chat_mentions(source, target, tally, apply=False)
        await self._source_row(source, target, tally, apply=False)
        return MergePreviewOut(
            source=_principal_out(source),
            target=_principal_out(target),
            areas=tally.out(),
            conflicts=conflicts,
            extra_permissions=extra,
            actor_holds_extra=covered,
            can_merge=not conflicts and covered,
        )

    async def merge(
        self, source_id: UUID, target_id: UUID, *, actor: str
    ) -> MergeResultOut:
        """Merge the source into the target in one transaction and commit.

        ``actor`` is the ``sub`` of the admin.

        Raises:
            ValidationProblem: The source and the target are the same (422).
            NotFoundError: One of the principals does not exist (404).
            ConflictError: A precondition fails, the admin merges their own account
                away (``merge_own_account``), or a real conflict exists
                (``merge_conflict``, the ``errors`` list each one as
                ``{field: kind, msg: label}``) (409). A row that a parallel request
                wrote after the conflict check also gives ``merge_conflict``, and a
                deadlock or serialization failure gives ``merge_retry``, because the
                same merge can run again. Nothing is written then.
        """
        try:
            source, target = await self._load(source_id, target_id, lock=True)
            if source.sub == actor:
                raise ConflictError(
                    "You cannot merge your own account into another one.",
                    code="merge_own_account",
                )
            conflicts = await self._conflicts(source, target)
            if conflicts:
                raise _conflict_error(conflicts)
            extra, covered = await self._privileges(source, target, actor)
            if not covered:
                raise ConflictError(
                    "The old account holds rights that the target and you lack.",
                    code="merge_privileges",
                    errors=[
                        FieldError(field="permission", msg=_permission_label(p))
                        for p in extra
                    ],
                )
            tally = _Tally()
            await self._combined_tables(source, target, tally, apply=True)
            await self._plain_columns(source, target, tally, apply=True)
            await self._todos(source, target, tally, apply=True)
            await self._chat_mentions(source, target, tally, apply=True)
            merged_at = await self._source_row(source, target, tally, apply=True)
            assert merged_at is not None
            await AuditService(self.session).record(
                actor=actor,
                action=AuditAction.PRINCIPAL_MERGE,
                target_type="principal",
                target_id=str(source.id),
                data={
                    "sourceId": str(source.id),
                    "targetId": str(target.id),
                    "counts": tally.data(),
                    "extraPermissions": [_permission_label(p) for p in extra],
                },
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                "The data changed during the merge. Check the preview again.",
                code="merge_conflict",
            ) from exc
        except DBAPIError as exc:
            await self.session.rollback()
            if _sqlstate(exc) in _RETRY_SQLSTATES:
                raise ConflictError(
                    "The merge met a parallel change. Try again.", code="merge_retry"
                ) from exc
            raise
        except BaseException:
            await self.session.rollback()
            raise
        return MergeResultOut(
            source=_principal_out(source),
            target=_principal_out(target),
            areas=tally.out(),
            merged_at=merged_at.isoformat(),
        )


def _sqlstate(exc: DBAPIError) -> str | None:
    """Return the SQLSTATE of a driver error (psycopg ``pgcode``, asyncpg ``sqlstate``)."""
    for err in (exc.orig, getattr(exc.orig, "__cause__", None)):
        code = getattr(err, "pgcode", None) or getattr(err, "sqlstate", None)
        if isinstance(code, str):
            return code
    return None


def _permission_label(p: MergePermissionOut) -> str:
    return f"{p.key} ({p.gremium})" if p.gremium else p.key


def _conflict_error(conflicts: Sequence[MergeConflictOut]) -> ConflictError:
    return ConflictError(
        "The accounts have conflicting data. Resolve the conflicts first.",
        code="merge_conflict",
        errors=[FieldError(field=c.kind, msg=c.label or "") for c in conflicts],
    )
