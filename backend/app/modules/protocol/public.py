"""The public version of a protocol and the reads of the public protocols page.

A gremium with `protocols_public` shows its final protocols without login. The
public version holds:

* the meeting title and date, as part of the protocol only;
* the TOPs in the agenda order: a public TOP with its title, its Markdown text
  and its closed decisions; a non-public TOP with its number only;
* the attendance as counts, never a name (no attendee, no keeper, no guest).

The finalization (and the backfill job for older protocols) stores this
version as a snapshot in `protocol.public_content`, in the same pass that
renders the public PDF. The public API serves the snapshot only, so the page
and the PDF always agree, and a protocol without a snapshot never appears.

Visibility fails closed: a protocol is public only when it is final, not held
back, has a snapshot, and its gremium has `protocols_public`. Everything else
gives 404. There is no public meeting read of any kind.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date as _date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, Date, Select, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Gremium
from app.modules.files.storage import ObjectStorage, StorageError
from app.modules.livevote.models import Meeting
from app.modules.media.refs import image_ids_in
from app.modules.protocol.filename import protocol_pdf_filename
from app.modules.protocol.models import Protocol
from app.shared.config_schemas import ElectionConfig
from app.shared.errors import NotFoundError, ServiceUnavailableError
from app.shared.schemas import FrozenCamelModel

logger = logging.getLogger("app.protocol")

SNAPSHOT_VERSION = 1

VoteResult = Literal["passed", "rejected", "tie", "elected", "runoff"]
MajorityRule = Literal["simple", "absolute", "two_thirds"]


def passed_conditions(view: object) -> list[str]:
    """Return the conditions of the decision of a passed vote, else none.

    Only a passed vote makes its proposal the decision of the application.
    """
    passed = getattr(view, "result", None) == "passed"
    proposal = getattr(view, "proposal", None)
    return list(getattr(proposal, "conditions", None) or []) if passed else []


class PublicDecision(FrozenCamelModel, frozen=True):
    """One closed vote of a public TOP: question, counts, result and conditions."""

    question: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    result: VoteResult | None = None
    majority_rule: MajorityRule = Field(default="simple", alias="majorityRule")
    secret: bool = False
    #: The vote is already in the TOP text as a callout: the detail page shows the
    #: text only, the list keeps the result.
    in_text: bool = Field(default=False, alias="inText")
    #: The conditions of the decision, when the vote passed with a proposal.
    conditions: list[str] = Field(default_factory=list)
    #: Personnel elections. The public version names the elected candidates
    #: only; the other candidates appear as a count, and no vote count travels.
    kind: Literal["motion", "election"] = "motion"
    seats: int | None = None
    round: int = 1
    elected: list[str] = Field(default_factory=list)
    other_candidates: int = Field(default=0, alias="otherCandidates")
    by_lot: bool = Field(default=False, alias="byLot")

    @classmethod
    def from_vote(cls, view: object) -> PublicDecision:
        """Build a decision from a `VoteOut`. The tally holds counts only, no voter."""
        tally = getattr(view, "tally", None)
        election = getattr(view, "election", None)
        if getattr(view, "kind", "motion") == "election" and election is not None:
            return cls._from_election(view, election)
        return cls(
            question=getattr(view, "question", None),
            counts=dict(getattr(tally, "counts", None) or {}),
            result=getattr(view, "result", None),
            majorityRule=getattr(view, "majority_rule", "simple"),
            secret=bool(getattr(view, "secret", False)),
            conditions=passed_conditions(view),
        )


    @classmethod
    def _from_election(cls, view: object, election: ElectionConfig) -> PublicDecision:
        """Build the public decision of an election: elected names and a count."""
        stored = getattr(view, "election_result", None)
        elected_ids: list[str] = list(stored.elected) if stored is not None else []
        names = {c.id: c.name for c in election.candidates}
        lot = stored.lot if stored is not None else None
        return cls(
            question=getattr(view, "question", None),
            result=getattr(view, "result", None),
            secret=bool(getattr(view, "secret", False)),
            kind="election",
            seats=election.seats,
            round=int(getattr(view, "round", 1) or 1),
            elected=[names.get(cid, cid) for cid in elected_ids],
            otherCandidates=len(election.candidates) - len(elected_ids),
            byLot=lot is not None and lot.drawn is not None,
        )


class PublicTop(FrozenCamelModel, frozen=True):
    """One TOP of the public version. A non-public TOP has its number only."""

    number: int
    title: str | None = None
    non_public: bool = Field(default=False, alias="nonPublic")
    markdown: str | None = None
    decisions: list[PublicDecision] = Field(default_factory=list)

    @property
    def results(self) -> list[VoteResult]:
        """Return the results of the decisions that have one."""
        return [d.result for d in self.decisions if d.result is not None]


class PublicAttendance(FrozenCamelModel, frozen=True):
    """The attendance of the public version: counts only."""

    present: int = 0
    excused: int = 0
    absent: int = 0
    guests: int = 0


class PublicSnapshot(BaseModel):
    """The stored public version of one protocol (`protocol.public_content`).

    The model stays mutable, because it collects the public version in the same pass
    that renders the public PDF: `ProtocolService._build_document` fills it in place.
    """

    model_config = ConfigDict(populate_by_name=True)

    version: int = SNAPSHOT_VERSION
    tops: list[PublicTop] = Field(default_factory=list)
    #: The free text of a meeting without agenda items. None when TOPs exist.
    markdown: str | None = None
    attendance: PublicAttendance = Field(default_factory=PublicAttendance)

    def search_text(self) -> str:
        """Return the plain text of the public parts for the search."""
        parts = (
            part
            for top in self.tops
            if not top.non_public
            for part in (top.title, top.markdown, *(d.question for d in top.decisions))
            if part
        )
        return "\n".join([*parts, *([self.markdown] if self.markdown else [])])


def apply_public_snapshot(protocol: Protocol, snapshot: PublicSnapshot, pdf: bytes | None) -> None:
    """Store the snapshot and the search text on the protocol row.

    `pdf` is the rendered public PDF. Without it (storage off) the size stays
    unchanged.
    """
    protocol.public_content = snapshot.model_dump(mode="json", by_alias=True)
    protocol.public_search_text = snapshot.search_text()
    if pdf is not None:
        protocol.public_pdf_size = len(pdf)


def semester_of(day: _date) -> str:
    """Return the semester key of a date.

    `ws-YYYY` is the winter semester YYYY/YY+1 (October to March), `ss-YYYY` the
    summer semester YYYY (April to September).
    """
    match day.month:
        case month if month >= 10:
            return f"ws-{day.year}"
        case month if month <= 3:
            return f"ws-{day.year - 1}"
        case _:
            return f"ss-{day.year}"


def semester_range(key: str) -> tuple[_date, _date]:
    """Return the first and the last day of a semester key (`ws-2026`, `ss-2026`)."""
    kind, _, year_text = key.partition("-")
    year = int(year_text)
    return (
        (_date(year, 10, 1), _date(year + 1, 3, 31))
        if kind == "ws"
        else (_date(year, 4, 1), _date(year, 9, 30))
    )


SEMESTER_PATTERN = r"^(ws|ss)-(19|20)\d{2}$"


class PublicGremiumRef(FrozenCamelModel, frozen=True):
    """A gremium as the public page names it."""

    id: UUID
    name: str
    slug: str


class PublicGremiumOut(PublicGremiumRef, frozen=True):
    """A gremium with the number of its public protocols."""

    protocol_count: int = Field(alias="protocolCount")


class PublicTopSummary(FrozenCamelModel, frozen=True):
    """One TOP in the public list: number, title and results."""

    number: int
    title: str | None = None
    non_public: bool = Field(alias="nonPublic")
    results: list[VoteResult] = Field(default_factory=list)


class PublicTopOut(PublicTopSummary, frozen=True):
    """One TOP on the public detail page, with its text and its decisions."""

    markdown: str | None = None
    decisions: list[PublicDecision] = Field(default_factory=list)


class PublicProtocolSummary(FrozenCamelModel, frozen=True):
    """One protocol in the public list."""

    id: UUID
    title: str
    date: _date
    semester: str
    finalized_at: Any = Field(default=None, alias="finalizedAt")
    gremium: PublicGremiumRef
    tops: list[PublicTopSummary]
    has_pdf: bool = Field(alias="hasPdf")
    pdf_size: int | None = Field(default=None, alias="pdfSize")


class PublicProtocolDetail(FrozenCamelModel, frozen=True):
    """One protocol on the public detail page."""

    id: UUID
    title: str
    date: _date
    semester: str
    finalized_at: Any = Field(default=None, alias="finalizedAt")
    gremium: PublicGremiumRef
    tops: list[PublicTopOut]
    markdown: str | None = None
    attendance: PublicAttendance
    has_pdf: bool = Field(alias="hasPdf")
    pdf_size: int | None = Field(default=None, alias="pdfSize")


class PublicProtocolPage(FrozenCamelModel, frozen=True):
    """One page of the public protocol list."""

    items: list[PublicProtocolSummary]
    total: int
    limit: int
    offset: int


class PublicSemesterOut(FrozenCamelModel, frozen=True):
    """A semester key with the number of its public protocols."""

    key: str
    count: int


def visible_clause() -> ColumnElement[bool]:
    """Return the fail-closed visibility rule of a public protocol.

    The caller joins `Gremium` and `Meeting`.
    """
    return and_(
        Protocol.status == "final",
        Protocol.public_withheld.is_(False),
        Protocol.public_content.is_not(None),
        Gremium.protocols_public.is_(True),
    )


def meeting_day_expr() -> ColumnElement[_date]:
    """Return the SQL day of a meeting: the planned date, else the creation day."""
    return func.coalesce(Meeting.date, cast(Meeting.created_at, Date))


def meeting_day(meeting: Meeting) -> _date:
    """Return the day of a meeting: the planned date, else the creation day."""
    return meeting.date or meeting.created_at.date()


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(slots=True, frozen=True)
class PublicFilter:
    """The filters of the public list. All of them are optional."""

    gremium_ids: tuple[UUID, ...] = ()
    semester: str | None = None
    year: int | None = None
    q: str | None = None


@dataclass(frozen=True, slots=True)
class PublicProtocolService:
    """The reads of the public protocols page. No write and no auth here.

    Attributes:
        session: The database session of the request.
        storage: The object storage of the public PDF, or `None` when storage is off.
    """

    session: AsyncSession
    storage: ObjectStorage | None = field(default=None, kw_only=True)

    @staticmethod
    def _base() -> Select[Protocol, Meeting, Gremium]:
        return (
            select(Protocol, Meeting, Gremium)
            .join(Meeting, Meeting.id == Protocol.meeting_id)
            .join(Gremium, Gremium.id == Protocol.gremium_id)
            .where(visible_clause())
        )

    @staticmethod
    def _filtered[*Ts](
        stmt: Select[*Ts], flt: PublicFilter, *, with_semester: bool = True
    ) -> Select[*Ts]:
        semester = semester_range(flt.semester) if with_semester and flt.semester else None
        by_year = with_semester and flt.year is not None
        pattern = f"%{_escape_like(flt.q.strip())}%" if flt.q else ""
        search = or_(
            Meeting.title.ilike(pattern, escape="\\"),
            Protocol.public_search_text.ilike(pattern, escape="\\"),
        )
        clauses = (
            *([Protocol.gremium_id.in_(flt.gremium_ids)] if flt.gremium_ids else []),
            *(
                [meeting_day_expr() >= semester[0], meeting_day_expr() <= semester[1]]
                if semester is not None
                else []
            ),
            *([func.extract("year", meeting_day_expr()) == flt.year] if by_year else []),
            *([search] if flt.q else []),
        )
        return stmt.where(*clauses)

    def _has_pdf(self, protocol: Protocol) -> bool:
        return protocol.public_pdf_storage_key is not None and self.storage is not None

    @staticmethod
    def _snapshot(protocol: Protocol) -> PublicSnapshot:
        return PublicSnapshot.model_validate(protocol.public_content or {})

    @staticmethod
    def _ref(gremium: Gremium) -> PublicGremiumRef:
        return PublicGremiumRef(id=gremium.id, name=gremium.name, slug=gremium.slug)

    def _summary(
        self, protocol: Protocol, meeting: Meeting, gremium: Gremium
    ) -> PublicProtocolSummary:
        snap = self._snapshot(protocol)
        return PublicProtocolSummary(
            id=protocol.id,
            title=meeting.title,
            date=meeting_day(meeting),
            semester=semester_of(meeting_day(meeting)),
            finalizedAt=protocol.sent_at,
            gremium=self._ref(gremium),
            tops=[
                PublicTopSummary(
                    number=t.number,
                    title=None if t.non_public else t.title,
                    nonPublic=t.non_public,
                    results=t.results,
                )
                for t in snap.tops
            ],
            hasPdf=self._has_pdf(protocol),
            pdfSize=protocol.public_pdf_size,
        )

    async def list_gremien(self) -> list[PublicGremiumOut]:
        """List the public gremien that have at least one visible protocol."""
        rows = (
            await self.session.execute(
                select(Gremium.id, Gremium.name, Gremium.slug, func.count(Protocol.id))
                .select_from(Protocol)
                .join(Meeting, Meeting.id == Protocol.meeting_id)
                .join(Gremium, Gremium.id == Protocol.gremium_id)
                .where(visible_clause())
                .group_by(Gremium.id, Gremium.name, Gremium.slug)
                .order_by(Gremium.name)
            )
        ).all()
        return [
            PublicGremiumOut(id=gid, name=name, slug=slug, protocolCount=int(count))
            for gid, name, slug, count in rows
        ]

    async def list_protocols(
        self, flt: PublicFilter, *, limit: int, offset: int
    ) -> PublicProtocolPage:
        """List the visible protocols, newest meeting first."""
        stmt = self._filtered(self._base(), flt)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(stmt.order_by(None).subquery())
            )
            or 0
        )
        rows = (
            await self.session.execute(
                stmt.order_by(meeting_day_expr().desc(), Meeting.created_at.desc(), Protocol.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return PublicProtocolPage(
            items=[self._summary(p, m, g) for p, m, g in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def list_semesters(self, flt: PublicFilter) -> list[PublicSemesterOut]:
        """Count the visible protocols per semester, newest semester first.

        The semester and year filters do not apply, so the chip can offer every
        semester of the other filters.
        """
        stmt = self._filtered(
            select(meeting_day_expr())
            .select_from(Protocol)
            .join(Meeting, Meeting.id == Protocol.meeting_id)
            .join(Gremium, Gremium.id == Protocol.gremium_id)
            .where(visible_clause()),
            flt,
            with_semester=False,
        )
        rows = (await self.session.execute(stmt)).all()
        counts = Counter(semester_of(day) for (day,) in rows)
        ordered = sorted(counts, key=lambda k: (semester_range(k)[0]), reverse=True)
        return [PublicSemesterOut(key=k, count=counts[k]) for k in ordered]

    async def _visible(self, protocol_id: UUID) -> tuple[Protocol, Meeting, Gremium]:
        """Load a publicly visible protocol with its meeting and gremium.

        A missing, draft, held-back protocol and one of a non-public gremium all give
        the same 404, so the page reveals nothing about a hidden protocol.
        """
        row = (await self.session.execute(self._base().where(Protocol.id == protocol_id))).first()
        if row is None:
            raise NotFoundError("protocol not found")
        protocol, meeting, gremium = row
        return protocol, meeting, gremium

    async def get_protocol(self, protocol_id: UUID) -> PublicProtocolDetail:
        """Return the public version of one visible protocol, else 404."""
        protocol, meeting, gremium = await self._visible(protocol_id)
        snap = self._snapshot(protocol)
        return PublicProtocolDetail(
            id=protocol.id,
            title=meeting.title,
            date=meeting_day(meeting),
            semester=semester_of(meeting_day(meeting)),
            finalizedAt=protocol.sent_at,
            gremium=self._ref(gremium),
            tops=[
                PublicTopOut(
                    number=t.number,
                    title=None if t.non_public else t.title,
                    nonPublic=t.non_public,
                    results=t.results,
                    markdown=None if t.non_public else t.markdown,
                    decisions=[] if t.non_public else t.decisions,
                )
                for t in snap.tops
            ],
            markdown=snap.markdown,
            attendance=snap.attendance,
            hasPdf=self._has_pdf(protocol),
            pdfSize=protocol.public_pdf_size,
        )

    async def public_image_ids(self, protocol_id: UUID) -> set[UUID]:
        """Return the ids of the images that the public version shows.

        The ids come from the public Markdown only: the free text of a meeting
        without TOPs and the text of each public TOP. An image of a non-public TOP
        stays out.

        Raises:
            NotFoundError: The protocol is not visible.
        """
        protocol = (await self._visible(protocol_id))[0]
        snap = self._snapshot(protocol)
        texts = [snap.markdown, *(t.markdown for t in snap.tops if not t.non_public)]
        return set(image_ids_in(*texts))

    async def get_pdf(self, protocol_id: UUID) -> tuple[bytes, str]:
        """Return the public PDF bytes and the download file name, else 404.

        The file name is the meeting title and day (`protocol_pdf_filename`). The
        meeting title is part of the public protocol already.

        Raises:
            NotFoundError: The protocol is not visible or has no public PDF.
            ServiceUnavailableError: The storage failed for a short time (503).
        """
        protocol, meeting, _ = await self._visible(protocol_id)
        if protocol.public_pdf_storage_key is None or self.storage is None:
            raise NotFoundError("protocol not found")
        try:
            data = await self.storage.get(protocol.public_pdf_storage_key)
        except StorageError as exc:
            raise ServiceUnavailableError("Protocol PDF temporarily unavailable.") from exc
        name = protocol_pdf_filename(meeting.title, meeting_day(meeting), public=True)
        return data, name
