"""Live-Vote/Meeting-Service (T-16, api.md §4, flows §5).

* :class:`MeetingService` — Sitzungs-CRUD + Steuerung (``activeApplicationId``/
  ``status``); jede Steuerung publiziert ``meeting_state`` auf ``meeting:{id}``.
* :class:`BrokerPublisher` — baut die WS-Events aus den Voting-Schemata und schreibt
  sie über den :class:`~app.modules.livevote.broker.MeetingBroker`. Implementiert das
  leaf-:class:`~app.modules.livevote.publisher.MeetingPublisher`-Protokoll, an dem das
  Voting-Modul beim Open/Close hängt (kein Import-Zyklus).

**Aggregat-only (requirements N1a):** Tally-/Closed-Events tragen nur ``counts``/
``quorumMet``/``leading``/``result`` — nie Wähler-Identitäten. Damit ist der
Beamer-Stream konstruktionsbedingt namensfrei.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from datetime import UTC, datetime
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time as _time
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import DateTime, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.gremium_roles import (
    _time_valid_clause,
    gremium_ids_with_permission,
    gremium_member_ids,
)
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import DelegationSubstitute, MeetingDelegation
from app.modules.livevote.broker import MeetingBroker
from app.modules.livevote.events import (
    MeetingStateEvent,
    VoteCancelledEvent,
    VoteClosedEvent,
    VoteOpenedEvent,
    VoteTallyEvent,
)
from app.modules.livevote.models import Meeting, MeetingAttendance
from app.modules.livevote.schemas import (
    MeetingCreate,
    MeetingOut,
    MeetingPage,
    MeetingPatch,
    MeetingVoteOut,
)
from app.modules.protocol.models import Protocol
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteClosed, VoteOut
from app.shared.config_schemas import VoteConfig
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)


def meeting_channel(meeting_id: UUID) -> str:
    """PubSub-Kanal einer Sitzung (api.md §4)."""
    return f"meeting:{meeting_id}"


# Sortier-/Boundary-Schlüssel der Timeline (#104): terminierter Zeitpunkt einer
# Sitzung. Fehlt die Uhrzeit, gilt Mitternacht; fehlt das Datum (offen geplant),
# rückt die Sitzung ans **Ende** der Zukunft (fernes Sentinel-Datum).
_MIDNIGHT = _time(0, 0)
_UNDATED_FALLBACK = _date(9999, 12, 31)


def _sort_ts_expr() -> Any:
    """SQL-Ausdruck ``date + start_time`` als ``timestamp`` (Keyset-Schlüssel)."""
    return cast(
        func.coalesce(Meeting.date, _UNDATED_FALLBACK)
        + func.coalesce(Meeting.start_time, _MIDNIGHT),
        DateTime,
    )


def _encode_cursor(ts: _datetime, meeting_id: UUID) -> str:
    """Opaker Keyset-Cursor aus (Sortier-Zeitstempel, ID)."""
    raw = f"{ts.isoformat()}|{meeting_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str | None) -> tuple[_datetime, UUID] | None:
    """Cursor → (Zeitstempel, ID); ``None`` bei leerem Cursor, 400 bei Murks."""
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = raw.split("|", 1)
        return _datetime.fromisoformat(ts_str), UUID(id_str)
    except (ValueError, TypeError) as exc:
        raise BadRequestError("invalid pagination cursor") from exc


class BrokerPublisher:
    """Übersetzt Domänen-Ergebnisse in WS-Events und fan-outet sie über den Broker."""

    def __init__(self, broker: MeetingBroker) -> None:
        self._broker = broker

    async def meeting_state(self, meeting: MeetingOut) -> None:
        event = MeetingStateEvent(
            activeApplicationId=meeting.active_application_id, status=meeting.status
        )
        await self._broker.publish(meeting_channel(meeting.id), event.dump())

    async def vote_opened(self, vote: VoteOut) -> None:
        if vote.meeting_id is None:
            return
        event = VoteOpenedEvent(
            voteId=vote.id,
            applicationId=vote.application_id,
            agendaItemId=vote.agenda_item_id,
            question=vote.question,
            options=vote.config.options,
            closesAt=vote.closes_at,
            secret=vote.secret,
        )
        await self._broker.publish(meeting_channel(vote.meeting_id), event.dump())

    async def vote_tally(self, vote: VoteOut) -> None:
        if vote.meeting_id is None:
            return
        # ``from_vote`` unterdrückt Choice-Counts solange der Vote geheim **und** offen
        # ist (kein Zwischenstand-Leak am Beamer/Voter); nur die Teilnahme reist mit.
        event = VoteTallyEvent.from_vote(vote)
        await self._broker.publish(meeting_channel(vote.meeting_id), event.dump())

    async def vote_closed(self, vote: VoteClosed) -> None:
        if vote.meeting_id is None:
            return
        event = VoteClosedEvent(
            voteId=vote.id,
            result=vote.result,
            counts=vote.tally.counts,
            failedReason=vote.tally.failed_reason,
        )
        await self._broker.publish(meeting_channel(vote.meeting_id), event.dump())

    async def vote_cancelled(self, vote: VoteOut) -> None:
        if vote.meeting_id is None:
            return
        event = VoteCancelledEvent(voteId=vote.id)
        await self._broker.publish(meeting_channel(vote.meeting_id), event.dump())


class MeetingService:
    """An eine ``AsyncSession`` (+ optionalen Publisher) gebundener Sitzungs-Service."""

    def __init__(
        self, session: AsyncSession, publisher: BrokerPublisher | None = None
    ) -> None:
        self.session = session
        self.publisher = publisher

    @staticmethod
    def _to_out(
        meeting: Meeting,
        protocol_id: UUID | None = None,
        *,
        can_manage: bool = False,
        can_write: bool = False,
        can_manage_votes: bool = False,
        can_vote: bool = False,
        is_protokollant: bool = False,
        protokollant_name: str | None = None,
        gremium_name: str | None = None,
        votes: list[MeetingVoteOut] | None = None,
    ) -> MeetingOut:
        return MeetingOut(
            id=meeting.id,
            gremiumId=meeting.gremium_id,
            gremiumName=gremium_name,
            title=meeting.title,
            date=meeting.date,
            startTime=meeting.start_time,
            closedAt=meeting.closed_at,
            status=meeting.status,  # type: ignore[arg-type]
            activeApplicationId=meeting.active_application_id,
            protocolId=protocol_id,
            createdAt=meeting.created_at,
            protokollantId=meeting.protokollant_id,
            protokollantName=protokollant_name,
            isProtokollant=is_protokollant,
            # ``canControl`` = darf die Sitzung **führen** (Protokoll/TOPs/Status) —
            # Protokollant oder Sitzungsverwalter. Master-Flag fürs FE-Editor-Gating.
            canControl=can_write,
            canManage=can_manage,
            canWrite=can_write,
            canManageVotes=can_manage_votes,
            canVote=can_vote,
            votes=votes or [],
        )

    async def _votes_for(self, meeting_ids: list[UUID]) -> dict[UUID, list[MeetingVoteOut]]:
        """An die Sitzung(en) gebundene Abstimmungen, je ``meeting_id`` gebündelt."""
        if not meeting_ids:
            return {}
        rows = (
            await self.session.execute(
                select(Vote)
                .where(Vote.meeting_id.in_(meeting_ids))
                .order_by(Vote.created_at)
            )
        ).scalars().all()
        # Stimmenstand (counts/leading) + Ablehnungs-Grund je Vote aus den Ballots
        # rekonstruieren (Reload-Pfad; der Live-WS-Pfad trägt sie schon mit). Gebündelt
        # geladen (kein N+1).
        tallies = await self._vote_tallies(rows)
        present_by_meeting = await self._present_by_meeting(meeting_ids)
        out: dict[UUID, list[MeetingVoteOut]] = {}
        for v in rows:
            if v.meeting_id is None:
                continue
            cfg = v.config if isinstance(v.config, dict) else {}
            opts = cfg.get("options") or []
            secret = bool(cfg.get("secret"))
            counts, leading, reason = tallies.get(v.id, (None, None, None))
            voted = sum((counts or {}).values())
            present = present_by_meeting.get(v.meeting_id, 0)
            # Reveal-Regel wie im VotingService: geschlossen ODER (nicht geheim UND alle
            # Anwesenden haben abgestimmt). Sonst counts/leading verdecken (#vote-progress).
            if v.status == "closed":
                revealed = True
            elif secret:
                revealed = False
            else:
                revealed = present > 0 and voted >= present
            out.setdefault(v.meeting_id, []).append(
                MeetingVoteOut(
                    id=v.id,
                    applicationId=v.application_id,
                    agendaItemId=v.agenda_item_id,
                    question=v.question,
                    options=list(opts),
                    status=v.status,  # type: ignore[arg-type]
                    result=v.result,
                    counts=counts if revealed else {},
                    leading=leading if revealed else None,
                    voted=voted,
                    present=present,
                    revealed=revealed,
                    failedReason=reason,
                )
            )
        return out

    async def _present_by_meeting(self, meeting_ids: list[UUID]) -> dict[UUID, int]:
        """``{meeting_id: Anzahl anwesender Mitglieder}`` (Reveal-Nenner, #vote-progress)."""
        if not meeting_ids:
            return {}
        rows = (
            await self.session.execute(
                select(
                    MeetingAttendance.meeting_id, func.count()
                )
                .where(
                    MeetingAttendance.meeting_id.in_(meeting_ids),
                    MeetingAttendance.status == "present",
                )
                .group_by(MeetingAttendance.meeting_id)
            )
        ).all()
        return {mid: n for mid, n in rows}

    async def _vote_tallies(
        self, votes: Sequence[Vote]
    ) -> dict[
        UUID,
        tuple[dict[str, int] | None, str | None, Literal["quorum", "majority"] | None],
    ]:
        """``{vote_id: (counts, leading, failedReason)}`` aus den Ballots (Reload).

        Lädt Stimmen gebündelt (offen: ``ballot``, geheim: ``secret_ballot``) und wendet
        die reine Tally-Logik an. ``failedReason`` nur für geschlossene, abgelehnte Votes."""
        from app.modules.voting import tally as tally_mod
        from app.modules.voting.models import Ballot, SecretBallot

        if not votes:
            return {}
        ids = [v.id for v in votes]
        open_rows = (
            await self.session.execute(
                select(Ballot.vote_id, Ballot.choice).where(Ballot.vote_id.in_(ids))
            )
        ).all()
        secret_rows = (
            await self.session.execute(
                select(SecretBallot.vote_id, SecretBallot.choice).where(
                    SecretBallot.vote_id.in_(ids)
                )
            )
        ).all()
        open_by_vote: dict[UUID, list[str | None]] = {}
        for vid, choice in open_rows:
            open_by_vote.setdefault(vid, []).append(choice)
        secret_by_vote: dict[UUID, list[str | None]] = {}
        for vid, choice in secret_rows:
            secret_by_vote.setdefault(vid, []).append(choice)

        out: dict[
            UUID,
            tuple[dict[str, int] | None, str | None, Literal["quorum", "majority"] | None],
        ] = {}
        for v in votes:
            config = VoteConfig.model_validate(v.config)
            choices = (
                secret_by_vote.get(v.id, [])
                if config.secret
                else open_by_vote.get(v.id, [])
            )
            counts = tally_mod.tally(config.options, choices)
            outcome = tally_mod.result(config, counts, v.eligible_count or 0)
            reason: Literal["quorum", "majority"] | None = None
            if v.status == "closed" and v.result is not None:
                reason = tally_mod.failed_reason(outcome.result, outcome.quorum_met)
            out[v.id] = (dict(counts), outcome.leading, reason)
        return out

    # -------------------------------------------------- Berechtigungen (#Sessions)
    async def _principal_id(self, sub: str) -> UUID | None:
        """``principal.id`` zur OIDC-``sub`` (für den Protokollant-Vergleich)."""
        return (
            await self.session.execute(
                select(PrincipalRow.id).where(PrincipalRow.sub == sub)
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _name_for(session: AsyncSession, principal_id: UUID | None) -> str | None:
        if principal_id is None:
            return None
        row = await session.get(PrincipalRow, principal_id)
        return (row.display_name or row.email) if row is not None else None

    async def _gremium_name_for(self, gremium_id: UUID | None) -> str | None:
        if gremium_id is None:
            return None
        row = await self.session.get(Gremium, gremium_id)
        return row.name if row is not None else None

    async def can_manage(self, gremium_id: UUID, principal: Principal) -> bool:
        """Sitzung verwalten: globale ``meeting.manage`` ODER Gremium-``session.manage``."""
        if principal.has("meeting.manage"):  # deckt Admin (#15) mit ab
            return True
        return gremium_id in await gremium_ids_with_permission(
            self.session, principal.sub, "session.manage"
        )

    async def _is_protokollant(self, meeting: Meeting, principal: Principal) -> bool:
        if meeting.protokollant_id is None:
            return False
        return meeting.protokollant_id == await self._principal_id(principal.sub)

    async def can_write(self, meeting: Meeting, principal: Principal) -> bool:
        """Protokoll/TOPs/Status führen: Verwalter, zugewiesener Protokollant ODER
        eine Rolle mit ``protocol.write``."""
        if await self.can_manage(meeting.gremium_id, principal):
            return True
        if await self._is_protokollant(meeting, principal):
            return True
        return meeting.gremium_id in await gremium_ids_with_permission(
            self.session, principal.sub, "protocol.write"
        )

    async def can_manage_votes(self, meeting: Meeting, principal: Principal) -> bool:
        """Abstimmungen öffnen/schließen: Verwalter, Protokollant ODER ``vote.manage``."""
        if await self.can_manage(meeting.gremium_id, principal):
            return True
        if await self._is_protokollant(meeting, principal):
            return True
        return meeting.gremium_id in await gremium_ids_with_permission(
            self.session, principal.sub, "vote.manage"
        )

    async def can_vote(self, meeting: Meeting, principal: Principal) -> bool:
        """Stimmberechtigt: Admin, eine Gremium-Rolle mit ``vote.cast`` ODER eine
        an den Principal gerichtete Stimm-Delegation dieser Sitzung
        (#delegation-rework — externer Stellvertreter)."""
        if "admin" in principal.roles:
            return True
        if meeting.gremium_id in await gremium_ids_with_permission(
            self.session, principal.sub, "vote.cast"
        ):
            return True
        return meeting.id in await self._delegated_meeting_ids(
            principal.sub, voting_only=True
        )

    async def is_member(self, gremium_id: UUID, principal: Principal) -> bool:
        """Aktuelles Mitglied des Gremiums (beliebige Rolle) — darf live mitlesen."""
        if "admin" in principal.roles:
            return True
        return gremium_id in await gremium_member_ids(self.session, principal.sub)

    async def is_participant(
        self, meeting_id: UUID, gremium_id: UUID, principal: Principal
    ) -> bool:
        """Mitglied **oder** Delegations-Empfänger dieser Sitzung — darf mitlesen.

        Externe Stellvertreter (#delegation-rework) sind keine Gremium-Mitglieder,
        brauchen für ihre Vertretung aber den Live-Kanal der Sitzung. ``meeting.view_all``
        (#meeting-view-all) öffnet den Live-Read-Kanal gremiumsübergreifend (rein lesend —
        das STIMMRECHT bleibt separat über ``can_vote``/``vote.cast`` gegatet).
        """
        if await self.is_member(gremium_id, principal):
            return True
        if principal.has("meeting.view_all"):
            return True
        return meeting_id in await self._delegated_meeting_ids(principal.sub)

    async def _delegated_meeting_ids(
        self, sub: str, *, voting_only: bool = False
    ) -> set[UUID]:
        """Sitzungen, für die ``sub`` eine (Stimm-)Delegation **empfängt**."""
        pid_subq = select(PrincipalRow.id).where(PrincipalRow.sub == sub).scalar_subquery()
        stmt = select(MeetingDelegation.meeting_id).where(
            MeetingDelegation.delegate_principal_id == pid_subq
        )
        if voting_only:
            stmt = stmt.where(MeetingDelegation.delegate_voting.is_(True))
        return set((await self.session.execute(stmt)).scalars().all())

    async def assert_can_read(self, meeting_id: UUID, principal: Principal) -> None:
        """Lesezugriff auf Sitzungs-Details (Detail/Roster/Agenda) absichern (#12
        sec-audit): erlaubt für Admin/``meeting.manage``, Mitglieder + Pool-Vertreter
        des Gremiums sowie Delegations-Empfänger dieser Sitzung — dieselbe Sichtbarkeit
        wie die Timeline. By-id-GETs waren zuvor für jeden eingeloggten Nutzer offen
        (Cross-Tenant-Lesen, u. a. Roster mit Namen/E-Mails)."""
        meeting = await self._get(meeting_id)  # 404, falls nicht vorhanden
        visible = await self._visible_gremium_ids(principal)
        if visible is None or meeting.gremium_id in visible:
            return
        if meeting_id in await self._delegated_meeting_ids(principal.sub):
            return
        raise ForbiddenError("not allowed to view this meeting")

    async def _visible_gremium_ids(self, principal: Principal) -> set[UUID] | None:
        """Gremien, deren Sitzungen der Principal sehen darf — ``None`` = **alle**.

        Admin/``meeting.manage``/``meeting.view_all`` sehen alles; sonst die Gremien, in
        denen der Principal Mitglied ist (beliebige Rolle) **oder** im Stellvertreter-Pool
        steht (#7): ein Pool-Vertreter sieht die Sitzungs-Timeline seiner Gremien (zur
        Vorbereitung), bekommt den Live-Kanal aber erst über eine konkrete Delegation
        (``is_participant``). ``meeting.view_all`` (#meeting-view-all) ist die globale,
        rein additive LESE-Permission: gremiumsübergreifende Sicht auf JEDE Sitzung
        (Timeline/Liste/Detail/Agenda/Protokoll/Vote-Ergebnisse) — verwaltet/schreibt/
        stimmt aber nicht (das bleibt an meeting.manage/session.manage/vote.* gegatet)."""
        if (
            "admin" in principal.roles
            or principal.has("meeting.manage")
            or principal.has("meeting.view_all")
        ):
            return None
        member = await gremium_member_ids(self.session, principal.sub)
        pool = await self._substitute_pool_gremium_ids(principal.sub)
        return member | pool

    async def _substitute_pool_gremium_ids(self, sub: str) -> set[UUID]:
        """Gremien, in deren Stellvertreter-Pool ``sub`` steht (#7)."""
        pid_subq = select(PrincipalRow.id).where(PrincipalRow.sub == sub).scalar_subquery()
        stmt = select(DelegationSubstitute.gremium_id).where(
            DelegationSubstitute.substitute_principal_id == pid_subq
        )
        return set((await self.session.execute(stmt)).scalars().all())

    async def _get(self, meeting_id: UUID) -> Meeting:
        meeting = (
            await self.session.execute(select(Meeting).where(Meeting.id == meeting_id))
        ).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def _protocol_id(self, meeting_id: UUID) -> UUID | None:
        """``protocol.id`` der Sitzung (UNIQUE ``meeting_id``) oder ``None``."""
        return (
            await self.session.execute(
                select(Protocol.id).where(Protocol.meeting_id == meeting_id)
            )
        ).scalar_one_or_none()

    async def _emit(
        self,
        meeting: Meeting,
        principal: Principal | None,
        *,
        protocol_id: UUID | None = None,
        votes: list[MeetingVoteOut] | None = None,
    ) -> MeetingOut:
        """``MeetingOut`` mit den vier Berechtigungs-Flags des Principals bauen."""
        name = await self._name_for(self.session, meeting.protokollant_id)
        gremium_name = await self._gremium_name_for(meeting.gremium_id)
        if principal is None:
            return self._to_out(
                meeting,
                protocol_id,
                protokollant_name=name,
                gremium_name=gremium_name,
                votes=votes,
            )
        return self._to_out(
            meeting,
            protocol_id,
            can_manage=await self.can_manage(meeting.gremium_id, principal),
            can_write=await self.can_write(meeting, principal),
            can_manage_votes=await self.can_manage_votes(meeting, principal),
            can_vote=await self.can_vote(meeting, principal),
            is_protokollant=await self._is_protokollant(meeting, principal),
            protokollant_name=name,
            gremium_name=gremium_name,
            votes=votes,
        )

    async def get(
        self, meeting_id: UUID, principal: Principal | None = None
    ) -> MeetingOut:
        """Sitzungs-State (404, falls unbekannt).

        ``principal`` optional: der WS-Pfad (Reconnect-State) braucht die Flags nicht
        und ruft ohne Principal auf.
        """
        meeting = await self._get(meeting_id)
        votes = (await self._votes_for([meeting.id])).get(meeting.id, [])
        return await self._emit(
            meeting,
            principal,
            protocol_id=await self._protocol_id(meeting.id),
            votes=votes,
        )

    async def list(
        self, principal: Principal, gremium_id: UUID | None = None
    ) -> list[MeetingOut]:
        """Sitzungen (neueste zuerst), optional auf ein Gremium gefiltert.

        Erlaubt das **Wiederfinden** angelegter Sitzungen (#104): ohne Liste war eine
        frisch erstellte Sitzung nach Reload nur über ihre UUID erreichbar.
        """
        stmt = select(Meeting).order_by(Meeting.created_at.desc())
        if gremium_id is not None:
            stmt = stmt.where(Meeting.gremium_id == gremium_id)
        visible = await self._visible_gremium_ids(principal)
        if visible is not None:
            # Delegations-Empfänger sehen »ihre« Sitzungen auch ohne Mitgliedschaft.
            delegated = await self._delegated_meeting_ids(principal.sub)
            stmt = stmt.where(
                or_(Meeting.gremium_id.in_(visible), Meeting.id.in_(delegated))
            )
        meetings = list((await self.session.execute(stmt)).scalars().all())
        return await self._decorate(meetings, principal)

    async def list_timeline(
        self,
        principal: Principal,
        *,
        direction: Literal["past", "upcoming"],
        cursor: str | None = None,
        limit: int = 20,
        gremium_id: UUID | None = None,
    ) -> MeetingPage:
        """Keyset-paginierte Sitzungs-Timeline um *jetzt* herum (#104).

        ``upcoming`` läuft chronologisch vorwärts ab dem aktuellen Zeitpunkt
        (frühestes zuerst, undatierte Sitzungen am Ende), ``past`` rückwärts in die
        Vergangenheit (jüngstes zuerst). Der ``cursor`` trägt den Sortier-Zeitstempel
        und die ID der zuletzt gelieferten Sitzung — stabil auch bei gleichem Termin.
        """
        sort_ts = _sort_ts_expr()
        # Naiver „Jetzt"-Zeitstempel — vergleichbar mit dem (datums-basierten) Sort-Key.
        now_ts = datetime.now(UTC).replace(tzinfo=None)
        cur = _decode_cursor(cursor)
        # Bucket status-bewusst (nicht rein zeitlich): ``live`` ist immer „anstehend"
        # (eine seit heute Vormittag laufende Sitzung darf nicht in die Vergangenheit
        # rutschen), ``closed`` immer „vergangen", ``planned`` entscheidet das Datum.
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
            # Delegations-Empfänger sehen »ihre« Sitzungen auch ohne Mitgliedschaft.
            delegated = await self._delegated_meeting_ids(principal.sub)
            stmt = stmt.where(
                or_(Meeting.gremium_id.in_(visible), Meeting.id.in_(delegated))
            )
        if direction == "upcoming":
            stmt = stmt.where(is_upcoming)
            if cur is not None:
                cts, cid = cur
                stmt = stmt.where(
                    or_(sort_ts > cts, and_(sort_ts == cts, Meeting.id > cid))
                )
            stmt = stmt.order_by(sort_ts.asc(), Meeting.id.asc())
        else:
            stmt = stmt.where(is_past)
            if cur is not None:
                cts, cid = cur
                stmt = stmt.where(
                    or_(sort_ts < cts, and_(sort_ts == cts, Meeting.id < cid))
                )
            stmt = stmt.order_by(sort_ts.desc(), Meeting.id.desc())
        # Ein Element über das Limit hinaus laden → verrät, ob eine Folgeseite existiert.
        rows = (await self.session.execute(stmt.limit(limit + 1))).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = await self._decorate([row[0] for row in rows], principal)
        next_cursor = (
            _encode_cursor(rows[-1][1], rows[-1][0].id) if has_more and rows else None
        )
        return MeetingPage(items=items, nextCursor=next_cursor)

    async def _decorate(
        self, meetings: list[Meeting], principal: Principal
    ) -> list[MeetingOut]:
        """Sitzungen mit Protokoll-ID, Votes und per-Principal-RBAC-Flags anreichern.

        Geteilt von :meth:`list` und :meth:`list_timeline`; lädt alles gebündelt
        (kein N+1) und filtert **keine** Sitzungen heraus — Sichtbarkeit ist
        modulweit, die Flags sind rein per-Principal.
        """
        if not meetings:
            return []
        # Protokoll-IDs gebündelt laden (kein N+1): meeting_id → protocol.id.
        proto_rows = (
            await self.session.execute(
                select(Protocol.meeting_id, Protocol.id).where(
                    Protocol.meeting_id.in_([m.id for m in meetings])
                )
            )
        ).all()
        proto_by_meeting = {meeting_id: pid for meeting_id, pid in proto_rows}
        # Gremium-Scopes des Principals einmal laden (kein N+1 je Sitzung). Admin/globaler
        # ``meeting.manage`` kurzschließt sämtliche Gremium-Queries.
        all_gids = {m.gremium_id for m in meetings}
        # Gremium-Namen gebündelt (Timeline zeigt Zugehörigkeit, #104).
        gremium_names: dict[UUID, str] = {
            gid: name
            for gid, name in (
                await self.session.execute(
                    select(Gremium.id, Gremium.name).where(Gremium.id.in_(all_gids))
                )
            ).all()
        }
        # Protokollant-Namen gebündelt (kein N+1) — sonst zeigt die Timeline/Karte
        # keinen Protokollanten (``protokollantName`` bliebe null → „nicht gespeichert"-
        # Eindruck), obwohl ``protokollant_id`` korrekt persistiert ist.
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
            vote_ids = await gremium_ids_with_permission(
                self.session, principal.sub, "vote.cast"
            )
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
                        prot_names.get(m.protokollant_id)
                        if m.protokollant_id is not None
                        else None
                    ),
                    votes=votes_by_meeting.get(m.id, []),
                )
            )
        return out

    async def create(self, payload: MeetingCreate, principal: Principal) -> MeetingOut:
        """Sitzung (``planned``) anlegen — nur Sitzungsverwalter (``session.manage``)."""
        if not await self.can_manage(payload.gremium_id, principal):
            raise ForbiddenError("not allowed to create meetings for this committee")
        protokollant_id = await self._resolve_protokollant(
            payload.gremium_id, payload.protokollant_id
        )
        meeting = Meeting(
            gremium_id=payload.gremium_id,
            title=payload.title,
            date=payload.date,
            start_time=payload.start_time,
            status="planned",
            created_by=principal.sub,
            protokollant_id=protokollant_id,
        )
        self.session.add(meeting)
        await self.session.flush()
        await self.session.commit()
        return await self._emit(meeting, principal)

    async def _resolve_protokollant(
        self, gremium_id: UUID, protokollant_id: UUID | None
    ) -> UUID | None:
        """Protokollant validieren: muss aktives Mitglied des Gremiums sein."""
        if protokollant_id is None:
            return None
        row = await self.session.get(PrincipalRow, protokollant_id)
        if row is None:
            raise NotFoundError(f"principal {protokollant_id} not found")
        if gremium_id not in await gremium_member_ids(self.session, row.sub):
            raise ForbiddenError(
                "protokollant must be an active member of the committee"
            )
        return protokollant_id

    async def patch(
        self, meeting_id: UUID, payload: MeetingPatch, principal: Principal
    ) -> MeetingOut:
        """Steuerung/Planung anwenden + ``meeting_state`` broadcasten.

        Feld-genaue RBAC: Status/aktiver Antrag verlangt ``canWrite`` (Protokollant
        oder Verwalter); Datum/Zeit/Protokollant-Zuweisung verlangt ``canManage``
        (Sitzungsverwalter)."""
        meeting = await self._get(meeting_id)
        wants_manage = (
            "date" in payload.model_fields_set
            or "start_time" in payload.model_fields_set
            or "protokollant_id" in payload.model_fields_set
        )
        wants_write = (
            payload.status is not None or payload.active_application_id is not None
        )
        if wants_manage and not await self.can_manage(meeting.gremium_id, principal):
            raise ForbiddenError("only a session manager may plan this meeting")
        if wants_write and not await self.can_write(meeting, principal):
            raise ForbiddenError("not allowed to control this meeting")

        # »closed« ist terminal: eine geschlossene Sitzung lässt sich nicht
        # wieder öffnen (kein closed→live/planned). Erneutes »closed« ist ein No-op.
        if (
            meeting.status == "closed"
            and payload.status is not None
            and payload.status != "closed"
        ):
            raise ConflictError("a closed session cannot be re-opened")

        # Geschlossen = eingefroren (#15): Datum/Zeit/Protokollant sind danach
        # nicht mehr änderbar — das Protokoll referenziert diese Planungsdaten.
        if meeting.status == "closed" and wants_manage:
            raise ConflictError(
                "the session is closed — its settings can no longer be changed"
            )

        # Start (planned→live): das Protokoll entsteht erst beim Start der Sitzung
        # — davor kann nicht protokolliert/abgestimmt werden. ``meeting.status`` wird
        # erst NACH der Protokollant-Prüfung gesetzt (atomar: kein »live« ohne
        # Protokollant, auch nicht in-memory bei einem abgewiesenen Patch).
        going_live = (
            payload.status == "live" and meeting.status != "live"
        )
        if payload.active_application_id is not None:
            meeting.active_application_id = payload.active_application_id
        if "date" in payload.model_fields_set:
            meeting.date = payload.date
        if "start_time" in payload.model_fields_set:
            meeting.start_time = payload.start_time
        if "protokollant_id" in payload.model_fields_set:
            # Nach Finalisierung ist die Schriftführung Teil des unterschriebenen
            # Dokuments — der Protokollant ist dann gesperrt (#15).
            if await self._protocol_final(meeting.id):
                raise ConflictError(
                    "protocol is finalized — the protokollant can no longer change"
                )
            meeting.protokollant_id = await self._resolve_protokollant(
                meeting.gremium_id, payload.protokollant_id
            )
        # Vor dem Start muss ein Protokollant feststehen — er ist die Schriftführung
        # des beim Start angelegten Protokolls (das Protokoll selbst legt der Router
        # nach diesem Commit an, planned→live).
        if going_live and meeting.protokollant_id is None:
            raise ConflictError(
                "assign a protokollant before starting the meeting"
            )
        if payload.status is not None:
            # Schließ-Zeitpunkt (#14): einmalig beim Wechsel auf ``closed`` —
            # liefert die »Ende«-Zeile der Protokoll-Titelseite.
            if payload.status == "closed" and meeting.status != "closed":
                meeting.closed_at = datetime.now(UTC)
            meeting.status = payload.status
        await self.session.flush()
        await self.session.commit()
        votes = (await self._votes_for([meeting.id])).get(meeting.id, [])
        out = await self._emit(meeting, principal, votes=votes)
        if self.publisher is not None:
            await self.publisher.meeting_state(out)
        return out

    async def broadcast_state(self, meeting_id: UUID, principal: Principal) -> None:
        """``meeting_state`` erneut senden, ohne State-Änderung — z. B. nach einem
        Protokoll-/TOP-Edit, damit Live-Follower den neuen Stand nachladen (#live-refresh)."""
        meeting = await self._get(meeting_id)
        votes = (await self._votes_for([meeting.id])).get(meeting.id, [])
        out = await self._emit(meeting, principal, votes=votes)
        if self.publisher is not None:
            await self.publisher.meeting_state(out)

    async def _protocol_final(self, meeting_id: UUID) -> bool:
        """Hat die Sitzung ein FINALISIERTES Protokoll? (#15/#16)"""
        # Lokaler Import: ``protocol`` hängt von ``livevote`` — Modul-Level wäre ein Zyklus.
        from app.modules.protocol.models import Protocol

        status = await self.session.scalar(
            select(Protocol.status).where(Protocol.meeting_id == meeting_id)
        )
        return status == "final"

    async def delete(self, meeting_id: UUID, principal: Principal) -> None:
        """Sitzung löschen — nur Sitzungsverwalter (``session.manage``)/Admin.

        Eine Sitzung mit FINALISIERTEM Protokoll (#16) verlangt zusätzlich die
        globale Permission ``meeting.delete_finalized`` — das Protokoll ist ein
        unterschriebenes, versandtes Dokument. Jedes Löschen wird auditiert.

        Kaskade: Protokoll/Tagesordnung/Anwesenheit entfallen mit; gebundene
        Abstimmungen werden via ``SET NULL`` entkoppelt (Ergebnis bleibt erhalten)."""
        meeting = await self._get(meeting_id)
        if not await self.can_manage(meeting.gremium_id, principal):
            raise ForbiddenError("not allowed to delete this meeting")
        finalized = await self._protocol_final(meeting_id)
        if finalized and not principal.has("meeting.delete_finalized"):
            raise ForbiddenError(
                "this meeting has a finalized protocol — deleting it requires "
                "the meeting.delete_finalized permission"
            )
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.MEETING_DELETE,
            target_type="meeting",
            target_id=str(meeting.id),
            data={
                "title": meeting.title,
                "gremiumId": str(meeting.gremium_id),
                "finalizedProtocol": finalized,
            },
        )
        await self.session.delete(meeting)
        await self.session.commit()

    async def open_vote(self, meeting_id: UUID) -> Vote | None:
        """Aktuell offener Vote dieser Sitzung (für ``subscribe``-Reconnect-State)."""
        return (
            await self.session.execute(
                select(Vote)
                .where(Vote.meeting_id == meeting_id, Vote.status == "open")
                .order_by(Vote.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def agenda_item_has_vote(self, item_id: UUID) -> bool:
        """Hat dieser TOP bereits eine Abstimmung (Antrags-TOP: max. eine)?"""
        return (
            await self.session.execute(
                select(Vote.id).where(Vote.agenda_item_id == item_id).limit(1)
            )
        ).first() is not None

    async def application_state_kind(self, application_id: UUID) -> str | None:
        """``state.kind`` des aktuellen Antrags-States (``None`` ohne Antrag/State)."""
        from app.modules.applications.models import Application
        from app.modules.flow.models import State

        return await self.session.scalar(
            select(State.kind)
            .join(Application, Application.current_state_id == State.id)
            .where(Application.id == application_id)
        )

    async def gremium_quorum_percent(self, gremium_id: UUID) -> int | None:
        """Default-Quorum (% der Stimmberechtigten) dieses Gremiums oder ``None``."""
        return (
            await self.session.execute(
                select(Gremium.quorum_percent).where(Gremium.id == gremium_id)
            )
        ).scalar_one_or_none()

    async def vote_eligible_count(self, gremium_id: UUID) -> int:
        """Roster-Größe fürs Quorum: aktive Mitglieder mit ``vote.cast``-Rolle."""
        now = datetime.now(UTC)
        rows = (
            await self.session.execute(
                select(GremiumMembership.principal_id, GremiumRole.permissions)
                .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
                .where(
                    GremiumMembership.gremium_id == gremium_id,
                    _time_valid_clause(now),
                )
            )
        ).all()
        return len({pid for pid, perms in rows if "vote.cast" in (perms or [])})
