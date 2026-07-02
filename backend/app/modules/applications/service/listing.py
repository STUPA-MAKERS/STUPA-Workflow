"""Filtered application listing, committee read scope, open tasks, export name maps."""

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
    """List/filter applications, committee read scope, tasks and export helpers."""

    async def list_applications(
        self,
        *,
        state_id: UUID | None = None,
        gremium_id: UUID | None = None,
        type_id: UUID | None = None,
        budget_pot_id: UUID | None = None,
        budget_id: UUID | None = None,
        q: str | None = None,
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
        """Filtered, paged, sorted application list (``GET /applications``).

        ``owner_sub`` restricts to own applications (``created_by``) — set for users
        WITHOUT ``application.read`` who may only see their own. ``committee_sub``
        widens that restriction by the committee read scope: also visible are
        applications in a view cost centre of a member gremium or in a ``vote`` state
        for one. Both are OR-combined; with neither set there is no read restriction
        (full view for ``application.read``/admin)."""
        # Unconfirmed guest applications stay invisible until the email is confirmed
        # (existing + logged-in applications carry ``email_confirmed_at``).
        filters: list[ColumnElement[bool]] = [Application.email_confirmed_at.is_not(None)]
        # Read scope: own applications OR committee scope, OR-combined; without
        # ``owner_sub``/``committee_sub`` the list stays unfiltered.
        read_scope: list[ColumnElement[bool]] = []
        if owner_sub is not None:
            read_scope.append(Application.created_by == owner_sub)
        if committee_sub is not None:
            read_scope.extend(await self._committee_read_clauses(committee_sub))
        if read_scope:
            filters.append(or_(*read_scope))
        if state_id is not None:
            filters.append(Application.current_state_id == state_id)
        if gremium_id is not None:
            filters.append(Application.gremium_id == gremium_id)
        if type_id is not None:
            filters.append(Application.type_id == type_id)
        if budget_pot_id is not None:
            filters.append(Application.budget_pot_id == budget_pot_id)
        if budget_id is not None:
            # Cost centre incl. subtree via the ``path_key`` prefix (node itself +
            # all descendants ``<path>-…``). Unknown cost centre → empty list.
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
        # Fuzzy search on MEANINGFUL text: title + string answer values of the
        # ``data`` JSONB — no ids/enums/numbers. Postgres uses the IMMUTABLE
        # ``app_search_text(data)`` function (the trigram index expression); the
        # SQLite fallback (unit stubs) lacks it → whole ``data`` blob as text
        # (substring ILIKE only).
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
            # ``created_to`` is inclusive → until end of day (< next day 00:00 UTC).
            end = datetime.combine(created_to + timedelta(days=1), time.min, UTC)
            filters.append(Application.created_at < end)

        sort_col = Application.amount if sort == "amount" else Application.created_at
        ordering = (sort_col.asc() if order == "asc" else sort_col.desc()).nulls_last()
        # Active search ⇒ most relevant first (rank), then the chosen sort as
        # deterministic tiebreak; unchanged otherwise.
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
                    budgetPotId=app.budget_pot_id,
                    amount=app.amount,
                    currency=app.currency,
                    createdAt=app.created_at,
                    updatedAt=app.updated_at,
                )
            )
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    async def _committee_read_clauses(self, sub: str) -> list[ColumnElement[bool]]:
        """Committee read scope as SQL clauses (OR-combined with the owner filter).

        Three paths — mirrored from ``access._committee_can_read`` (detail view):

        * cost centre (node OR ancestor) with ``view_gremium_id`` in a member
          gremium → the whole subtree (``path_key`` prefix),
        * current ``vote`` state with ``config.gremiumId`` in a member gremium, and
        * legacy: voted in a meeting of a member gremium (``vote → meeting.gremium_id``).

        Both functions MUST cover the same paths so a listed application is also
        openable (and vice versa). No active memberships → empty list (no extra
        scope)."""
        from app.modules.admin.gremium_roles import gremium_member_ids

        member_ids = await gremium_member_ids(self.session, sub)
        if not member_ids:
            return []
        clauses: list[ColumnElement[bool]] = []

        # (a) Member view cost centres (node/ancestor) incl. subtree: first the
        #     "root" paths with a matching ``view_gremium_id``, then all applications
        #     whose ``budget_id`` points at one of those paths OR a descendant.
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

        # (b) Current ``vote`` state for a member gremium. JSONB ``config`` evaluated
        #     in Python (dialect-neutral, like ``list_tasks``); the set of ``vote``
        #     states is small.
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

        # (c) Legacy: voted in a meeting of a member gremium. Applications with a
        #     ``Vote`` whose ``meeting.gremium_id`` belongs to one of the gremien —
        #     mirrored from ``access._committee_can_read`` (c).
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
        """``(type_names, gremium_names)`` for the application export (xlsx)."""
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
        """``True`` if ``sub`` is currently (valid term) a member of the gremium."""
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
        """Open tasks of the principal.

        An application is a task when the principal can act on it:
        * a ``vote`` state + gremium membership (or admin) → vote, **or**
        * at least one **manual** transition is firable (guard satisfied) and the
          principal may fire transitions (``application.transition`` / admin).
        """
        from app.modules.flow.service import FlowService

        flow = FlowService(self.session)
        is_admin = "admin" in principal.roles
        can_transition = is_admin or principal.has("application.transition")

        # All open (confirmed) applications with a current state — newest first.
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
                if is_admin:
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
                # Only firable manual transitions with ``requiresAction`` count —
                # optional actions create no pseudo-task; a terminal state (no exits)
                # is not a task, also for one's own submission.
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
                        budgetPotId=app.budget_pot_id,
                        amount=app.amount,
                        currency=app.currency,
                        createdAt=app.created_at,
                        updatedAt=app.updated_at,
                    )
                )
        return items
