"""Live-vote/meeting router (REST + WebSocket).

Auth is fail-closed. REST answers 401 or 403 through ``require_principal``. The
WebSocket closes with ``4401`` (no session) or ``4403`` (not eligible) after a
``not_eligible`` error frame.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, WebSocket

from app.deps import DbSession, require_principal
from app.modules.auth.principal import Principal
from app.modules.flow.dispatch import ActionDispatcher
from app.modules.flow.router import get_action_dispatcher
from app.modules.livevote.agenda_service import AgendaService
from app.modules.livevote.attendance_service import AttendanceService
from app.modules.livevote.broker import InMemoryBroker, MeetingBroker
from app.modules.livevote.connection import (
    WS_FORBIDDEN,
    WS_NOT_FOUND,
    WS_UNAUTHENTICATED,
    LiveVoteConnection,
    resolve_ws_principal,
)
from app.modules.livevote.events import ErrorEvent
from app.modules.livevote.guests import GuestService
from app.modules.livevote.locks import InMemoryLocker, Locker
from app.modules.livevote.schemas import (
    AgendaAddBody,
    AgendaBodyBody,
    AgendaItemOut,
    AgendaReorderBody,
    AssignableApplicationOut,
    AttendanceOut,
    AttendanceSelfBody,
    AttendanceSetBody,
    GuestNameBody,
    JoinLinkOut,
    MeetingCreate,
    MeetingDefaultsOut,
    MeetingGremiumOut,
    MeetingGuestOut,
    MeetingMemberOut,
    MeetingOut,
    MeetingPage,
    MeetingPatch,
    MeetingVoteOpenBody,
    ProtokollantHandoverBody,
)
from app.modules.livevote.service import BrokerPublisher, MeetingService
from app.modules.notifications.auto import AutoMailer, get_auto_mailer
from app.modules.voting.schemas import VoteCreateInternal
from app.modules.voting.service import VotingService
from app.settings import Settings, get_settings
from app.shared.config_schemas import VoteConfig
from app.shared.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ProblemDetail,
    ValidationProblem,
)

router = APIRouter(tags=["livevote"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}

# Single-process fallback for the case where the lifespan does not wire a broker
# or a locker onto the app state, for example in tests. Production uses Redis.
_FALLBACK_BROKER = InMemoryBroker()
_FALLBACK_LOCKER = InMemoryLocker()

# Cap the concurrent WebSocket connections per meeting and principal as a
# denial-of-service guard. One user cannot open unbounded sockets. Each socket
# holds a subscription plus a receive task. The counter is per process. A
# distributed limit would live at Redis or at the ingress.
_MAX_CONNECTIONS_PER_PRINCIPAL = 5
_connection_counts: dict[tuple[UUID, str], int] = {}


def _try_acquire_slot(meeting_id: UUID, sub: str) -> bool:
    """Take a connection slot (``False`` when the limit is reached)."""
    key = (meeting_id, sub)
    current = _connection_counts.get(key, 0)
    if current >= _MAX_CONNECTIONS_PER_PRINCIPAL:
        return False
    _connection_counts[key] = current + 1
    return True


def _release_slot(meeting_id: UUID, sub: str) -> None:
    """Release a connection slot.

    The call is idempotent. It drops the entry when the count reaches zero.
    """
    key = (meeting_id, sub)
    current = _connection_counts.get(key, 0)
    if current <= 1:
        _connection_counts.pop(key, None)
    else:
        _connection_counts[key] = current - 1


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


# Tests replace these providers through ``dependency_overrides``.
def get_broker_rest(request: Request) -> MeetingBroker:
    return getattr(request.app.state, "broker", None) or _FALLBACK_BROKER


def get_broker_ws(websocket: WebSocket) -> MeetingBroker:
    return getattr(websocket.app.state, "broker", None) or _FALLBACK_BROKER


def get_locker_ws(websocket: WebSocket) -> Locker:
    return getattr(websocket.app.state, "locker", None) or _FALLBACK_LOCKER


def get_meeting_service(
    session: DbSession,
    broker: Annotated[MeetingBroker, Depends(get_broker_rest)],
) -> MeetingService:
    return MeetingService(session, BrokerPublisher(broker))


def get_meeting_service_ws(
    session: DbSession,
    broker: Annotated[MeetingBroker, Depends(get_broker_ws)],
) -> MeetingService:
    """Meeting service for the WebSocket path (broker from the WebSocket app state)."""
    return MeetingService(session, BrokerPublisher(broker))


def get_attendance_service(session: DbSession) -> AttendanceService:
    return AttendanceService(session)


def get_agenda_service(session: DbSession) -> AgendaService:
    return AgendaService(session)


def get_voting_service(
    session: DbSession,
    dispatcher: Annotated[ActionDispatcher, Depends(get_action_dispatcher)],
) -> VotingService:
    """Voting service with the app flow dispatcher (override in `app.main`)."""
    return VotingService(session, dispatcher)


def get_voting_service_ws(
    session: DbSession,
    dispatcher: Annotated[ActionDispatcher, Depends(get_action_dispatcher)],
) -> VotingService:
    """Voting service for the WebSocket cast path, with the app flow dispatcher."""
    return VotingService(session, dispatcher)


async def get_ws_principal(
    websocket: WebSocket,
    session: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal | None:
    """Handshake principal from the session cookie (``None`` without a valid session)."""
    return await resolve_ws_principal(websocket, session, settings)


def get_guest_service(
    session: DbSession,
    broker: Annotated[MeetingBroker, Depends(get_broker_rest)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GuestService:
    """Guest service of the public meeting (#17) with the broker and the base URL."""
    return GuestService(session, BrokerPublisher(broker), base_url=settings.public_base_url)


ServiceDep = Annotated[MeetingService, Depends(get_meeting_service)]
GuestServiceDep = Annotated[GuestService, Depends(get_guest_service)]
AttendanceDep = Annotated[AttendanceService, Depends(get_attendance_service)]
AgendaDep = Annotated[AgendaService, Depends(get_agenda_service)]
VotingDep = Annotated[VotingService, Depends(get_voting_service)]
BrokerRestDep = Annotated[MeetingBroker, Depends(get_broker_rest)]
ReaderDep = Annotated[Principal, Depends(require_principal())]
SettingsDep = Annotated[Settings, Depends(get_settings)]
AutoMailerDep = Annotated[AutoMailer, Depends(get_auto_mailer)]
BrokerWsDep = Annotated[MeetingBroker, Depends(get_broker_ws)]
LockerWsDep = Annotated[Locker, Depends(get_locker_ws)]
MeetingServiceWsDep = Annotated[MeetingService, Depends(get_meeting_service_ws)]
VotingServiceWsDep = Annotated[VotingService, Depends(get_voting_service_ws)]
WsPrincipalDep = Annotated[Principal | None, Depends(get_ws_principal)]


# REST
@router.post("/meetings", response_model=MeetingOut, responses=_errors(400, 401, 403, 422))
async def create_meeting(
    payload: MeetingCreate,
    service: ServiceDep,
    principal: ReaderDep,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    mailer: AutoMailerDep,
) -> MeetingOut:
    """Create a meeting in status ``planned``.

    The caller must hold the gremium permission ``session.manage`` in the Gremium of
    the meeting, or the admin role. The service raises 403 when the principal may not
    manage the Gremium. The members of the Gremium receive a meeting mail.
    """
    meeting = await service.create(payload, principal)
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(mailer.meeting_created, settings, meeting.id, pool)
    return meeting


@router.get(
    "/gremien/{gremium_id}/meeting-members",
    response_model=list[MeetingMemberOut],
    responses=_errors(401, 403),
)
async def list_meeting_members(
    gremium_id: UUID,
    attendance: AttendanceDep,
    service: ServiceDep,
    principal: ReaderDep,
) -> list[MeetingMemberOut]:
    """List the current Gremium members as protokollant candidates.

    The caller must be able to manage the Gremium (``session.manage`` or admin).
    The list fills the protokollant picker in the create dialog before a roster
    exists. ``canKeepProtocol`` marks the members with ``protocol.write`` (O20): only
    they can be the protokollant.
    """
    if not await service.can_manage(gremium_id, principal):
        raise ForbiddenError("not allowed to manage meetings for this committee")
    return await attendance.members(gremium_id)


@router.get(
    "/gremien/{gremium_id}/meeting-defaults",
    response_model=MeetingDefaultsOut,
    responses=_errors(401, 403),
)
async def get_meeting_defaults(
    gremium_id: UUID, service: ServiceDep, principal: ReaderDep
) -> MeetingDefaultsOut:
    """What a new meeting of the gremium allows (#17).

    Public participation needs a gremium without a quorum; the create dialog reads it
    before the meeting exists. The caller must manage the gremium (``session.manage``
    or admin).
    """
    if not await service.can_manage(gremium_id, principal):
        raise ForbiddenError("not allowed to manage meetings for this committee")
    quorum = await service.gremium_quorum_percent(gremium_id)
    return MeetingDefaultsOut(publicJoinAllowed=quorum is None, quorumPercent=quorum)


@router.get("/meetings", response_model=list[MeetingOut], responses=_errors(401, 403, 422))
async def list_meetings(
    service: ServiceDep,
    principal: ReaderDep,
    gremium_id: Annotated[UUID | None, Query(alias="gremiumId")] = None,
    date_from: Annotated[date | None, Query(alias="dateFrom")] = None,
    date_to: Annotated[date | None, Query(alias="dateTo")] = None,
) -> list[MeetingOut]:
    """List the meetings, newest first, with an optional Gremium filter.

    ``dateFrom`` and ``dateTo`` (``YYYY-MM-DD``, both included) limit the list to
    the meetings with a planned date in this range. The calendar view of the
    overview reads one month this way. A range with ``dateFrom`` after ``dateTo``
    gives 422.
    """
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValidationProblem(
            "dateFrom is after dateTo.",
            code="invalid_date_range",
            errors=[{"field": "dateFrom", "msg": "must not be after dateTo"}],
        )
    return await service.list(principal, gremium_id, date_from=date_from, date_to=date_to)


@router.get("/meetings/timeline", response_model=MeetingPage, responses=_errors(400, 401, 403))
async def list_meetings_timeline(
    service: ServiceDep,
    principal: ReaderDep,
    direction: Annotated[Literal["past", "upcoming"], Query()] = "upcoming",
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    gremium_id: Annotated[UUID | None, Query(alias="gremiumId")] = None,
    q: Annotated[str | None, Query()] = None,
) -> MeetingPage:
    """Keyset-paginated meeting timeline around *now*.

    ``upcoming`` returns the upcoming meetings forward. ``past`` returns the past
    meetings backward. ``cursor`` comes from the ``nextCursor`` of the previous
    page. ``None`` starts at *now*. With ``q`` the timeline collapses into one
    relevance-sorted list (fuzzy search). ``direction`` then has no effect,
    ``cursor`` carries an offset, and ``nextCursor === null`` ends the results.
    """
    return await service.list_timeline(
        principal,
        direction=direction,
        cursor=cursor,
        limit=limit,
        gremium_id=gremium_id,
        q=q,
    )


@router.get(
    "/meetings/gremien",
    response_model=list[MeetingGremiumOut],
    responses=_errors(401, 403),
)
async def list_meeting_filter_gremien(
    service: ServiceDep,
    principal: ReaderDep,
) -> list[MeetingGremiumOut]:
    """Gremien for the meeting-overview filter.

    The result holds the Gremien where the principal has at least one readable
    meeting. It is not the list of Gremien the principal belongs to. This route
    must precede ``/meetings/{meeting_id}``, or the UUID path captures ``gremien``.
    """
    return await service.list_filter_gremien(principal)


@router.get("/meetings/{meeting_id}", response_model=MeetingOut, responses=_errors(401, 403, 404))
async def get_meeting(meeting_id: UUID, service: ServiceDep, principal: ReaderDep) -> MeetingOut:
    """Meeting state."""
    await service.assert_can_read(meeting_id, principal)
    return await service.get(meeting_id, principal)


@router.delete(
    "/meetings/{meeting_id}", status_code=204, responses=_errors(401, 403, 404, 409)
)
async def delete_meeting(meeting_id: UUID, service: ServiceDep, principal: ReaderDep) -> None:
    """Delete a meeting.

    Only a meeting manager (``session.manage``) or an admin may delete a meeting.
    A meeting with an open vote gives 409 ``open_vote``. The delete cancels the
    draft votes of the meeting.
    """
    await service.delete(meeting_id, principal)


@router.patch(
    "/meetings/{meeting_id}",
    response_model=MeetingOut,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def patch_meeting(
    meeting_id: UUID, payload: MeetingPatch, service: ServiceDep, principal: ReaderDep
) -> MeetingOut:
    """Control or plan a meeting and broadcast ``meeting_state``.

    The service applies RBAC per field. Status and active application need
    ``canWrite`` (protokollant or manager). Date, time and protokollant need
    ``canManage`` (meeting manager). A new protokollant needs ``protocol.write`` in
    the Gremium (O20: 422). While the meeting is live, a new protokollant is a
    handover ``now`` (Z3). On the start transition (planned to live) the
    router creates the protocol, and that step is idempotent. The protocol is
    created only here, never by hand. The service has already checked that a
    protokollant is set, else it answers 409.

    The status runs only planned, live, closed (409 ``invalid_status_transition``
    otherwise). The close answers 409 ``open_vote`` while a vote of the meeting is
    open, and it cancels the draft votes of the meeting.
    """
    updated = await service.patch(meeting_id, payload, principal)
    if payload.status == "live" and updated.status == "live":
        # Local import: ``protocol`` depends on ``livevote``. A module-level import
        # would cycle. The protocol uses the session of the service, so the work
        # stays in one transaction and one commit.
        from app.modules.protocol.service import ProtocolService

        await ProtocolService(service.session).get_or_create(meeting_id, author=principal.sub)
        # Re-read so the response carries the new ``protocolId``.
        return await service.get(meeting_id, principal)
    return updated


@router.post(
    "/meetings/{meeting_id}/protokollant-handover",
    response_model=MeetingOut,
    responses=_errors(401, 403, 404, 409, 422),
)
async def hand_over_protokollant(
    meeting_id: UUID,
    payload: ProtokollantHandoverBody,
    service: ServiceDep,
    principal: ReaderDep,
) -> MeetingOut:
    """Hand the minutes of a live meeting over to another member (Z3, O1).

    ``mode=now`` hands over at once. ``mode=next_item`` plans the handover for the
    next forward move of the current agenda item and replaces an older plan. The
    session lead (``session.manage``) or the current protokollant may call it. The
    new protokollant is an active member (403) with ``protocol.write`` (O20: 422
    ``protokollant_needs_protocol_write``). 409 ``meeting_not_live`` outside a live
    meeting, 409 ``already_protokollant`` for the current protokollant, 409
    ``no_next_item`` for ``next_item`` on the last agenda item. Writes
    ``protokollant_handover`` and sends ``meeting_state``.
    """
    return await service.hand_over(meeting_id, payload.principal_id, payload.mode, principal)


@router.delete(
    "/meetings/{meeting_id}/protokollant-handover",
    response_model=MeetingOut,
    responses=_errors(401, 403, 404, 409),
)
async def cancel_protokollant_handover(
    meeting_id: UUID, service: ServiceDep, principal: ReaderDep
) -> MeetingOut:
    """Discard the planned handover of a live meeting (Z3).

    The same callers as for the handover. 404 ``no_planned_handover`` without a
    planned handover. Writes ``protokollant_handover`` (mode ``cancel``) and sends
    ``meeting_state``.
    """
    return await service.cancel_handover(meeting_id, principal)


@router.get(
    "/meetings/{meeting_id}/attendance",
    response_model=list[AttendanceOut],
    responses=_errors(401, 403, 404),
)
async def list_attendance(
    meeting_id: UUID,
    attendance: AttendanceDep,
    service: ServiceDep,
    principal: ReaderDep,
) -> list[AttendanceOut]:
    """Attendance roster of the meeting and the status of each entry.

    The roster holds the members whose membership overlaps the meeting window,
    plus each principal with an attendance record for the meeting. The reason of
    an excuse (`note`) goes only to the member and to the meeting lead
    (`canWrite`).
    """
    # Only a principal that may read the meeting sees the names and the emails.
    await service.assert_can_read(meeting_id, principal)
    can_write = await service.can_write_meeting(meeting_id, principal)
    return await attendance.roster(meeting_id, principal.sub, can_write=can_write)


@router.put(
    "/meetings/{meeting_id}/attendance/me",
    response_model=list[AttendanceOut],
    responses=_errors(401, 403, 404, 409, 422),
)
async def set_own_attendance(
    meeting_id: UUID,
    payload: AttendanceSelfBody,
    attendance: AttendanceDep,
    service: ServiceDep,
    principal: ReaderDep,
) -> list[AttendanceOut]:
    """Report the attendance of the caller (Gremium members only, Z2).

    The status is `present` or `excused`, else 422. A `note` (the reason) is
    allowed only with `excused`. The meeting must be `planned` or `live`, else
    409. When the meeting lead set the record, the member cannot change it: 409
    `attendance_set_by_lead` (O15). `present` gives 409 `delegation_active` while
    the caller has a delegation for this meeting (O23).
    """
    can_write = await service.can_write_meeting(meeting_id, principal)
    return await attendance.set_self(
        meeting_id,
        payload.status,
        principal.sub,
        note=payload.clean_note(),
        replace_note=payload.note_given,
        can_write=can_write,
    )


async def _require_lead(service: MeetingService, meeting_id: UUID, principal: Principal) -> None:
    """Allow only the meeting lead (`canWrite`): manager, protokollant or `protocol.write`."""
    if not await service.can_write_meeting(meeting_id, principal):
        raise ForbiddenError("not allowed to set members' attendance")


@router.put(
    "/meetings/{meeting_id}/attendance/{principal_id}",
    response_model=list[AttendanceOut],
    responses=_errors(401, 403, 404, 409, 422),
)
async def set_member_attendance(
    meeting_id: UUID,
    principal_id: UUID,
    payload: AttendanceSetBody,
    attendance: AttendanceDep,
    service: ServiceDep,
    principal: ReaderDep,
) -> list[AttendanceOut]:
    """Set the attendance of a member as the meeting lead (`canWrite`).

    The lead's record wins over the own report of the member (O15). `present`
    gives 409 `delegation_active` while the member has a delegation for this
    meeting (O23). The change writes `attendance_set` without the note.
    """
    await _require_lead(service, meeting_id, principal)
    return await attendance.set_for(
        meeting_id,
        principal_id,
        payload.status,
        principal.sub,
        note=payload.clean_note(),
        replace_note=payload.note_given,
    )


@router.delete(
    "/meetings/{meeting_id}/attendance/{principal_id}",
    response_model=list[AttendanceOut],
    responses=_errors(401, 403, 404, 409),
)
async def reset_member_attendance(
    meeting_id: UUID,
    principal_id: UUID,
    attendance: AttendanceDep,
    service: ServiceDep,
    principal: ReaderDep,
) -> list[AttendanceOut]:
    """Reset the attendance of a member to "open" as the meeting lead (`canWrite`).

    The record goes away, so the member can report again. The reset writes
    `attendance_reset`. A closed meeting gives 409.
    """
    await _require_lead(service, meeting_id, principal)
    return await attendance.reset(meeting_id, principal_id, principal.sub)


@router.get(
    "/meetings/{meeting_id}/agenda",
    response_model=list[AgendaItemOut],
    responses=_errors(401, 403, 404),
)
async def list_agenda(
    meeting_id: UUID, agenda: AgendaDep, service: ServiceDep, principal: ReaderDep
) -> list[AgendaItemOut]:
    """Meeting agenda: the assigned applications in order."""
    await service.assert_can_read(meeting_id, principal)
    return await agenda.list(meeting_id)


@router.post(
    "/meetings/{meeting_id}/votes",
    response_model=MeetingOut,
    responses=_errors(401, 403, 404, 409, 422),
)
async def open_meeting_vote(
    meeting_id: UUID,
    payload: MeetingVoteOpenBody,
    service: ServiceDep,
    voting: VotingDep,
    agenda: AgendaDep,
    broker: BrokerRestDep,
    principal: ReaderDep,
) -> MeetingOut:
    """Open a live vote on an agenda item of this meeting.

    The route creates the vote and opens it in one step. The caller must be the
    manager, the protokollant, or hold the gremium permission ``vote.manage``. An
    application agenda item allows exactly one vote, because that vote fires the pass
    or fail branch on close. A free-text agenda item allows several generic questions.
    ``eligibleGroup`` is the Gremium of the meeting. The server derives the quorum
    denominator from the roster (members with ``vote.cast``) and never from client
    input. The route broadcasts ``vote_opened``.
    """
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_manage_votes:
        raise ForbiddenError("not allowed to open a vote in this meeting")
    # A vote needs a started meeting. Before ``live`` there is no protocol to
    # record the result in.
    if meeting.status != "live":
        raise ConflictError("the meeting has not started — start it before opening a vote")
    item = await agenda.item(meeting_id, payload.agenda_item_id)
    # #17: the admitted guests vote too when the meeting lets them and the item is
    # public. Such a vote has no quorum: only the majority of the cast ballots counts.
    guests_allowed = meeting.public_join and meeting.guests_mode == "vote"
    if payload.guests_vote and not guests_allowed:
        raise ValidationProblem(
            "Guests do not vote in this meeting.",
            code="guests_vote_unavailable",
            errors=[{"field": "guestsVote", "msg": "the meeting does not let guests vote"}],
        )
    if payload.guests_vote and item.non_public:
        raise ValidationProblem(
            "Guests never vote on a non-public agenda item.",
            code="guests_vote_non_public",
            errors=[{"field": "guestsVote", "msg": "non-public agenda item"}],
        )
    guests_vote = (
        payload.guests_vote
        if payload.guests_vote is not None
        else guests_allowed and not item.non_public
    )
    if item.application_id is not None:
        if await service.agenda_item_has_vote(item.id):
            raise ConflictError("this application TOP already has a decision vote")
        # Fail fast: an application vote fires the pass or fail branch of the
        # current state on close. If the application is not in a vote state, nobody
        # can close the vote, and the cast ballots are lost.
        kind = await service.application_state_kind(item.application_id)
        if kind != "vote":
            raise ConflictError(
                "The application is not in a vote state — move it into its "
                "decision state before opening the vote.",
                code="conflict",
            )
        # Only the Gremium that decides the current vote state votes. A stale agenda
        # item (the application left the state and came back for another Gremium)
        # must not let this meeting decide.
        if await service.application_vote_gremium(item.application_id) != meeting.gremium_id:
            raise ConflictError(
                "The Gremium of this meeting does not decide the current vote of the "
                "application.",
                code="vote_gremium_mismatch",
            )
    config_data: dict[str, object] = {
        "options": payload.options,
        "majorityRule": payload.majority_rule,
        "secret": payload.secret,
        # A meeting vote has no casting vote (O18): a tie is ``rejected``. The body
        # has no ``tieBreak``, so the client cannot change this.
        "tieBreak": "rejected",
        "guestsVote": guests_vote,
    }
    # Gremium quorum default: without an explicit percent, the vote inherits the
    # percent quorum configured on the Gremium. A vote with guests has no quorum.
    quorum_percent = (
        None
        if guests_vote
        else payload.quorum_percent
        if payload.quorum_percent is not None
        else await service.gremium_quorum_percent(meeting.gremium_id)
    )
    if quorum_percent is not None:
        config_data["quorum"] = {"type": "percent", "value": quorum_percent}
    config = VoteConfig.model_validate(config_data)
    # The server always derives the quorum denominator from the real roster and
    # never from the client. A holder of ``canManageVotes`` cannot manipulate it.
    # A vote with guests counts the present members and the admitted guests; the
    # close fixes the number again (a display value, there is no quorum).
    if guests_vote:
        eligible = await service.present_member_count(meeting_id) + meeting.admitted_guests
    else:
        eligible = await service.vote_eligible_count(meeting.gremium_id)
    create = VoteCreateInternal(
        config=config,
        eligibleGroup=meeting.gremium_id,
        question=payload.question,
        eligibleCount=eligible,
    )
    vote = await voting.create_internal(
        item.application_id, create, meeting_id=meeting_id, agenda_item_id=item.id
    )
    opened = await voting.open(vote.id, now=datetime.now(UTC), actor=principal.sub)
    await BrokerPublisher(broker).vote_opened(opened)
    return await service.get(meeting_id, principal)


@router.delete(
    "/meetings/{meeting_id}/votes/{vote_id}",
    response_model=MeetingOut,
    responses=_errors(401, 403, 404, 409),
)
async def delete_meeting_vote(
    meeting_id: UUID,
    vote_id: UUID,
    service: ServiceDep,
    voting: VotingDep,
    principal: ReaderDep,
) -> MeetingOut:
    """Delete a vote and its ballots.

    The caller must be the manager, the protokollant, or hold the gremium permission
    ``vote.manage``. Only a ``planned`` or ``live`` meeting deletes a vote (O24): after
    the close the vote is part of the record, and the route answers 409
    ``meeting_closed``. Only a ``draft`` or ``cancelled`` vote can go: an open or
    closed vote gives 409 ``vote_not_deletable``. Every delete writes ``vote_delete``.
    """
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_manage_votes:
        raise ForbiddenError("not allowed to delete a vote in this meeting")
    if meeting.status == "closed":
        raise ConflictError(
            "the meeting is closed — its votes can no longer be deleted",
            code="meeting_closed",
        )
    await voting.delete(vote_id, meeting_id=meeting_id, actor=principal.sub)
    return await service.get(meeting_id, principal)


@router.get(
    "/meetings/{meeting_id}/agenda/assignable",
    response_model=list[AssignableApplicationOut],
    responses=_errors(401, 403, 404),
)
async def list_assignable(
    meeting_id: UUID, agenda: AgendaDep, service: ServiceDep, principal: ReaderDep
) -> list[AssignableApplicationOut]:
    """Applications of this Gremium in a vote state that are not yet on the agenda."""
    await service.assert_can_read(meeting_id, principal)
    return await agenda.assignable(meeting_id)


@router.post(
    "/meetings/{meeting_id}/agenda",
    response_model=list[AgendaItemOut],
    responses=_errors(401, 403, 404, 409, 422),
)
async def add_agenda_item(
    meeting_id: UUID,
    payload: AgendaAddBody,
    agenda: AgendaDep,
    service: ServiceDep,
    principal: ReaderDep,
) -> list[AgendaItemOut]:
    """Add an agenda item, either an application or a free-text item.

    Only the meeting lead or an admin may edit the agenda. A closed meeting answers
    409 ``meeting_closed``.
    """
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_write:
        raise ForbiddenError("not allowed to edit the agenda")
    return await agenda.add(
        meeting_id,
        payload.application_id,
        payload.title,
        non_public=payload.non_public,
        actor=principal.sub,
    )


@router.delete(
    "/meetings/{meeting_id}/agenda/{item_id}",
    response_model=list[AgendaItemOut],
    responses=_errors(401, 403, 404, 409),
)
async def remove_agenda_item(
    meeting_id: UUID,
    item_id: UUID,
    agenda: AgendaDep,
    service: ServiceDep,
    principal: ReaderDep,
) -> list[AgendaItemOut]:
    """Remove an agenda item.

    Only the meeting lead or an admin may edit the agenda. A closed meeting answers
    409 ``meeting_closed``. An item with an open or closed vote answers 409
    ``agenda_item_has_vote``. The draft and cancelled votes of the item go with it.
    To delete them the caller also needs ``canManageVotes``, as on
    ``DELETE /meetings/{id}/votes/{voteId}``, else 403.
    """
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_write:
        raise ForbiddenError("not allowed to edit the agenda")
    return await agenda.remove(
        meeting_id,
        item_id,
        actor=principal.sub,
        may_delete_votes=meeting.can_manage_votes,
    )


@router.put(
    "/meetings/{meeting_id}/agenda/order",
    response_model=list[AgendaItemOut],
    responses=_errors(401, 403, 404, 409, 422),
)
async def reorder_agenda(
    meeting_id: UUID,
    payload: AgendaReorderBody,
    agenda: AgendaDep,
    service: ServiceDep,
    principal: ReaderDep,
) -> list[AgendaItemOut]:
    """Reorder the agenda items.

    Only the meeting lead or an admin may edit the agenda. A closed meeting answers
    409 ``meeting_closed``.
    """
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_write:
        raise ForbiddenError("not allowed to edit the agenda")
    return await agenda.reorder(meeting_id, payload.item_ids, actor=principal.sub)


@router.patch(
    "/meetings/{meeting_id}/agenda/{item_id}",
    response_model=list[AgendaItemOut],
    responses=_errors(401, 403, 404, 409, 422),
)
async def set_agenda_body(
    meeting_id: UUID,
    item_id: UUID,
    payload: AgendaBodyBody,
    agenda: AgendaDep,
    service: ServiceDep,
    principal: ReaderDep,
) -> list[AgendaItemOut]:
    """Set the markdown body or the title of an agenda item.

    The per-item editor calls this route. Only the meeting lead or an admin may
    edit the agenda (``canWrite``). The body needs a live meeting, or a closed
    meeting whose protocol is still a draft (O22). A rename needs a planned or live
    meeting (O25). The service answers 409 otherwise.
    """
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_write:
        raise ForbiddenError("not allowed to edit the agenda")
    items = await agenda.set_body(
        meeting_id,
        item_id,
        body=payload.body,
        title=payload.title,
        non_public=payload.non_public,
        actor=principal.sub,
    )
    # Tell the live followers about the changed agenda-item text.
    await service.broadcast_state(meeting_id, principal)
    return items


# Public meeting with a QR code (#17): the routes of the meeting lead.
async def _require_manage(service: MeetingService, meeting_id: UUID, principal: Principal) -> None:
    """Allow only the meeting lead with ``session.manage`` in the gremium (or admin)."""
    gremium_id = await service.meeting_gremium_id(meeting_id)
    if not await service.can_manage(gremium_id, principal):
        raise ForbiddenError("not allowed to manage the guests of this meeting")


@router.get(
    "/meetings/{meeting_id}/guests",
    response_model=list[MeetingGuestOut],
    responses=_errors(401, 403, 404),
)
async def list_meeting_guests(
    meeting_id: UUID, service: ServiceDep, guests: GuestServiceDep, principal: ReaderDep
) -> list[MeetingGuestOut]:
    """List the join requests and the guests of a public meeting (#17).

    The open requests come first. Only the meeting lead (``session.manage``) sees the
    names.
    """
    await _require_manage(service, meeting_id, principal)
    return await guests.list(meeting_id)


@router.post(
    "/meetings/{meeting_id}/guests/admit-all",
    response_model=list[MeetingGuestOut],
    responses=_errors(401, 403, 404, 409),
)
async def admit_all_meeting_guests(
    meeting_id: UUID, service: ServiceDep, guests: GuestServiceDep, principal: ReaderDep
) -> list[MeetingGuestOut]:
    """Admit every waiting guest (#17). Writes ``guest_admit_all`` with the count."""
    await _require_manage(service, meeting_id, principal)
    return await guests.admit_all(meeting_id, actor_sub=principal.sub)


@router.post(
    "/meetings/{meeting_id}/guests/{guest_id}/admit",
    response_model=MeetingGuestOut,
    responses=_errors(401, 403, 404, 409),
)
async def admit_meeting_guest(
    meeting_id: UUID,
    guest_id: UUID,
    service: ServiceDep,
    guests: GuestServiceDep,
    principal: ReaderDep,
) -> MeetingGuestOut:
    """Admit a waiting guest (#17). 409 ``guest_not_pending`` for any other status.

    A guest admitted while a vote with guests is open votes in it too.
    """
    await _require_manage(service, meeting_id, principal)
    return await guests.admit(meeting_id, guest_id, actor_sub=principal.sub)


@router.post(
    "/meetings/{meeting_id}/guests/{guest_id}/reject",
    response_model=MeetingGuestOut,
    responses=_errors(401, 403, 404, 409),
)
async def reject_meeting_guest(
    meeting_id: UUID,
    guest_id: UUID,
    service: ServiceDep,
    guests: GuestServiceDep,
    principal: ReaderDep,
) -> MeetingGuestOut:
    """Reject a waiting guest (#17). The device may ask again after 3 minutes."""
    await _require_manage(service, meeting_id, principal)
    return await guests.reject(meeting_id, guest_id, actor_sub=principal.sub)


@router.post(
    "/meetings/{meeting_id}/guests/{guest_id}/remove",
    response_model=MeetingGuestOut,
    responses=_errors(401, 403, 404, 409),
)
async def remove_meeting_guest(
    meeting_id: UUID,
    guest_id: UUID,
    service: ServiceDep,
    guests: GuestServiceDep,
    principal: ReaderDep,
) -> MeetingGuestOut:
    """Remove an admitted guest (#17). The cast ballots stay counted."""
    await _require_manage(service, meeting_id, principal)
    return await guests.remove(meeting_id, guest_id, actor_sub=principal.sub)


@router.post(
    "/meetings/{meeting_id}/guests/{guest_id}/rename",
    response_model=MeetingGuestOut,
    responses=_errors(401, 403, 404, 409, 422),
)
async def rename_meeting_guest(
    meeting_id: UUID,
    guest_id: UUID,
    payload: GuestNameBody,
    service: ServiceDep,
    guests: GuestServiceDep,
    principal: ReaderDep,
) -> MeetingGuestOut:
    """Give a guest another name (#17). The audit entry holds the guest id only."""
    await _require_manage(service, meeting_id, principal)
    return await guests.rename(
        meeting_id, guest_id, payload.display_name, actor_sub=principal.sub
    )


@router.get(
    "/meetings/{meeting_id}/join-link",
    response_model=JoinLinkOut,
    responses=_errors(401, 403, 404, 409),
)
async def get_meeting_join_link(
    meeting_id: UUID, service: ServiceDep, guests: GuestServiceDep, principal: ReaderDep
) -> JoinLinkOut:
    """Return the join link and its QR code (#17); 409 when the meeting is not public."""
    await _require_manage(service, meeting_id, principal)
    return await guests.join_link(meeting_id)


@router.post(
    "/meetings/{meeting_id}/join-code/rotate",
    response_model=JoinLinkOut,
    responses=_errors(401, 403, 404, 409),
)
async def rotate_meeting_join_code(
    meeting_id: UUID, service: ServiceDep, guests: GuestServiceDep, principal: ReaderDep
) -> JoinLinkOut:
    """Replace the join code (#17). The old link stops working; open requests are void.

    The admitted guests stay. Writes ``meeting_join_code_rotated``.
    """
    await _require_manage(service, meeting_id, principal)
    return await guests.rotate(meeting_id, actor_sub=principal.sub)


# WebSocket
async def _authorize(
    websocket: WebSocket,
    meeting_id: UUID,
    principal: Principal | None,
    meetings: MeetingService,
    *,
    beamer: bool,
) -> tuple[Principal, bool] | None:
    """Check the handshake authentication and the RBAC.

    Returns:
        The principal and its ``canManage`` flag (#17: the guest events with names
        reach only the meeting lead), or ``None`` when the socket is already closed.
    """
    if principal is None:
        await websocket.close(code=WS_UNAUTHENTICATED)
        return None
    try:
        meeting = await meetings.get(meeting_id, principal)
    except NotFoundError:
        await websocket.close(code=WS_NOT_FOUND)
        return None
    # Voter channel: active Gremium members and the external substitutes that hold
    # a delegation for this meeting may read the live stream. The vote right itself
    # is gated separately through the gremium ``vote.cast`` and the delegation check. The
    # dedicated read-only beamer channel needs ``session.manage`` in the Gremium of
    # the meeting (or the admin role).
    eligible = (
        await meetings.can_manage(meeting.gremium_id, principal)
        if beamer
        else await meetings.is_participant(meeting_id, meeting.gremium_id, principal)
    )
    if not eligible:
        await websocket.accept()
        await websocket.send_json(ErrorEvent(code="not_eligible").dump())
        await websocket.close(code=WS_FORBIDDEN)
        return None
    return principal, meeting.can_manage


async def _serve(
    websocket: WebSocket,
    meeting_id: UUID,
    principal: Principal | None,
    meetings: MeetingService,
    voting: VotingService,
    broker: MeetingBroker,
    locker: Locker,
    *,
    beamer: bool,
) -> None:
    authorization = await _authorize(websocket, meeting_id, principal, meetings, beamer=beamer)
    if authorization is None:
        return
    authorized, can_manage = authorization
    # Check the connection cap per meeting and principal before the accept, so a
    # flooding client never opens a socket. Above the cap the server sends a
    # ``too_many_connections`` frame and closes with 4403, the code that the RBAC
    # rejection also uses.
    if not _try_acquire_slot(meeting_id, authorized.sub):
        await websocket.accept()
        await websocket.send_json(ErrorEvent(code="too_many_connections").dump())
        await websocket.close(code=WS_FORBIDDEN)
        return
    try:
        await websocket.accept()
        await LiveVoteConnection(
            websocket,
            meeting_id,
            beamer=beamer,
            principal=authorized,
            meetings=meetings,
            voting=voting,
            broker=broker,
            locker=locker,
            can_manage=can_manage,
        ).run()
    finally:
        _release_slot(meeting_id, authorized.sub)


@router.websocket("/ws/meetings/{meeting_id}")
async def meeting_socket(
    websocket: WebSocket,
    meeting_id: UUID,
    principal: WsPrincipalDep,
    meetings: MeetingServiceWsDep,
    voting: VotingServiceWsDep,
    broker: BrokerWsDep,
    locker: LockerWsDep,
) -> None:
    """Voter channel: live state, ``cast`` (lock + unique), ``subscribe`` (reconnect)."""
    await _serve(websocket, meeting_id, principal, meetings, voting, broker, locker, beamer=False)


@router.websocket("/ws/meetings/{meeting_id}/beamer")
async def beamer_socket(
    websocket: WebSocket,
    meeting_id: UUID,
    principal: WsPrincipalDep,
    meetings: MeetingServiceWsDep,
    voting: VotingServiceWsDep,
    broker: BrokerWsDep,
    locker: LockerWsDep,
) -> None:
    """Read-only beamer stream: only ``meeting_state|vote_opened|vote_tally|vote_closed``."""
    await _serve(websocket, meeting_id, principal, meetings, voting, broker, locker, beamer=True)
