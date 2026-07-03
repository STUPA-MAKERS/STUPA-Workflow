"""Live-vote/meeting router (REST + WebSocket).

Auth is fail-closed: REST 401/403 via ``require_principal``; the WS closes with
``4401`` (no session) or ``4403`` (not eligible) after a ``not_eligible`` error
frame.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, WebSocket

from app.deps import DbSession, require_principal
from app.modules.auth.principal import Principal
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
from app.modules.livevote.locks import InMemoryLocker, Locker
from app.modules.livevote.schemas import (
    AgendaAddBody,
    AgendaBodyBody,
    AgendaItemOut,
    AgendaReorderBody,
    AssignableApplicationOut,
    AttendanceOut,
    AttendanceSetBody,
    MeetingCreate,
    MeetingGremiumOut,
    MeetingMemberOut,
    MeetingOut,
    MeetingPage,
    MeetingPatch,
    MeetingVoteOpenBody,
)
from app.modules.livevote.service import BrokerPublisher, MeetingService
from app.modules.notifications.auto import AutoMailer, get_auto_mailer
from app.modules.voting.schemas import VoteCreate
from app.modules.voting.service import VotingService
from app.settings import Settings, get_settings
from app.shared.config_schemas import VoteConfig
from app.shared.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ProblemDetail,
)

router = APIRouter(tags=["livevote"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
MANAGE_PERMISSION = "meeting.manage"

# Single-process fallback when lifespan didn't wire a broker/locker onto app
# state (e.g. tests). Production uses Redis.
_FALLBACK_BROKER = InMemoryBroker()
_FALLBACK_LOCKER = InMemoryLocker()

# Cap on concurrent WS connections per (meeting, principal) (DoS guard): one user
# can't open unbounded sockets (each holds a subscription + receive task).
# Per-process counter; a distributed limit would live at Redis/ingress.
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
    """Release a connection slot (idempotent; cleans up zero entries)."""
    key = (meeting_id, sub)
    current = _connection_counts.get(key, 0)
    if current <= 1:
        _connection_counts.pop(key, None)
    else:
        _connection_counts[key] = current - 1


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


# Providers (from app state; overridable in tests via dependency_overrides).
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
    """Meeting service for the WS path (broker from WS app state)."""
    return MeetingService(session, BrokerPublisher(broker))


def get_attendance_service(session: DbSession) -> AttendanceService:
    return AttendanceService(session)


def get_agenda_service(session: DbSession) -> AgendaService:
    return AgendaService(session)


def get_voting_service(session: DbSession) -> VotingService:
    return VotingService(session)


def get_voting_service_ws(session: DbSession) -> VotingService:
    """Voting service for the WS cast path (own session, default flow dispatch)."""
    return VotingService(session)


async def get_ws_principal(
    websocket: WebSocket,
    session: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal | None:
    """Handshake principal from the session cookie (``None`` without a valid session)."""
    return await resolve_ws_principal(websocket, session, settings)


ServiceDep = Annotated[MeetingService, Depends(get_meeting_service)]
AttendanceDep = Annotated[AttendanceService, Depends(get_attendance_service)]
AgendaDep = Annotated[AgendaService, Depends(get_agenda_service)]
VotingDep = Annotated[VotingService, Depends(get_voting_service)]
BrokerRestDep = Annotated[MeetingBroker, Depends(get_broker_rest)]
ManagerDep = Annotated[Principal, Depends(require_principal(MANAGE_PERMISSION))]
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
    """Create a ``planned`` meeting — session manager (``session.manage``)/admin.

    RBAC is committee-scoped (committee board/manager or global
    ``meeting.manage``); the service raises 403 when the principal may not manage
    the committee. Committee members receive a meeting mail.
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
    """Current committee members as protokollant candidates — for whoever may
    manage the committee (``session.manage``/admin). Fills the protokollant picker
    in the create dialog before a roster exists.
    """
    if not await service.can_manage(gremium_id, principal):
        raise ForbiddenError("not allowed to manage meetings for this committee")
    return await attendance.members(gremium_id)


@router.get("/meetings", response_model=list[MeetingOut], responses=_errors(401, 403))
async def list_meetings(
    service: ServiceDep,
    principal: ReaderDep,
    gremium_id: Annotated[UUID | None, Query(alias="gremiumId")] = None,
) -> list[MeetingOut]:
    """List meetings (newest first), optionally committee-filtered."""
    return await service.list(principal, gremium_id)


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

    ``upcoming`` returns upcoming meetings forward, ``past`` past ones backward.
    ``cursor`` comes from the previous page's ``nextCursor``; ``None`` starts at
    *now*. With ``q`` the timeline collapses into a single relevance-sorted list
    (fuzzy search): ``direction`` is then irrelevant, ``cursor`` carries an offset,
    ``nextCursor === null`` ends the results.
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
    """Committees for the meeting-overview filter.

    Returns committees where the principal has at least one readable meeting, not
    their member committees. Must precede ``/meetings/{meeting_id}`` or the UUID
    path captures ``gremien``.
    """
    return await service.list_filter_gremien(principal)


@router.get("/meetings/{meeting_id}", response_model=MeetingOut, responses=_errors(401, 403, 404))
async def get_meeting(meeting_id: UUID, service: ServiceDep, principal: ReaderDep) -> MeetingOut:
    """Meeting state."""
    await service.assert_can_read(meeting_id, principal)
    return await service.get(meeting_id, principal)


@router.delete("/meetings/{meeting_id}", status_code=204, responses=_errors(401, 403, 404))
async def delete_meeting(meeting_id: UUID, service: ServiceDep, principal: ReaderDep) -> None:
    """Delete a meeting — session manager (``session.manage``)/admin only."""
    await service.delete(meeting_id, principal)


@router.patch(
    "/meetings/{meeting_id}",
    response_model=MeetingOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def patch_meeting(
    meeting_id: UUID, payload: MeetingPatch, service: ServiceDep, principal: ReaderDep
) -> MeetingOut:
    """Control/plan a meeting → ``meeting_state`` broadcast.

    Field-scoped RBAC in the service: status/active application = ``canWrite``
    (protokollant or manager); date/time/protokollant = ``canManage`` (session
    manager). On start (planned→live) the router creates the protocol (idempotent)
    — only here, never manually; the service has ensured a protokollant is set
    (else 409).
    """
    updated = await service.patch(meeting_id, payload, principal)
    if payload.status == "live" and updated.status == "live":
        # Local import: ``protocol`` depends on ``livevote``; module-level would
        # cycle. Same session as the service (one transaction/commit).
        from app.modules.protocol.service import ProtocolService

        await ProtocolService(service.session).get_or_create(meeting_id, author=principal.sub)
        # Re-read so the response carries the new ``protocolId``.
        return await service.get(meeting_id, principal)
    return updated


# Attendance
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
    """Attendance roster (current committee members + status)."""
    # Roster (names/emails) only for principals allowed to read the meeting.
    await service.assert_can_read(meeting_id, principal)
    return await attendance.roster(meeting_id, principal.sub)


@router.put(
    "/meetings/{meeting_id}/attendance/me",
    response_model=list[AttendanceOut],
    responses=_errors(401, 403, 404, 422),
)
async def set_own_attendance(
    meeting_id: UUID,
    payload: AttendanceSetBody,
    attendance: AttendanceDep,
    principal: ReaderDep,
) -> list[AttendanceOut]:
    """Mark own attendance (committee members only)."""
    return await attendance.set_self(meeting_id, payload.status, principal.sub)


@router.put(
    "/meetings/{meeting_id}/attendance/{principal_id}",
    response_model=list[AttendanceOut],
    responses=_errors(401, 403, 404, 422),
)
async def set_member_attendance(
    meeting_id: UUID,
    principal_id: UUID,
    payload: AttendanceSetBody,
    attendance: AttendanceDep,
    service: ServiceDep,
    principal: ReaderDep,
) -> list[AttendanceOut]:
    """Set a member's attendance — whoever leads the meeting (protokollant/manager)."""
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_write:
        raise ForbiddenError("not allowed to set members' attendance")
    return await attendance.set_for(meeting_id, principal_id, payload.status, principal.sub)


# Agenda
@router.get(
    "/meetings/{meeting_id}/agenda",
    response_model=list[AgendaItemOut],
    responses=_errors(401, 403, 404),
)
async def list_agenda(
    meeting_id: UUID, agenda: AgendaDep, service: ServiceDep, principal: ReaderDep
) -> list[AgendaItemOut]:
    """Meeting agenda (assigned applications, ordered)."""
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
    """Open a live vote on a TOP in this meeting (created + opened at once).

    Manager/protokollant/``vote.manage``. Application TOPs allow exactly one vote
    (it fires the pass/fail branch on close); free-text TOPs allow several generic
    questions. ``eligibleGroup`` = the meeting's committee; the quorum denominator
    is derived server-side from the roster (members with ``vote.cast``), never a
    client input. Broadcasts ``vote_opened``.
    """
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_manage_votes:
        raise ForbiddenError("not allowed to open a vote in this meeting")
    # Votes only after start: before ``live`` there is no protocol to record the
    # result in.
    if meeting.status != "live":
        raise ConflictError("the meeting has not started — start it before opening a vote")
    item = await agenda.item(meeting_id, payload.agenda_item_id)
    if item.application_id is not None:
        if await service.agenda_item_has_vote(item.id):
            raise ConflictError("this application TOP already has a decision vote")
        # Fail-fast: an application vote fires the pass/fail branch of the current
        # state on close. If the application isn't in a vote state the vote would
        # be unclosable, wasting the cast ballots.
        kind = await service.application_state_kind(item.application_id)
        if kind != "vote":
            raise ConflictError(
                "The application is not in a vote state — move it into its "
                "decision state before opening the vote.",
                code="conflict",
            )
    config_data: dict[str, object] = {
        "options": payload.options,
        "majorityRule": payload.majority_rule,
        "secret": payload.secret,
    }
    # Committee quorum default: without an explicit percent, the vote inherits the
    # committee's configured percent quorum.
    if payload.quorum_percent is not None:
        config_data["quorum"] = {"type": "percent", "value": payload.quorum_percent}
    else:
        default_quorum = await service.gremium_quorum_percent(meeting.gremium_id)
        if default_quorum is not None:
            config_data["quorum"] = {"type": "percent", "value": default_quorum}
    config = VoteConfig.model_validate(config_data)
    # Quorum denominator is always derived from the real roster, never from the
    # client, so a ``canManageVotes`` holder can't manipulate the quorum.
    eligible = await service.vote_eligible_count(meeting.gremium_id)
    create = VoteCreate(
        config=config,
        eligibleGroup=str(meeting.gremium_id),
        question=payload.question,
        eligibleCount=eligible,
    )
    vote = await voting.create(
        item.application_id, create, meeting_id=meeting_id, agenda_item_id=item.id
    )
    opened = await voting.open(vote.id, now=datetime.now(UTC))
    await BrokerPublisher(broker).vote_opened(opened)
    return await service.get(meeting_id, principal)


@router.delete(
    "/meetings/{meeting_id}/votes/{vote_id}",
    response_model=MeetingOut,
    responses=_errors(401, 403, 404),
)
async def delete_meeting_vote(
    meeting_id: UUID,
    vote_id: UUID,
    service: ServiceDep,
    voting: VotingDep,
    principal: ReaderDep,
) -> MeetingOut:
    """Delete a vote (ballots included). Manager/protokollant/``vote.manage``."""
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_manage_votes:
        raise ForbiddenError("not allowed to delete a vote in this meeting")
    await voting.delete(vote_id, meeting_id=meeting_id)
    return await service.get(meeting_id, principal)


@router.get(
    "/meetings/{meeting_id}/agenda/assignable",
    response_model=list[AssignableApplicationOut],
    responses=_errors(401, 403, 404),
)
async def list_assignable(
    meeting_id: UUID, agenda: AgendaDep, service: ServiceDep, principal: ReaderDep
) -> list[AssignableApplicationOut]:
    """Applications in a vote state of this committee, not yet on the agenda."""
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
    """Add a TOP (application or free-text) — session lead/admin only."""
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_write:
        raise ForbiddenError("not allowed to edit the agenda")
    return await agenda.add(
        meeting_id, payload.application_id, payload.title, non_public=payload.non_public
    )


@router.delete(
    "/meetings/{meeting_id}/agenda/{item_id}",
    response_model=list[AgendaItemOut],
    responses=_errors(401, 403, 404),
)
async def remove_agenda_item(
    meeting_id: UUID,
    item_id: UUID,
    agenda: AgendaDep,
    service: ServiceDep,
    principal: ReaderDep,
) -> list[AgendaItemOut]:
    """Remove a TOP from the agenda — session lead/admin only."""
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_write:
        raise ForbiddenError("not allowed to edit the agenda")
    return await agenda.remove(meeting_id, item_id)


@router.put(
    "/meetings/{meeting_id}/agenda/order",
    response_model=list[AgendaItemOut],
    responses=_errors(401, 403, 404, 422),
)
async def reorder_agenda(
    meeting_id: UUID,
    payload: AgendaReorderBody,
    agenda: AgendaDep,
    service: ServiceDep,
    principal: ReaderDep,
) -> list[AgendaItemOut]:
    """Reorder TOPs — session lead/admin only."""
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_write:
        raise ForbiddenError("not allowed to edit the agenda")
    return await agenda.reorder(meeting_id, payload.item_ids)


@router.patch(
    "/meetings/{meeting_id}/agenda/{item_id}",
    response_model=list[AgendaItemOut],
    responses=_errors(401, 403, 404, 422),
)
async def set_agenda_body(
    meeting_id: UUID,
    item_id: UUID,
    payload: AgendaBodyBody,
    agenda: AgendaDep,
    service: ServiceDep,
    principal: ReaderDep,
) -> list[AgendaItemOut]:
    """Set a TOP's markdown body/title (per-TOP editor) — session lead/admin only."""
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_write:
        raise ForbiddenError("not allowed to edit the agenda")
    # Minute-taking (TOP body) only after start; renaming a free-text TOP is
    # planning and stays allowed before ``live``.
    if payload.body is not None and meeting.status != "live":
        raise ConflictError("the meeting has not started — start it before taking minutes")
    items = await agenda.set_body(
        meeting_id,
        item_id,
        body=payload.body,
        title=payload.title,
        non_public=payload.non_public,
    )
    # Notify live followers of the changed TOP text.
    await service.broadcast_state(meeting_id, principal)
    return items


# WebSocket
async def _authorize(
    websocket: WebSocket,
    meeting_id: UUID,
    principal: Principal | None,
    meetings: MeetingService,
    *,
    beamer: bool,
) -> Principal | None:
    """Handshake auth/RBAC. Returns ``None`` when already closed."""
    if principal is None:
        await websocket.close(code=WS_UNAUTHENTICATED)
        return None
    try:
        meeting = await meetings.get(meeting_id, principal)
    except NotFoundError:
        await websocket.close(code=WS_NOT_FOUND)
        return None
    # Voter channel: active committee members and the meeting's delegation
    # recipients (external substitutes) may read live; the actual vote right is
    # gated separately via ``vote.cast``/delegation check. The dedicated read-only
    # beamer channel stays ``meeting.manage``-gated.
    eligible = (
        principal.has(MANAGE_PERMISSION)
        if beamer
        else await meetings.is_participant(meeting_id, meeting.gremium_id, principal)
    )
    if not eligible:
        await websocket.accept()
        await websocket.send_json(ErrorEvent(code="not_eligible").dump())
        await websocket.close(code=WS_FORBIDDEN)
        return None
    return principal


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
    authorized = await _authorize(websocket, meeting_id, principal, meetings, beamer=beamer)
    if authorized is None:
        return
    # Connection cap per (meeting, principal), checked before accept so a flooding
    # client never opens (DoS guard). On excess: a ``too_many_connections`` frame +
    # close 4403 (same code as the RBAC rejection).
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
