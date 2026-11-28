"""The assembly of the render document: header, attendance, quorum, agenda items, votes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date as _date
from datetime import datetime
from datetime import time as _time
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.modules.applications.models import Application
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.delegations.models import MeetingDelegation
from app.modules.documents.service import anlage_reference
from app.modules.gremien.models import Gremium, GremiumMembership, GremiumRole
from app.modules.media.models import MarkdownDocument
from app.modules.meetings.agenda_service import agenda_order, title_of
from app.modules.meetings.keepers import agenda_positions, keeper_periods, principal_names
from app.modules.meetings.models import Meeting, MeetingAgendaItem, MeetingAttendance
from app.modules.meetings.present import VOTE_PERMISSION, meeting_present
from app.modules.meetings.protocol_models import Protocol
from app.modules.protocol.markdown import (
    KeeperLine,
    ProtocolDoc,
    build_protocol_document,
    demote_headings,
    mark_vote_blocks,
    replace_vote_blocks,
    top_time_note,
    votes_in_body,
)
from app.modules.protocol.plan_anlage import plan_reference, with_plan_reference
from app.modules.protocol.public import PublicAttendance, PublicDecision, PublicSnapshot, PublicTop
from app.modules.protocol.service.base import ProtocolServiceBase
from app.modules.protocol.service.common import HeaderMeta, _redacted_item
from app.modules.protocol.service.snippets import _election_pairs, _repeat_marks, _snippet
from app.modules.voting.models import Vote
from app.modules.voting.service import VotingService
from app.modules.voting.tally import meeting_quorate
from app.shared.blackout import black_out


class DocumentOps(ProtocolServiceBase):
    """Builds the typst document of a protocol."""

    async def _build_document(
        self,
        protocol: Protocol,
        *,
        public: bool = False,
        snapshot: PublicSnapshot | None = None,
    ) -> str:
        """Build the protocol Markdown document with its header.

        The per-item editor, that is the agenda, is the source of truth. If agenda items
        exist, the document is assembled from their Markdown bodies and the decision
        snippets. If not, it falls back to the free text in `protocol.markdown`, which
        is then the whole public body too.

        The document holds no circular vote of the Gremium: such a decision shows in the
        list of decisions only (§F/meetings/voting/000949).

        `public=True` redacts a non-public item and the header metadata. The mailed
        variant must not carry the names of the attendees, of the excused members, of
        the absentees or of the protocol keepers. `_header_meta` then returns empty name
        lists and the counters only. The quorum statement rests on the counters and
        stays meaningful.
        """
        meeting = await self.session.get(Meeting, protocol.meeting_id)
        gremium = await self.session.get(Gremium, protocol.gremium_id)
        title = meeting.title if meeting is not None else "Protokoll"
        assembled = await self._assemble_from_agenda(
            protocol.meeting_id,
            public=public,
            tops=snapshot.tops if snapshot is not None else None,
        )
        header = await self._header_meta(meeting, public=public)
        free_text = (
            black_out(protocol.markdown) if public and protocol.markdown else protocol.markdown
        )
        if snapshot is not None:
            snapshot.attendance = PublicAttendance(
                present=header.present_count,
                excused=header.excused_count,
                absent=header.absent_count,
                guests=header.guest_count,
            )
            if not assembled:
                snapshot.markdown = free_text
        date, start_time = self._start_of(meeting)
        return build_protocol_document(
            ProtocolDoc(
                title=title,
                gremium_name=getattr(gremium, "name", None) if gremium is not None else None,
                cd_variant=protocol.cd_variant,
                date=date,
                start_time=start_time,
                end_time=self._local_end_time(
                    getattr(meeting, "closed_at", None) if meeting is not None else None
                ),
                started_at=(
                    f"{date.isoformat()} {start_time.strftime('%H:%M')}"
                    if date is not None and start_time is not None
                    else None
                ),
                kind=getattr(meeting, "kind", None),
                location=getattr(meeting, "location", None),
                form=getattr(meeting, "form", None),
                protokollant=header.protokollant,
                keepers=header.keepers,
                present=header.present,
                excused=header.excused,
                absent=header.absent,
                datalines=header.datalines,
                quorate=await self._quorate(gremium, meeting, header.present_count),
                signatures=tuple(getattr(gremium, "protocol_signatures", None) or ()),
                markdown=assembled or free_text,
            )
        )

    def _start_of(self, meeting: Meeting | None) -> tuple[_date | None, _time | None]:
        """Return the local date and time of the start: the real one, else the planned.

        `started_at = COALESCE(meeting.started_at, planned start)`. A meeting
        from before the real start existed shows the planned date and time.
        """
        if meeting is None:
            return None, None
        started = getattr(meeting, "started_at", None)
        if isinstance(started, datetime):
            local = started.astimezone(self._tz())
            return local.date(), local.time().replace(second=0, microsecond=0)
        return meeting.date, getattr(meeting, "start_time", None)

    def _local_end_time(self, closed_at: object) -> _time | None:
        """Convert `meeting.closed_at` from UTC to local time for the end line."""
        return (
            closed_at.astimezone(self._tz()).time().replace(second=0, microsecond=0)
            if isinstance(closed_at, datetime)
            else None
        )

    def _local_hhmm(self, value: datetime | None) -> str | None:
        return None if value is None else value.astimezone(self._tz()).strftime("%H:%M")

    async def _keeper_lines(self, meeting: Meeting) -> list[KeeperLine]:
        """Build the header lines of the keeper periods that started.

        A TOP number comes from the current agenda order. A period without an agenda
        item, or with a deleted one, carries the time only.
        """
        periods = [p for p in await keeper_periods(self.session, [meeting.id]) if p.from_at]
        if not periods:
            return []
        names = await principal_names(self.session, {p.principal_id for p in periods})
        positions = await agenda_positions(self.session, [meeting.id])
        return [
            KeeperLine(
                name=names.get(p.principal_id) or "—",
                from_time=self._local_hhmm(p.from_at),
                to_time=self._local_hhmm(p.to_at),
                from_top=positions.get(p.from_agenda_item_id) if p.from_agenda_item_id else None,
                to_top=positions.get(p.to_agenda_item_id) if p.to_agenda_item_id else None,
            )
            for p in periods
        ]

    async def _voting_members(self, gremium_id: UUID) -> int:
        """Count the members of the Gremium whose role holds `vote.cast`."""
        return (
            await self.session.scalar(
                select(func.count(GremiumMembership.principal_id.distinct()))
                .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
                .where(
                    GremiumMembership.gremium_id == gremium_id,
                    GremiumRole.permissions.contains([VOTE_PERMISSION]),
                )
            )
        ) or 0

    async def _quorate(
        self, gremium: object | None, meeting: Meeting | None, present_count: int
    ) -> bool | None:
        """Compute the quorum from the present count and the members with a voting right.

        A closed meeting gives the member count that its close fixed, so a new render
        gives the same quorum (§F/meetings/protocols/000357). A meeting that is not
        closed, and a meeting without a fixed count, counts the members of the Gremium
        whose role holds `vote.cast` now. The rule is the one that closes the votes of
        the meeting (`meeting_quorate`): the quorum of the Gremium in percent, in a
        Wiederholungssitzung its repeat quorum when that is set, and the least number
        of present persons. A Gremium without a quorum is always quorate, as its votes
        are.

        Returns:
            The quorum result, or `None` when the Gremium or its members are missing.
            The PDF then shows no quorum statement.
        """
        gremium_id = getattr(gremium, "id", None)
        if gremium_id is None:
            return None
        fixed: int | None = getattr(meeting, "eligible_count", None)
        members = (
            fixed
            if fixed is not None and getattr(meeting, "status", None) == "closed"
            else await self._voting_members(gremium_id)
        )
        repeat: int | None = (
            getattr(gremium, "repeat_quorum_percent", None)
            if getattr(meeting, "kind", None) == "repeat"
            else None
        )
        percent: int | None = (
            repeat if repeat is not None else getattr(gremium, "quorum_percent", None)
        )
        min_present: int | None = getattr(gremium, "quorum_min_present", None)
        return (
            None
            if members == 0
            else meeting_quorate(percent, min_present, present=present_count, members=members)
        )

    async def _header_meta(self, meeting: Meeting | None, *, public: bool = False) -> HeaderMeta:
        """Resolve the protocol keepers and the attendance groups for the header.

        A list entry holds the display name of the principal, or the sub as a
        fallback. A delegate names the represented members: "Lea Kurz (für Max
        Muster)" (§F/meetings/protocols/003153). The excused members are their own
        group. `public=True`
        redacts the person-related header metadata for the mailed variant. The full
        attendance lists and the names of the protocol keepers must never go
        external. The method then emits the counters only, as the data lines
        `Anwesend: n`, `Entschuldigt: n` and `Abwesend: n`.

        The guests of a public meeting appear as a count only, never by name. The legacy
        key `protokollant` names every keeper once, for a render service that does not
        read `keepers`.
        """
        if meeting is None:
            return HeaderMeta()
        rows = await self._attendance_lines(meeting.id)
        present = [line for status, line in rows if status == "present"]
        excused = [line for status, line in rows if status == "excused"]
        absent = [line for status, line in rows if status == "absent"]
        present_count = await meeting_present(self.session, meeting)
        from app.modules.livevote.guests import GuestService

        guests = await GuestService(self.session).attended_count(meeting.id)
        guest_lines = [f"Gäste: {guests}"] if guests else []
        if public:
            return HeaderMeta(
                present_count=present_count,
                excused_count=len(excused),
                absent_count=len(absent),
                guest_count=guests,
                datalines=[
                    f"Anwesend: {present_count}",
                    f"Entschuldigt: {len(excused)}",
                    f"Abwesend: {len(absent)}",
                    *guest_lines,
                ],
            )
        keepers = await self._keeper_lines(meeting)
        protokollant = (
            ", ".join(dict.fromkeys(k.name for k in keepers))
            if keepers
            else await self._legacy_protokollant(meeting)
        )
        return HeaderMeta(
            protokollant=protokollant,
            keepers=keepers,
            present=present,
            excused=excused,
            absent=absent,
            present_count=present_count,
            datalines=guest_lines,
        )

    async def _attendance_lines(self, meeting_id: UUID) -> list[tuple[str, str]]:
        """Return the status and the list entry of each person with an attendance.

        A person with a record has one, and so has a pool substitute on a seat without a
        record (§F/meetings/delegations/003152). A delegate names the represented members
        (§F/meetings/protocols/003153). The entries and the represented members are in
        the order of the names.
        """
        records = (
            await self.session.execute(
                select(MeetingAttendance.status, PrincipalRow.display_name, PrincipalRow.sub)
                .join(PrincipalRow, PrincipalRow.id == MeetingAttendance.principal_id)
                .where(MeetingAttendance.meeting_id == meeting_id)
            )
        ).all()
        delegate, delegator = aliased(PrincipalRow), aliased(PrincipalRow)
        delegations = (
            await self.session.execute(
                select(
                    delegate.sub,
                    delegate.display_name,
                    delegator.display_name,
                    delegator.sub,
                    MeetingDelegation.via_pool,
                )
                .join(delegate, delegate.id == MeetingDelegation.delegate_principal_id)
                .join(delegator, delegator.id == MeetingDelegation.delegator_principal_id)
                .where(
                    MeetingDelegation.meeting_id == meeting_id,
                    MeetingDelegation.delegate_voting.is_(True),
                )
            )
        ).all()
        behalf = {
            sub: sorted(
                (name or other for d_sub, _, name, other, _ in delegations if d_sub == sub),
                key=str.casefold,
            )
            for sub in {d_sub for d_sub, _, _, _, _ in delegations}
        }
        recorded = {sub: (status, name or sub) for status, name, sub in records}
        seats = {
            sub: ("present", name or sub)
            for sub, name, _, _, pool in delegations
            if pool and sub not in recorded
        }
        lines = [
            (status, f"{name} (für {', '.join(behalf[sub])})" if sub in behalf else name)
            for sub, (status, name) in (recorded | seats).items()
        ]
        return sorted(lines, key=lambda line: line[1].casefold())

    async def _legacy_protokollant(self, meeting: Meeting) -> str | None:
        """Return the name of `meeting.protokollant_id` for a meeting without periods."""
        if getattr(meeting, "protokollant_id", None) is None:
            return None
        return await self.session.scalar(
            select(PrincipalRow.display_name).where(PrincipalRow.id == meeting.protokollant_id)
        )

    async def _has_non_public(self, meeting_id: UUID) -> bool:
        """Return True if the meeting has a non-public agenda item.

        The result drives the dual render.
        """
        return bool(
            await self.session.scalar(
                select(func.count())
                .select_from(MeetingAgendaItem)
                .where(
                    MeetingAgendaItem.meeting_id == meeting_id,
                    MeetingAgendaItem.non_public.is_(True),
                )
            )
        )

    async def _assemble_from_agenda(
        self,
        meeting_id: UUID,
        *,
        public: bool = False,
        tops: list[PublicTop] | None = None,
    ) -> str:
        """Build the protocol Markdown from the agenda item bodies and their votes.

        `public=True` redacts a non-public item. The heading stays, and so does the
        numbering. A placeholder replaces the body and the decision snippets.
        With `tops`, the method also collects the structured public TOPs for the
        public protocols page, in the same pass and without extra queries.

        The items follow the agenda order of the meeting page, so "TOP n" in the PDF and
        the TOP numbers of the keeper periods agree. An application item has no title of
        its own: it shows the title of its application, as on the meeting page.

        Each item heading is a top-level `#` WITHOUT a "TOP n:" prefix, because the
        typst service numbers the sections itself as "TOP 1", "TOP 2" and so on. A `##`
        would get the number "TOP 0.1", and a manual prefix would appear twice. The body
        headings move down one level, because otherwise every `#` counts as its own
        agenda item. A public non-public item gets a neutral heading, because the
        original title can encode the sensitive subject.

        A cancelled vote has no result and gets no empty tally box. In the public text
        an election callout of the protokollant shows the elected names only, not every
        candidate with the votes. A vote that the protokollant already put into the text
        with the same snippet gets no second box, also for two votes with one question.
        A poll is no decision and stays out of the public decisions. The public list
        shows a closed decision also when its snippet is already in the text, and
        `inText` tells the detail page to show no second box for it.
        """
        items = (
            (
                await self.session.execute(
                    select(MeetingAgendaItem)
                    .where(MeetingAgendaItem.meeting_id == meeting_id)
                    .order_by(*agenda_order())
                )
            )
            .scalars()
            .all()
        )
        if not items:
            return ""
        app_ids = [
            app_id
            for item in items
            if (app_id := getattr(item, "application_id", None)) is not None
        ]
        app_rows = (
            (
                await self.session.execute(
                    select(Application.id, Application.data).where(Application.id.in_(app_ids))
                )
            ).all()
            if app_ids
            else []
        )
        app_titles = {app_id: title_of(data) for app_id, data in app_rows}
        voting = VotingService(self.session)
        assembled = [
            await self._assemble_item(number, item, app_titles, voting, public=public)
            for number, item in enumerate(items, start=1)
        ]
        if tops is not None:
            tops.extend(top for _, top in assembled)
        return "\n\n".join(block for block, _ in assembled) + "\n"

    async def _assemble_item(
        self,
        number: int,
        item: MeetingAgendaItem,
        app_titles: Mapping[UUID, str | None],
        voting: VotingService,
        *,
        public: bool,
    ) -> tuple[str, PublicTop]:
        """Build the Markdown block and the public TOP of one agenda item.

        A non-public item of the public variant gets the neutral heading and the
        placeholder, and its TOP keeps the number only. An item that the meeting
        reached gets an empty time note in front of its heading, also when it is
        non-public, because the time tells nothing about the subject.
        """
        app_id = getattr(item, "application_id", None)
        own = item.title or (app_titles.get(app_id) if app_id is not None else None)
        heading = (own or "Tagesordnungspunkt").strip()
        block, top = (
            _redacted_item(number)
            if public and item.non_public
            else await self._item_with_votes(number, item, heading, voting, public=public)
        )
        note = top_time_note(getattr(item, "started_at", None), self._tz())
        return (f"{note}\n\n{block}" if note else block), top

    async def _item_with_votes(
        self,
        number: int,
        item: MeetingAgendaItem,
        heading: str,
        voting: VotingService,
        *,
        public: bool,
    ) -> tuple[str, PublicTop]:
        """Build the block of an agenda item from its body and its non-cancelled votes.

        A vote whose snippet is already in the body gets no second box, and a repeated
        vote gets its mark line, in the body or below its own box. An item of a
        Haushaltsplan ends with the reference to the PDF of the plan, once the finalize
        stored it (spec 000876).
        """
        stripped = item.body.strip() if item.body and item.body.strip() else ""
        raw = black_out(stripped) if public else stripped
        votes = (
            (
                await self.session.execute(
                    select(Vote)
                    .where(
                        Vote.agenda_item_id == item.id,
                        Vote.status != "cancelled",
                    )
                    .order_by(Vote.created_at)
                )
            )
            .scalars()
            .all()
        )
        views = [await voting.get(vote.id) for vote in votes]
        marks = _repeat_marks(votes, views)
        tz = self._tz()
        body = replace_vote_blocks(raw, _election_pairs(views, tz)) if public else raw
        plain = [_snippet(view, "Beschlussfrage", public=public, tz=tz) for view in views]
        found = votes_in_body(body, plain)
        voted = mark_vote_blocks(
            body,
            [
                (snippet, marks[vote.id])
                for vote, snippet, in_text in zip(votes, plain, found, strict=True)
                if in_text and vote.id in marks
            ],
        )
        document_id = getattr(item, "plan_document_id", None)
        document = (
            await self.session.get(MarkdownDocument, document_id)
            if document_id is not None
            else None
        )
        marked = with_plan_reference(
            voted, plan_reference(document.name, document.id) if document is not None else None
        )
        snippets = [
            f"{snippet}\n> {marks[vote.id]}" if vote.id in marks else snippet
            for vote, snippet in zip(votes, plain, strict=True)
        ]
        decisions = [
            PublicDecision.from_vote(view).model_copy(update={"in_text": in_text})
            for view, in_text in zip(views, found, strict=True)
            if getattr(view, "status", None) == "closed" and getattr(view, "kind", None) != "poll"
        ]
        anlage = (
            [anlage_reference(item.id, heading, public=public)]
            if getattr(item, "application_id", None) is not None
            else []
        )
        block = [
            f"# {heading}",
            *anlage,
            *([demote_headings(marked)] if marked else []),
            *(snippet for snippet, in_text in zip(snippets, found, strict=True) if not in_text),
        ]
        top = PublicTop(number=number, title=heading, markdown=marked or None, decisions=decisions)
        return "\n\n".join(block), top
