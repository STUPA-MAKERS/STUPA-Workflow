"""Filtered application listing, Gremium read scope, open tasks, export name maps."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, ColumnElement, Text, and_, case, cast, false, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB, array
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationListItem
from app.modules.applications.service.service_base import (
    ApplicationsServiceBase,
    _title_of,
    state_since_subquery,
)
from app.modules.budget.tree_models import Budget
from app.modules.flow.models import State
from app.search import dialect_of, trigram_rank
from app.shared.paging import Page


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

        `state_ids` keeps the applications in one of these states (A4). None or an
        empty list does not filter.

        Each item carries `stateSince`, the time of the last status change (A9). One
        grouped subquery over `status_event` gives it for the whole page.

        `hide_pii_in_search` is for a caller without the PII right (O21). The search
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
        """
        # An unconfirmed guest application stays invisible until the applicant confirms
        # the email. An existing or logged-in application carries `email_confirmed_at`.
        filters: list[ColumnElement[bool]] = [Application.email_confirmed_at.is_not(None)]
        read_scope = await self._read_scope(owner_sub=owner_sub, committee_sub=committee_sub)
        if read_scope is not None:
            filters.append(read_scope)
        # Archived applications leave the working list by default. `None` asks for both,
        # which is what a search across everything wants.
        if archived is False:
            filters.append(Application.archived_at.is_(None))
        elif archived is True:
            filters.append(Application.archived_at.is_not(None))
        if state_ids:
            filters.append(Application.current_state_id.in_(set(state_ids)))
        if gremium_id is not None:
            filters.append(Application.gremium_id == gremium_id)
        if type_id is not None:
            filters.append(Application.type_id == type_id)
        if budget_id is not None:
            # The filter covers the cost center and its whole subtree through the
            # `path_key` prefix. An unknown cost center gives an empty list.
            node_path = await self.session.scalar(
                select(Budget.path_key).where(Budget.id == budget_id)
            )
            if node_path is None:
                filters.append(false())
            else:
                descendants = select(Budget.id).where(
                    or_(
                        Budget.path_key == node_path,
                        Budget.path_key.like(f"{node_path}-%"),
                    )
                )
                filters.append(Application.budget_id.in_(descendants))
        # The fuzzy search reads meaningful text only: the title and the string answer
        # values of the `data` JSONB. It skips ids, enums and numbers. See
        # `_search_text` for the dialects and for the PII projection (O21).
        rank_expr: ColumnElement[Any] | None = None
        if q and q.strip():
            dialect = dialect_of(self.session)
            search_col = self._search_text(
                dialect,
                hidden_keys=await self._all_pii_keys() if hide_pii_in_search else set(),
                owner_sub=owner_sub,
            )
            where, rank_expr = trigram_rank(q, [search_col], dialect=dialect)
            filters.append(where)
        if amount_min is not None:
            filters.append(Application.amount >= amount_min)
        if amount_max is not None:
            filters.append(Application.amount <= amount_max)
        if created_from is not None:
            filters.append(Application.created_at >= datetime.combine(created_from, time.min, UTC))
        if created_to is not None:
            # `created_to` is inclusive, so the filter ends at 00:00 UTC of the next day.
            end = datetime.combine(created_to + timedelta(days=1), time.min, UTC)
            filters.append(Application.created_at < end)

        since_sq = state_since_subquery()
        # `stateSince` falls back to the creation time, as the items do below.
        sort_col: ColumnElement[Any] | InstrumentedAttribute[Any]
        if sort == "amount":
            sort_col = Application.amount
        elif sort == "stateSince":
            sort_col = func.coalesce(since_sq.c.since, Application.created_at)
        else:
            sort_col = Application.created_at
        ordering = (sort_col.asc() if order == "asc" else sort_col.desc()).nulls_last()
        # An active search puts the most relevant row first. The chosen sort then acts
        # as a deterministic tiebreak. Without a search the order does not change.
        order_by = (rank_expr.desc(), ordering) if rank_expr is not None else (ordering,)

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
        items: list[ApplicationListItem] = []
        for app, since in rows:
            state = await self._get_state(app.current_state_id)
            items.append(
                ApplicationListItem(
                    id=app.id,
                    typeId=app.type_id,
                    title=_title_of(app.data),
                    state=await self._state_out_resolved(state),
                    gremiumId=app.gremium_id,
                    amount=app.amount,
                    currency=app.currency,
                    createdAt=app.created_at,
                    updatedAt=app.updated_at,
                    archivedAt=app.archived_at,
                    stateSince=since or app.created_at,
                )
            )
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    async def _read_scope(
        self, *, owner_sub: str | None, committee_sub: str | None
    ) -> ColumnElement[bool] | None:
        """Build the read scope of the list as one SQL clause.

        The clause holds the own applications (`owner_sub`) OR the Gremium read scope
        (`committee_sub`, see `_committee_read_clauses`). None means no limit: the
        full view of `application.read`, `application.read_all` and admin.
        """
        clauses: list[ColumnElement[bool]] = []
        if owner_sub is not None:
            clauses.append(Application.created_by == owner_sub)
        if committee_sub is not None:
            clauses.extend(await self._committee_read_clauses(committee_sub))
        return or_(*clauses) if clauses else None

    async def read_scope_for(self, principal: Any) -> ColumnElement[bool] | None:
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
        ``hidden_keys`` leaves these top-level keys out of `data` first (O21). An
        application with ``created_by == owner_sub`` keeps all keys, because the
        creator reads the own PII. The projection cannot use the trigram index;
        the read scope of such a caller is small.
        """
        full: ColumnElement[Any]
        projected: ColumnElement[Any]
        keys = sorted(hidden_keys)
        if dialect == "postgresql":
            full = func.app_search_text(Application.data)
            if not keys:
                return full
            stripped = Application.data.op("-", return_type=JSONB)(
                cast(array(keys, type_=Text), ARRAY(Text))
            )
            projected = func.app_search_text(stripped)
        else:
            full = cast(Application.data, Text)
            if not keys:
                return full
            paths = ['$."' + k.replace('"', '\\"') + '"' for k in keys]
            projected = cast(func.json_remove(Application.data, *paths), Text)
        if owner_sub is None:
            return projected
        return case((Application.created_by == owner_sub, full), else_=projected)

    async def _committee_read_clauses(self, sub: str) -> list[ColumnElement[bool]]:
        """Build the Gremium read scope as SQL clauses.

        The caller combines these clauses with the owner filter through OR. The three
        paths mirror `access._committee_can_read`, which the detail view uses:

        * a cost center (the node or an ancestor) with `view_gremium_id` in a member
          Gremium, which opens the whole subtree through the `path_key` prefix,
        * the current `vote` state with `config.gremiumId` in a member Gremium, and
        * legacy: a vote in a meeting of a member Gremium, found over `vote` and
          `meeting.gremium_id`.

        Both functions must cover the same paths. A listed application must also be
        openable, and an openable application must also be listed.

        Returns:
            An empty list when the principal holds no active membership. The caller
            then adds no extra scope.
        """
        from app.modules.admin.gremium_roles import gremium_member_ids

        member_ids = await gremium_member_ids(self.session, sub)
        if not member_ids:
            return []
        clauses: list[ColumnElement[bool]] = []

        # (a) View cost centers of a member Gremium, the node or an ancestor, with the
        #     whole subtree. First collect the root paths with a matching
        #     `view_gremium_id`. Then take every application whose `budget_id` points
        #     at such a path or at a descendant.
        root_paths = (
            await self.session.scalars(
                select(Budget.path_key).where(Budget.view_gremium_id.in_(member_ids))
            )
        ).all()
        if root_paths:
            scoped = select(Budget.id).where(
                or_(
                    *[
                        or_(Budget.path_key == rp, Budget.path_key.like(f"{rp}-%"))
                        for rp in root_paths
                    ]
                )
            )
            clauses.append(Application.budget_id.in_(scoped))

        # (b) The current `vote` state belongs to a member Gremium. Python evaluates the
        #     JSONB `config` to stay dialect-neutral. The set of `vote` states is
        #     small.
        member_str = {str(g) for g in member_ids}
        vote_state_ids = [
            s.id
            for s in (
                await self.session.scalars(select(State).where(State.kind == "vote"))
            ).all()
            if isinstance(s.config, dict)
            and str(s.config.get("gremiumId") or "") in member_str
        ]
        if vote_state_ids:
            clauses.append(Application.current_state_id.in_(vote_state_ids))

        # (c) Legacy: the application has a `Vote` in a meeting of a member Gremium.
        #     This mirrors `access._committee_can_read` (c).
        from app.modules.livevote.models import Meeting
        from app.modules.voting.models import Vote

        voted_app_ids = (
            select(Vote.application_id)
            .join(Meeting, Meeting.id == Vote.meeting_id)
            .where(Vote.application_id.is_not(None), Meeting.gremium_id.in_(member_ids))
        )
        clauses.append(Application.id.in_(voted_app_ids))

        return clauses

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
        gremium_names = {gid: name for gid, name in gremium_rows}
        return type_names, gremium_names

    async def list_tasks(self, principal: Any) -> list[ApplicationListItem]:
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

        Each task carries `stateSince`, the time of the last status change (A9).
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

        items: list[ApplicationListItem] = []
        for app, state in rows:
            if not (
                await self._casts_in_open_vote(app.id, principal, now)
                or await self._fires_task_transition(
                    flow, app, principal, can_transition=can_transition
                )
            ):
                continue
            items.append(
                ApplicationListItem(
                    id=app.id,
                    typeId=app.type_id,
                    title=_title_of(app.data),
                    state=await self._state_out_resolved(state),
                    gremiumId=app.gremium_id,
                    amount=app.amount,
                    currency=app.currency,
                    createdAt=app.created_at,
                    updatedAt=app.updated_at,
                    stateSince=app.created_at,
                )
            )
        # One grouped query for the kept tasks only (A9). An application without a
        # status event keeps its creation time.
        since_by_app = await self._state_since_map(item.id for item in items)
        for item in items:
            item.state_since = since_by_app.get(item.id, item.state_since)
        return items

    async def _task_filters(
        self, principal: Any, *, can_transition: bool
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

        filters: list[ColumnElement[bool]] = [
            Application.current_state_id.is_not(None),
            Application.email_confirmed_at.is_not(None),
        ]
        read_scope = await self.read_scope_for(principal)
        if read_scope is not None:
            filters.append(read_scope)
        open_vote = (
            select(Vote.id)
            .where(Vote.application_id == Application.id, Vote.status == "open")
            .exists()
        )
        action_exit: ColumnElement[bool] = (
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
        if not can_transition:
            action_exit = and_(action_exit, Application.created_by == principal.sub)
        filters.append(or_(open_vote, action_exit))
        return filters

    async def _casts_in_open_vote(
        self, application_id: UUID, principal: Any, now: datetime
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
        flow: Any, app: Application, principal: Any, *, can_transition: bool
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
        if app.created_by is None or app.created_by != principal.sub:
            return False
        return any(
            t.requires_action for t in await flow.available_applicant_transitions(app.id)
        )
