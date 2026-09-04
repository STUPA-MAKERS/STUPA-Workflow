"""Filtered application listing, Gremium read scope, open tasks, export name maps."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Text, cast, false, func, or_, select

from app.modules.admin.models import ApplicationType, Gremium, GremiumMembership
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationListItem
from app.modules.applications.service.service_base import (
    ApplicationsServiceBase,
    _title_of,
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
        state_id: UUID | None = None,
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

        `archived` defaults to False, so the working list hides archived applications
        without every caller remembering to ask. `True` lists only the archived ones and
        `None` lists both. The count follows the same filter, or the total would promise
        rows the page does not contain.
        """
        # An unconfirmed guest application stays invisible until the applicant confirms
        # the email. An existing or logged-in application carries `email_confirmed_at`.
        filters: list[ColumnElement[bool]] = [Application.email_confirmed_at.is_not(None)]
        read_scope: list[ColumnElement[bool]] = []
        if owner_sub is not None:
            read_scope.append(Application.created_by == owner_sub)
        if committee_sub is not None:
            read_scope.extend(await self._committee_read_clauses(committee_sub))
        if read_scope:
            filters.append(or_(*read_scope))
        # Archived applications leave the working list by default. `None` asks for both,
        # which is what a search across everything wants.
        if archived is False:
            filters.append(Application.archived_at.is_(None))
        elif archived is True:
            filters.append(Application.archived_at.is_not(None))
        if state_id is not None:
            filters.append(Application.current_state_id == state_id)
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
        # values of the `data` JSONB. It skips ids, enums and numbers. Postgres uses the
        # IMMUTABLE `app_search_text(data)` function, which is the trigram index
        # expression. The SQLite fallback for the unit stubs has no such function and
        # searches the whole `data` blob as text with a substring ILIKE.
        rank_expr: ColumnElement[Any] | None = None
        if q and q.strip():
            dialect = dialect_of(self.session)
            search_col = (
                func.app_search_text(Application.data)
                if dialect == "postgresql"
                else cast(Application.data, Text)
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

        sort_col = Application.amount if sort == "amount" else Application.created_at
        ordering = (sort_col.asc() if order == "asc" else sort_col.desc()).nulls_last()
        # An active search puts the most relevant row first. The chosen sort then acts
        # as a deterministic tiebreak. Without a search the order does not change.
        order_by = (rank_expr.desc(), ordering) if rank_expr is not None else (ordering,)

        total = await self.session.scalar(
            select(func.count()).select_from(Application).where(*filters)
        )
        rows = (
            await self.session.scalars(
                select(Application).where(*filters).order_by(*order_by).limit(limit).offset(offset)
            )
        ).all()
        items: list[ApplicationListItem] = []
        for app in rows:
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
                )
            )
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

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
        #     JSONB `config` to stay dialect-neutral, as `list_tasks` does. The set of
        #     `vote` states is small.
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

    async def _in_gremium(self, sub: str, gremium_id: UUID) -> bool:
        """Tell if `sub` is a member of the Gremium with a currently valid term."""
        from app.modules.auth.models import Principal as PrincipalRow

        now = datetime.now(UTC)
        row = await self.session.scalar(
            select(GremiumMembership.id)
            .join(PrincipalRow, PrincipalRow.id == GremiumMembership.principal_id)
            .where(
                PrincipalRow.sub == sub,
                GremiumMembership.gremium_id == gremium_id,
                (GremiumMembership.valid_from.is_(None)) | (GremiumMembership.valid_from <= now),
                (GremiumMembership.valid_until.is_(None)) | (GremiumMembership.valid_until > now),
            )
            .limit(1)
        )
        return row is not None

    async def list_tasks(self, principal: Any) -> list[ApplicationListItem]:
        """List the open tasks of the principal.

        An application is a task when the principal can act on it:

        * the application is in a `vote` state and the principal is a member of the
          Gremium or an admin, so the principal can vote, or
        * at least one manual transition is firable because its guard holds, and the
          principal may fire transitions with `application.transition` or as admin.
        """
        from app.modules.flow.service import FlowService

        flow = FlowService(self.session)
        # Both go through `Principal.has`, never through `principal.roles`: `has` grants
        # the admin role every right and still applies the OAuth scope cap. A vote state
        # is actionable only for someone who may actually cast, and `vote.cast` is in
        # FORBIDDEN_PERMISSIONS, so no token ever sees one as a task.
        can_cast = principal.has("vote.cast")
        can_transition = principal.has("application.transition")

        apps = (
            await self.session.scalars(
                select(Application)
                .where(
                    Application.current_state_id.is_not(None),
                    Application.email_confirmed_at.is_not(None),
                )
                .order_by(Application.created_at.desc())
            )
        ).all()
        if not apps:
            return []
        states = (
            await self.session.scalars(
                select(State).where(State.id.in_({a.current_state_id for a in apps}))
            )
        ).all()
        by_id = {s.id: s for s in states}

        items: list[ApplicationListItem] = []
        for app in apps:
            if app.current_state_id is None:
                continue
            s = by_id.get(app.current_state_id)
            if s is None:
                continue
            ok = False
            if s.kind == "vote":
                if can_cast:
                    ok = True
                else:
                    cfg = s.config if isinstance(s.config, dict) else {}
                    gid = cfg.get("gremiumId")
                    ok = (
                        isinstance(gid, str)
                        and bool(gid)
                        and await self._in_gremium(principal.sub, UUID(gid))
                    )
            if not ok and (can_transition or app.created_by == principal.sub):
                # Only a firable manual transition with `requiresAction` counts. An
                # optional action creates no pseudo-task. A terminal state has no exit
                # and is no task, also for an application of the principal.
                ok = any(
                    t.requires_action for t in await flow.available_transitions(app.id, principal)
                )
            if ok:
                items.append(
                    ApplicationListItem(
                        id=app.id,
                        typeId=app.type_id,
                        title=_title_of(app.data),
                        state=await self._state_out_resolved(s),
                        gremiumId=app.gremium_id,
                            amount=app.amount,
                        currency=app.currency,
                        createdAt=app.created_at,
                        updatedAt=app.updated_at,
                    )
                )
        return items
