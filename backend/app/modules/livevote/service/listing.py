"""Detail read, meeting list, filter gremien, and the keyset/search timeline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, or_, select

from app.modules.admin.gremium_roles import gremium_ids_with_permission
from app.modules.admin.models import Gremium
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.models import Meeting
from app.modules.livevote.schemas import MeetingGremiumOut, MeetingOut, MeetingPage
from app.modules.livevote.service.paging import (
    _decode_cursor,
    _decode_offset,
    _encode_cursor,
    _encode_offset,
    _sort_ts_expr,
)
from app.modules.livevote.service.permissions import PermissionOps
from app.modules.livevote.service.votes import VoteReadOps
from app.modules.protocol.models import Protocol
from app.search import dialect_of, trigram_rank


class ListingOps(PermissionOps, VoteReadOps):
    """Detail view, list, gremium filter, and paginated timeline."""

    async def get(self, meeting_id: UUID, principal: Principal | None = None) -> MeetingOut:
        """Meeting state (404 if unknown).

        ``principal`` is optional: the WS path (reconnect state) does not need the
        flags and calls without one.
        """
        meeting = await self._get(meeting_id)
        votes = (await self._votes_for([meeting.id])).get(meeting.id, [])
        return await self._emit(
            meeting,
            principal,
            protocol_id=await self._protocol_id(meeting.id),
            votes=votes,
        )

    async def list(self, principal: Principal, gremium_id: UUID | None = None) -> list[MeetingOut]:
        """Meetings (newest first), optionally filtered to one gremium."""
        stmt = select(Meeting).order_by(Meeting.created_at.desc())
        if gremium_id is not None:
            stmt = stmt.where(Meeting.gremium_id == gremium_id)
        visible = await self._visible_gremium_ids(principal)
        if visible is not None:
            # Delegation recipients see "their" meetings even without membership.
            delegated = await self._delegated_meeting_ids(principal.sub)
            stmt = stmt.where(or_(Meeting.gremium_id.in_(visible), Meeting.id.in_(delegated)))
        meetings = list((await self.session.execute(stmt)).scalars().all())
        return await self._decorate(meetings, principal)

    async def list_filter_gremien(self, principal: Principal) -> list[MeetingGremiumOut]:
        """Gremien (id + name) for the meetings-overview filter.

        Exactly the gremien in which the principal has AT LEAST ONE visible meeting
        — not the membership list. Visibility matches timeline/list
        (``_visible_gremium_ids`` plus individually delegated meetings).
        """
        stmt = select(Meeting.gremium_id, Gremium.name).join(
            Gremium, Gremium.id == Meeting.gremium_id
        )
        visible = await self._visible_gremium_ids(principal)
        if visible is not None:
            # Delegation recipients see "their" meetings even without membership —
            # their gremium then belongs into the filter as well.
            delegated = await self._delegated_meeting_ids(principal.sub)
            stmt = stmt.where(or_(Meeting.gremium_id.in_(visible), Meeting.id.in_(delegated)))
        rows = (await self.session.execute(stmt.distinct())).all()
        items = [MeetingGremiumOut(id=gid, name=name) for gid, name in rows]
        items.sort(key=lambda g: g.name.casefold())
        return items

    async def list_timeline(
        self,
        principal: Principal,
        *,
        direction: Literal["past", "upcoming"],
        cursor: str | None = None,
        limit: int = 20,
        gremium_id: UUID | None = None,
        q: str | None = None,
    ) -> MeetingPage:
        """Keyset-paginated meeting timeline around *now*.

        ``upcoming`` runs forward from now (earliest first, undated meetings last),
        ``past`` backward (latest first). The cursor carries the sort timestamp and
        id of the last delivered meeting — stable even on equal dates.

        With an active search (``q``) the timeline COLLAPSES into a single
        relevance-sorted list (no past/upcoming split, no now marker): the buckets
        cannot be relevance-ranked. Visibility scoping + ``gremium_id`` filter stay;
        the cursor then carries an offset.
        """
        if q and q.strip():
            return await self._search_timeline(
                principal, q=q.strip(), cursor=cursor, limit=limit, gremium_id=gremium_id
            )
        sort_ts = _sort_ts_expr()
        # Naive "now" timestamp — comparable with the date-based sort key.
        now_ts = datetime.now(UTC).replace(tzinfo=None)
        cur = _decode_cursor(cursor)
        # Bucket status-aware (not purely by time): ``live`` is always upcoming (a
        # meeting running since morning must not slip into the past), ``closed``
        # always past, ``planned`` decided by its date.
        is_upcoming = or_(
            Meeting.status == "live",
            and_(Meeting.status == "planned", sort_ts >= now_ts),
        )
        is_past = and_(
            Meeting.status != "live",
            or_(Meeting.status == "closed", sort_ts < now_ts),
        )
        stmt = select(Meeting, sort_ts)
        if gremium_id is not None:
            stmt = stmt.where(Meeting.gremium_id == gremium_id)
        visible = await self._visible_gremium_ids(principal)
        if visible is not None:
            # Delegation recipients see "their" meetings even without membership.
            delegated = await self._delegated_meeting_ids(principal.sub)
            stmt = stmt.where(or_(Meeting.gremium_id.in_(visible), Meeting.id.in_(delegated)))
        if direction == "upcoming":
            stmt = stmt.where(is_upcoming)
            if cur is not None:
                cts, cid = cur
                stmt = stmt.where(or_(sort_ts > cts, and_(sort_ts == cts, Meeting.id > cid)))
            stmt = stmt.order_by(sort_ts.asc(), Meeting.id.asc())
        else:
            stmt = stmt.where(is_past)
            if cur is not None:
                cts, cid = cur
                stmt = stmt.where(or_(sort_ts < cts, and_(sort_ts == cts, Meeting.id < cid)))
            stmt = stmt.order_by(sort_ts.desc(), Meeting.id.desc())
        # Load one row past the limit — tells whether a next page exists.
        rows = (await self.session.execute(stmt.limit(limit + 1))).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = await self._decorate([row[0] for row in rows], principal)
        next_cursor = _encode_cursor(rows[-1][1], rows[-1][0].id) if has_more and rows else None
        return MeetingPage(items=items, nextCursor=next_cursor)

    async def _search_timeline(
        self,
        principal: Principal,
        *,
        q: str,
        cursor: str | None,
        limit: int,
        gremium_id: UUID | None,
    ) -> MeetingPage:
        """Relevance-sorted meeting search (collapsed timeline, offset paging).

        Trigram ranking over title + gremium name + protokollant display name.
        Visibility (``_visible_gremium_ids`` + delegations) and the ``gremium_id``
        filter stay identical to the keyset path; only the bucket split + now marker
        drop. The cursor carries an offset here (relevance ranking, no keyset).
        """
        offset = _decode_offset(cursor)
        where, rank = trigram_rank(
            q,
            [Meeting.title, Gremium.name, PrincipalRow.display_name],
            dialect=dialect_of(self.session),
        )
        stmt = (
            select(Meeting)
            .join(Gremium, Gremium.id == Meeting.gremium_id)
            .outerjoin(PrincipalRow, PrincipalRow.id == Meeting.protokollant_id)
            .where(where)
        )
        if gremium_id is not None:
            stmt = stmt.where(Meeting.gremium_id == gremium_id)
        visible = await self._visible_gremium_ids(principal)
        if visible is not None:
            delegated = await self._delegated_meeting_ids(principal.sub)
            stmt = stmt.where(or_(Meeting.gremium_id.in_(visible), Meeting.id.in_(delegated)))
        # Most relevant first; id as deterministic tiebreak (stable offset paging).
        stmt = stmt.order_by(rank.desc(), Meeting.id.desc()).offset(offset)
        # Load one row past the limit — tells whether a next page exists.
        rows = (await self.session.execute(stmt.limit(limit + 1))).scalars().all()
        has_more = len(rows) > limit
        page_rows = list(rows[:limit])
        items = await self._decorate(page_rows, principal)
        next_cursor = _encode_offset(offset + limit) if has_more else None
        return MeetingPage(items=items, nextCursor=next_cursor)

    async def _decorate(self, meetings: list[Meeting], principal: Principal) -> list[MeetingOut]:
        """Enrich meetings with protocol id, votes, and per-principal RBAC flags.

        Shared by :meth:`list` and :meth:`list_timeline`; loads everything batched
        (no N+1) and filters NO meetings — visibility is module-wide, the flags are
        purely per principal.
        """
        if not meetings:
            return []
        # Protocol ids batched (no N+1): meeting_id -> protocol.id.
        proto_rows = (
            await self.session.execute(
                select(Protocol.meeting_id, Protocol.id).where(
                    Protocol.meeting_id.in_([m.id for m in meetings])
                )
            )
        ).all()
        proto_by_meeting = {meeting_id: pid for meeting_id, pid in proto_rows}
        # Load the principal's gremium scopes once (no N+1 per meeting). Admin/global
        # ``meeting.manage`` short-circuits all gremium queries.
        all_gids = {m.gremium_id for m in meetings}
        # Gremium names batched (the timeline shows the affiliation).
        gremium_names: dict[UUID, str] = {
            gid: name
            for gid, name in (
                await self.session.execute(
                    select(Gremium.id, Gremium.name).where(Gremium.id.in_(all_gids))
                )
            ).all()
        }
        # Protokollant names batched (no N+1) — otherwise the timeline shows no
        # protokollant (``protokollantName`` null) although the id is persisted.
        prot_ids = {m.protokollant_id for m in meetings if m.protokollant_id is not None}
        prot_names: dict[UUID, str | None] = (
            {
                pid: (display_name or email)
                for pid, display_name, email in (
                    await self.session.execute(
                        select(
                            PrincipalRow.id,
                            PrincipalRow.display_name,
                            PrincipalRow.email,
                        ).where(PrincipalRow.id.in_(prot_ids))
                    )
                ).all()
            }
            if prot_ids
            else {}
        )
        if "admin" in principal.roles or principal.has("meeting.manage"):
            manage_ids = write_ids = votes_mgmt_ids = vote_ids = all_gids
            my_id: UUID | None = None
        else:
            manage_ids = await gremium_ids_with_permission(
                self.session, principal.sub, "session.manage"
            )
            write_ids = manage_ids | await gremium_ids_with_permission(
                self.session, principal.sub, "protocol.write"
            )
            votes_mgmt_ids = manage_ids | await gremium_ids_with_permission(
                self.session, principal.sub, "vote.manage"
            )
            vote_ids = await gremium_ids_with_permission(self.session, principal.sub, "vote.cast")
            my_id = await self._principal_id(principal.sub)
        votes_by_meeting = await self._votes_for([m.id for m in meetings])
        out: list[MeetingOut] = []
        for m in meetings:
            is_prot = m.protokollant_id is not None and m.protokollant_id == my_id
            out.append(
                self._to_out(
                    m,
                    proto_by_meeting.get(m.id),
                    can_manage=m.gremium_id in manage_ids,
                    can_write=(m.gremium_id in write_ids) or is_prot,
                    can_manage_votes=(m.gremium_id in votes_mgmt_ids) or is_prot,
                    can_vote=m.gremium_id in vote_ids,
                    gremium_name=gremium_names.get(m.gremium_id),
                    protokollant_name=(
                        prot_names.get(m.protokollant_id) if m.protokollant_id is not None else None
                    ),
                    votes=votes_by_meeting.get(m.id, []),
                )
            )
        return out
