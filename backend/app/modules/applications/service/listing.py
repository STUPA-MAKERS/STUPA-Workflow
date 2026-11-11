"""Filtered application listing, Gremium read scope, open tasks, export name maps."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    ColumnElement,
    Subquery,
    Text,
    and_,
    case,
    cast,
    false,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, array
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.application_types.models import ApplicationType
from app.modules.applications.models import Application
from app.modules.applications.schemas import (
    ApplicantApplicationItem,
    ApplicationListItem,
    StateOut,
)
from app.modules.applications.service.service_base import (
    ApplicationsServiceBase,
    _title_of,
    state_since_subquery,
)
from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import Budget
from app.modules.flow.models import State
from app.modules.gremien.models import Gremium
from app.shared.paging import Page
from app.shared.search import dialect_of, trigram_rank

if TYPE_CHECKING:
    from app.modules.flow.service import FlowService


class ListingOps(ApplicationsServiceBase):
    """List and filter applications, Gremium read scope, tasks and export helpers."""

    async def list_applications(
        self,
        *,
        state_ids: Sequence[UUID] | None = None,
        gremium_id: UUID | None = None,
        type_id: UUID | None = None,
        budget_id: UUID | None = None,
        q: str | None = None,
        archived: bool | None = False,
        amount_min: Decimal | None = None,
        amount_max: Decimal | None = None,
        created_from: date | None = None,
        created_to: date | None = None,
        sort: str = "createdAt",
        order: str = "desc",
        owner_sub: str | None = None,
        committee_sub: str | None = None,
        hide_pii_in_search: bool = False,
        limit: int,
        offset: int,
    ) -> Page[ApplicationListItem]:
        """List applications with filters, paging and sorting for `GET /applications`.

        `owner_sub` limits the result to applications with that `created_by`. Set it for
        a user without `application.read` who may see only own applications.

        `committee_sub` adds the Gremium read scope. The result then holds an
        application in a view cost center of a member Gremium. It also holds an
        application in a `vote` state of such a Gremium.

        The query combines both limits with OR. If the caller sets neither, the list
        holds every application. That is the full view for `application.read` and for
        admin.

        `state_ids` keeps the applications in one of these states. None or an
        empty list does not filter.

        Each item carries `stateSince`, the time of the last status change. One
        grouped subquery over `status_event` gives it for the whole page.

        `hide_pii_in_search` is for a caller without the PII right. The search
        `q` then skips the `isPII` field values, except in the own applications
        (`created_by == owner_sub`). Without this rule the search is an oracle: a
        guessed name or IBAN would tell which readable application holds it.

        `sort` is `createdAt`, `amount` or `stateSince`. `stateSince` sorts by the time
        of the last status change, with the creation time for an application without an
        event, the same value as the item carries.

        `archived` defaults to False, so the working list hides archived applications
        without every caller remembering to ask. `True` lists only the archived ones and
        `None` lists both. The count follows the same filter, or the total would promise
        rows the page does not contain.

        An unconfirmed guest application stays invisible until the applicant confirms the email.
        The cost-center filter covers the subtree through the `path_key` prefix; an unknown cost
        center gives an empty list. The fuzzy search reads meaningful text only: the title and
        the string answer values of the `data` JSONB, no ids, enums or numbers (see
        `_search_text` for the dialects and the PII projection). An active search puts the most
        relevant row first, and the chosen sort acts as a deterministic tiebreak. `created_to`
        is inclusive, so the filter ends at 00:00 UTC of the next day.
        """
        read_scope = await self._read_scope(owner_sub=owner_sub, committee_sub=committee_sub)
        budget_scope = await self._budget_scope(budget_id) if budget_id is not None else None
        search = (
            await self._search_filter(q, hide_pii_in_search=hide_pii_in_search, owner_sub=owner_sub)
            if q and q.strip()
            else None
        )
        optional = (
            read_scope,
            _archived_filter(archived),
            Application.current_state_id.in_(set(state_ids)) if state_ids else None,
            Application.gremium_id == gremium_id if gremium_id is not None else None,
            Application.type_id == type_id if type_id is not None else None,
            budget_scope,
            search[0] if search is not None else None,
            Application.amount >= amount_min if amount_min is not None else None,
            Application.amount <= amount_max if amount_max is not None else None,
            (
                Application.created_at >= datetime.combine(created_from, time.min, UTC)
                if created_from is not None
                else None
            ),
            (
                Application.created_at
                < datetime.combine(created_to + timedelta(days=1), time.min, UTC)
                if created_to is not None
                else None
            ),
        )
        filters = [
            Application.email_confirmed_at.is_not(None),
            *(clause for clause in optional if clause is not None),
        ]

        since_sq = state_since_subquery()
        sort_col = _sort_column(sort, since_sq)
        ordering = (sort_col.asc() if order == "asc" else sort_col.desc()).nulls_last()
        order_by = (search[1].desc(), ordering) if search is not None else (ordering,)

        total = await self.session.scalar(
            select(func.count()).select_from(Application).where(*filters)
        )
        rows = (
            await self.session.execute(
                select(Application, since_sq.c.since)
                .outerjoin(since_sq, since_sq.c.app_id == Application.id)
                .where(*filters)
                .order_by(*order_by)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        items = [
            _list_item(
                app,
                await self._state_out_resolved(await self._get_state(app.current_state_id)),
                since or app.created_at,
                archived_at=app.archived_at,
            )
            for app, since in rows
        ]
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    async def _budget_scope(self, budget_id: UUID) -> ColumnElement[bool]:
        """Keep the applications in the subtree of a cost center, or none for an unknown one."""
        node_path = await self.session.scalar(
            select(Budget.path_key).where(Budget.id == budget_id)
        )
        if node_path is None:
            return false()
        descendants = select(Budget.id).where(
            or_(
                Budget.path_key == node_path,
                Budget.path_key.like(f"{node_path}-%"),
            )
        )
        return Application.budget_id.in_(descendants)

    async def _search_filter(
        self, q: str, *, hide_pii_in_search: bool, owner_sub: str | None
    ) -> tuple[ColumnElement[bool], ColumnElement[Any]]:
        """Build the fuzzy search of the list: the where clause and the rank expression."""
        dialect = dialect_of(self.session)
        search_col = self._search_text(
            dialect,
            hidden_keys=await self._all_pii_keys() if hide_pii_in_search else set(),
            owner_sub=owner_sub,
        )
        return trigram_rank(q, [search_col], dialect=dialect)

    async def _read_scope(
        self, *, owner_sub: str | None, committee_sub: str | None
    ) -> ColumnElement[bool] | None:
        """Build the read scope of the list as one SQL clause.

        The clause holds the own applications (`owner_sub`) OR the Gremium read scope
        (`committee_sub`, see `_committee_read_clauses`). None means no limit: the
        full view of `application.read`, `application.read_all` and admin.
        """
        owner = (Application.created_by == owner_sub,) if owner_sub is not None else ()
        committee = (
            await self._committee_read_clauses(committee_sub) if committee_sub is not None else []
        )
        clauses = (*owner, *committee)
        return or_(*clauses) if clauses else None

    async def read_scope_for(self, principal: Principal) -> ColumnElement[bool] | None:
        """Build the read scope of `principal` as one SQL clause, or None for all.

        This is the rule of `GET /applications` without `mine`: a principal with
        `principal_reads_all` reads every application. Every other principal reads the
        own applications and the Gremium read scope. `access.resolve_app_read` gives
        the same answer for one application.
        """
        from app.modules.applications.access import principal_reads_all

        if principal_reads_all(principal):
            return None
        return await self._read_scope(owner_sub=principal.sub, committee_sub=principal.sub)

    async def _all_pii_keys(self) -> set[str]:
        """Collect the ``isPII`` field keys of every form version of every type.

        The search hides these keys for a reader without the PII right. The union
        over all types is stricter than the set of one type: a key that is PII in
        one type also leaves the search of another type. That loses some recall,
        but it never leaks.
        """
        from app.modules.forms.models import FormField

        rows = await self.session.scalars(
            select(FormField.key).where(FormField.is_pii.is_(True)).distinct()
        )
        return set(rows)

    @staticmethod
    def _search_text(
        dialect: str, *, hidden_keys: set[str], owner_sub: str | None
    ) -> ColumnElement[Any]:
        """Build the text expression that the fuzzy search reads.

        Postgres uses `app_search_text(data)`, the trigram index expression. The
        SQLite fallback of the unit stubs reads the whole `data` blob as text.
        ``hidden_keys`` leaves these top-level keys out of `data` first. An
        application with ``created_by == owner_sub`` keeps all keys, because the
        creator reads the own PII. The projection cannot use the trigram index;
        the read scope of such a caller is small.
        """
        postgres = dialect == "postgresql"
        keys = sorted(hidden_keys)
        full: ColumnElement[Any] = (
            func.app_search_text(Application.data) if postgres else cast(Application.data, Text)
        )
        if not keys:
            return full
        projected = _postgres_projection(keys) if postgres else _sqlite_projection(keys)
        if owner_sub is None:
            return projected
        return case((Application.created_by == owner_sub, full), else_=projected)

    async def _committee_read_clauses(self, sub: str) -> list[ColumnElement[bool]]:
        """Build the Gremium read scope as SQL clauses.

        The caller combines these clauses with the owner filter through OR. A member
        Gremium is a membership or a substitute pool (`gremium_reader_ids`). The three
        paths mirror `access._committee_can_read`, which the detail view uses:

        * a cost center (the node or an ancestor) with `view_gremium_id` in a member
          Gremium, which opens the whole subtree through the `path_key` prefix,
        * the current `vote` state decided by a member Gremium (the snapshot
          `application.vote_gremium_id`), and
        * legacy: a vote in a meeting of a member Gremium, found over `vote` and
          `meeting.gremium_id`.

        Both functions must cover the same paths. A listed application must also be
        openable, and an openable application must also be listed.

        Path (a) first collects the root paths with a matching `view_gremium_id`, then takes
        every application whose `budget_id` points at such a path or a descendant. Path (b) is a
        plain filter, because the flow engine keeps the snapshot in sync with the state.

        Returns:
            An empty list when the principal holds no active membership. The caller
            then adds no extra scope.
        """
        from app.modules.gremien.gremium_roles import gremium_reader_ids

        member_ids = await gremium_reader_ids(self.session, sub)
        if not member_ids:
            return []
        root_paths = (
            await self.session.scalars(
                select(Budget.path_key).where(Budget.view_gremium_id.in_(member_ids))
            )
        ).all()
        budget_scope = (_view_subtrees(root_paths),) if root_paths else ()

        from app.modules.livevote.models import Meeting
        from app.modules.voting.models import Vote

        voted_app_ids = (
            select(Vote.application_id)
            .join(Meeting, Meeting.id == Vote.meeting_id)
            .where(Vote.application_id.is_not(None), Meeting.gremium_id.in_(member_ids))
        )
        return [
            *budget_scope,
            Application.vote_gremium_id.in_(member_ids),
            Application.id.in_(voted_app_ids),
        ]

    async def name_maps(self, locale: str = "de") -> tuple[dict[UUID, str], dict[UUID, str]]:
        """Return `(type_names, gremium_names)` for the application xlsx export."""
        type_rows = (
            await self.session.execute(select(ApplicationType.id, ApplicationType.name_i18n))
        ).all()
        type_names = {
            tid: (n or {}).get(locale) or (n or {}).get("de") or (n or {}).get("en") or ""
            for tid, n in type_rows
        }
        gremium_rows = (await self.session.execute(select(Gremium.id, Gremium.name))).all()
        gremium_names = dict(gremium_rows)
        return type_names, gremium_names

    async def list_for_applicant(
        self, application_ids: frozenset[str]
    ) -> list[ApplicantApplicationItem]:
        """List the Anträge of an applicant session, newest first.

        The caller passes the ids that the session reaches (`Applicant`), so the list
        never shows more than the item routes open.
        """
        if not application_ids:
            return []
        rows = (
            await self.session.execute(
                select(Application, State)
                .outerjoin(State, State.id == Application.current_state_id)
                .where(Application.id.in_([UUID(i) for i in application_ids]))
                .order_by(Application.created_at.desc())
            )
        ).all()
        return [
            ApplicantApplicationItem(
                id=app.id,
                title=_title_of(app.data),
                state=await self._state_out_resolved(state),
                typeId=app.type_id,
                amount=app.amount,
                approvedAmount=app.approved_amount,
                currency=app.currency,
                createdAt=app.created_at,
            )
            for app, state in rows
        ]

    async def list_tasks(self, principal: Principal) -> list[ApplicationListItem]:
        """List the open tasks of the principal.

        A task is an application that the principal can read AND act on now. The
        read rule is the one of the list (`read_scope_for`), applied in SQL. The
        principal acts on an application in two ways:

        * a ballot: an open vote of the application takes a ballot of the principal
          now (`VotingService.can_still_cast`, the gate of the cast route), or
        * a transition: a manual transition with `requiresAction` that the principal
          may fire. The member route needs `application.transition` and the read
          access (`flow.router.require_transition_principal`) and lists
          `available_transitions`. The applicant route admits the creator
          (`access.require_app_applicant`) and lists
          `available_applicant_transitions`.

        So each task matches a route that accepts the action, and no other
        application is a task. Before the per-row checks, SQL keeps only the
        readable, confirmed applications that have an open vote or a manual exit
        with `requiresAction`.

        Each task carries `stateSince`, the time of the last status change.

        One grouped query computes `stateSince` for the kept tasks only. An application without
        a status event keeps its creation time.
        """
        from app.modules.flow.service import FlowService

        flow = FlowService(self.session)
        now = datetime.now(UTC)
        can_transition = principal.has("application.transition")
        rows = (
            await self.session.execute(
                select(Application, State)
                .join(State, State.id == Application.current_state_id)
                .where(*await self._task_filters(principal, can_transition=can_transition))
                .order_by(Application.created_at.desc())
            )
        ).all()

        tasks = [
            (app, await self._state_out_resolved(state))
            for app, state in rows
            if await self._casts_in_open_vote(app.id, principal, now)
            or await self._fires_task_transition(
                flow, app, principal, can_transition=can_transition
            )
        ]
        since_by_app = await self._state_since_map(app.id for app, _ in tasks)
        return [
            _list_item(
                app, state_out, since_by_app.get(app.id, app.created_at), archived_at=None
            )
            for app, state_out in tasks
        ]

    async def _task_filters(
        self, principal: Principal, *, can_transition: bool
    ) -> list[ColumnElement[bool]]:
        """Build the SQL pre-filter of `list_tasks`.

        The filter keeps the confirmed applications with a state inside the read
        scope of the principal. Of these it keeps the ones with an open vote, and the
        ones whose current state has a manual exit with `requiresAction`. Without
        `application.transition` only the own applications keep that second path,
        because only the applicant route is open to the creator.
        """
        from app.modules.flow.models import Transition
        from app.modules.voting.models import Vote

        read_scope = await self.read_scope_for(principal)
        open_vote = (
            select(Vote.id)
            .where(Vote.application_id == Application.id, Vote.status == "open")
            .exists()
        )
        manual_exit: ColumnElement[bool] = (
            select(Transition.id)
            .where(
                Transition.flow_version_id == Application.flow_version_id,
                Transition.from_state_id == Application.current_state_id,
                Transition.requires_action.is_(True),
                Transition.automatic.is_(False),
                Transition.branch.is_(None),
            )
            .exists()
        )
        action_exit = (
            manual_exit
            if can_transition
            else and_(manual_exit, Application.created_by == principal.sub)
        )
        return [
            Application.current_state_id.is_not(None),
            Application.email_confirmed_at.is_not(None),
            *((read_scope,) if read_scope is not None else ()),
            or_(open_vote, action_exit),
        ]

    async def _casts_in_open_vote(
        self, application_id: UUID, principal: Principal, now: datetime
    ) -> bool:
        """Tell whether an open vote of the application takes a ballot of the principal.

        `VotingService.can_still_cast` holds the rule of the cast route.
        """
        from app.modules.voting.models import Vote
        from app.modules.voting.service import VotingService

        votes = (
            await self.session.scalars(
                select(Vote).where(Vote.application_id == application_id, Vote.status == "open")
            )
        ).all()
        voting = VotingService(self.session)
        for vote in votes:
            if await voting.can_still_cast(vote, principal, now=now):
                return True
        return False

    @staticmethod
    async def _fires_task_transition(
        flow: FlowService, app: Application, principal: Principal, *, can_transition: bool
    ) -> bool:
        """Tell whether the principal may fire a manual transition with `requiresAction`.

        The member route lists `available_transitions` for a holder of
        `application.transition`. The caller already applied the read scope. The
        applicant route lists `available_applicant_transitions` for the creator.
        """
        if can_transition and any(
            t.requires_action for t in await flow.available_transitions(app.id, principal)
        ):
            return True
        own = app.created_by is not None and app.created_by == principal.sub
        return own and any(
            t.requires_action for t in await flow.available_applicant_transitions(app.id)
        )


def _archived_filter(archived: bool | None) -> ColumnElement[bool] | None:
    """Keep the working list (False), the archive (True) or both (None)."""
    match archived:
        case False:
            return Application.archived_at.is_(None)
        case True:
            return Application.archived_at.is_not(None)
        case None:
            return None


def _sort_column(
    sort: str, since_sq: Subquery
) -> ColumnElement[Any] | InstrumentedAttribute[Any]:
    """Return the column of a list sort key; an unknown key sorts by the creation time."""
    match sort:
        case "amount":
            return Application.amount
        case "stateSince":
            return func.coalesce(since_sq.c.since, Application.created_at)
        case _:
            return Application.created_at


def _postgres_projection(keys: Sequence[str]) -> ColumnElement[Any]:
    """Return the search text of `data` without the top-level ``keys`` (Postgres)."""
    stripped = Application.data.op("-", return_type=JSONB)(
        cast(array(keys, type_=Text), ARRAY(Text))
    )
    return func.app_search_text(stripped)


def _sqlite_projection(keys: Sequence[str]) -> ColumnElement[Any]:
    """Return the text of `data` without the top-level ``keys`` (SQLite of the unit stubs)."""
    paths = ['$."' + k.replace('"', '\\"') + '"' for k in keys]
    return cast(func.json_remove(Application.data, *paths), Text)


def _view_subtrees(root_paths: Sequence[str]) -> ColumnElement[bool]:
    """Keep the applications in the subtree of one of the view cost centers."""
    scoped = select(Budget.id).where(
        or_(
            *[
                or_(Budget.path_key == rp, Budget.path_key.like(f"{rp}-%"))
                for rp in root_paths
            ]
        )
    )
    return Application.budget_id.in_(scoped)


def _list_item(
    app: Application,
    state: StateOut | None,
    since: datetime,
    *,
    archived_at: datetime | None,
) -> ApplicationListItem:
    """Build one row of the list or of the tasks."""
    return ApplicationListItem(
        id=app.id,
        typeId=app.type_id,
        title=_title_of(app.data),
        state=state,
        gremiumId=app.gremium_id,
        amount=app.amount,
        approvedAmount=app.approved_amount,
        currency=app.currency,
        createdAt=app.created_at,
        updatedAt=app.updated_at,
        archivedAt=archived_at,
        stateSince=since,
    )
