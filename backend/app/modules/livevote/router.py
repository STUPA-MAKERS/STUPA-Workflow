"""Live-Vote/Meeting-Router (T-16, api.md §4).

REST (problem+json):
* ``POST  /api/meetings``            — P(meeting.manage); Sitzung anlegen.
* ``GET   /api/meetings/{id}``       — P; Sitzungs-State.
* ``PATCH /api/meetings/{id}``       — P(meeting.manage); Steuerung → ``meeting_state``.

WebSocket (api.md §4):
* ``/api/ws/meetings/{id}``          — P + Gremium-Gruppe; Voter-Kanal (cast/subscribe).
* ``/api/ws/meetings/{id}/beamer``   — P(meeting.manage); read-only Beamer-Stream.

Auth ist fail-closed: REST 401/403 via ``require_principal``; WS schließt mit
``4401`` (keine Session) bzw. ``4403`` (nicht berechtigt) **nach** einem
``error``-Frame ``not_eligible`` (api.md §4).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, WebSocket

from app.deps import DbSession, require_principal
from app.modules.auth.principal import Principal
from app.modules.livevote.broker import InMemoryBroker, MeetingBroker
from app.modules.livevote.connection import (
    WS_FORBIDDEN,
    WS_NOT_FOUND,
    WS_UNAUTHENTICATED,
    LiveVoteConnection,
    resolve_ws_principal,
)
from app.modules.livevote.attendance_service import AttendanceService
from app.modules.livevote.events import ErrorEvent
from app.modules.livevote.locks import InMemoryLocker, Locker
from app.modules.livevote.schemas import (
    AttendanceOut,
    AttendanceSetBody,
    MeetingCreate,
    MeetingOut,
    MeetingPatch,
)
from app.modules.livevote.service import BrokerPublisher, MeetingService
from app.modules.voting.service import VotingService
from app.settings import Settings, get_settings
from app.shared.errors import ForbiddenError, NotFoundError, ProblemDetail

router = APIRouter(tags=["livevote"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
MANAGE_PERMISSION = "meeting.manage"

# Single-Prozess-Fallback, falls die Lifespan keinen Broker/Locker auf den App-State
# gelegt hat (z. B. Tests ohne Wiring). Prod nutzt Redis (s. ``create_app``).
_FALLBACK_BROKER = InMemoryBroker()
_FALLBACK_LOCKER = InMemoryLocker()


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


# --------------------------------------------------------------------------- #
# Provider (aus App-State; in Tests via dependency_overrides ersetzbar)
# --------------------------------------------------------------------------- #
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
    """Meeting-Service für den WS-Pfad (Broker aus dem WS-App-State)."""
    return MeetingService(session, BrokerPublisher(broker))


def get_attendance_service(session: DbSession) -> AttendanceService:
    return AttendanceService(session)


def get_voting_service_ws(session: DbSession) -> VotingService:
    """Voting-Service für den WS-Cast-Pfad (eigene Session, Flow-Dispatch default)."""
    return VotingService(session)


async def get_ws_principal(
    websocket: WebSocket,
    session: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal | None:
    """Handshake-Principal aus dem Session-Cookie (``None`` ohne gültige Session)."""
    return await resolve_ws_principal(websocket, session, settings)


ServiceDep = Annotated[MeetingService, Depends(get_meeting_service)]
AttendanceDep = Annotated[AttendanceService, Depends(get_attendance_service)]
ManagerDep = Annotated[Principal, Depends(require_principal(MANAGE_PERMISSION))]
ReaderDep = Annotated[Principal, Depends(require_principal())]
SettingsDep = Annotated[Settings, Depends(get_settings)]
BrokerWsDep = Annotated[MeetingBroker, Depends(get_broker_ws)]
LockerWsDep = Annotated[Locker, Depends(get_locker_ws)]
MeetingServiceWsDep = Annotated[MeetingService, Depends(get_meeting_service_ws)]
VotingServiceWsDep = Annotated[VotingService, Depends(get_voting_service_ws)]
WsPrincipalDep = Annotated[Principal | None, Depends(get_ws_principal)]


# --------------------------------------------------------------------------- #
# REST
# --------------------------------------------------------------------------- #
@router.post(
    "/meetings", response_model=MeetingOut, responses=_errors(400, 401, 403, 422)
)
async def create_meeting(
    payload: MeetingCreate, service: ServiceDep, principal: ManagerDep
) -> MeetingOut:
    """Sitzung (``planned``) anlegen."""
    return await service.create(payload, principal)


@router.get("/meetings", response_model=list[MeetingOut], responses=_errors(401, 403))
async def list_meetings(
    service: ServiceDep,
    principal: ReaderDep,
    gremium_id: Annotated[UUID | None, Query(alias="gremiumId")] = None,
) -> list[MeetingOut]:
    """Sitzungen auflisten (neueste zuerst), optional Gremium-gefiltert (#104)."""
    return await service.list(principal, gremium_id)


@router.get(
    "/meetings/{meeting_id}", response_model=MeetingOut, responses=_errors(401, 403, 404)
)
async def get_meeting(
    meeting_id: UUID, service: ServiceDep, principal: ReaderDep
) -> MeetingOut:
    """Sitzungs-State."""
    return await service.get(meeting_id, principal)


@router.patch(
    "/meetings/{meeting_id}",
    response_model=MeetingOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def patch_meeting(
    meeting_id: UUID, payload: MeetingPatch, service: ServiceDep, principal: ManagerDep
) -> MeetingOut:
    """Steuerung (``activeApplicationId``/``status``) → ``meeting_state``-Broadcast.

    Zusätzlich zu ``meeting.manage`` muss der Principal die Sitzungsleitung des
    Gremiums sein (Vorstand/Schriftführung) oder Admin (#Meetings)."""
    return await service.patch(meeting_id, payload, principal)


# --------------------------------------------------------------------------- #
# Anwesenheit (#Meetings/#55/#56)
# --------------------------------------------------------------------------- #
@router.get(
    "/meetings/{meeting_id}/attendance",
    response_model=list[AttendanceOut],
    responses=_errors(401, 403, 404),
)
async def list_attendance(
    meeting_id: UUID, attendance: AttendanceDep, principal: ReaderDep
) -> list[AttendanceOut]:
    """Anwesenheits-Roster (aktuelle Gremium-Mitglieder + Status)."""
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
    """Eigene Anwesenheit markieren (nur Gremium-Mitglieder)."""
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
    principal: ManagerDep,
) -> list[AttendanceOut]:
    """Anwesenheit eines Mitglieds setzen — nur Sitzungsleitung/Admin (#Meetings)."""
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_control:
        raise ForbiddenError("only the committee lead may set members' attendance")
    return await attendance.set_for(meeting_id, principal_id, payload.status, principal.sub)


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #
async def _authorize(
    websocket: WebSocket,
    meeting_id: UUID,
    principal: Principal | None,
    meetings: MeetingService,
    *,
    beamer: bool,
) -> Principal | None:
    """Handshake-Auth/RBAC. Gibt ``None`` zurück, wenn bereits geschlossen wurde."""
    if principal is None:
        await websocket.close(code=WS_UNAUTHENTICATED)
        return None
    try:
        meeting = await meetings.get(meeting_id, principal)
    except NotFoundError:
        await websocket.close(code=WS_NOT_FOUND)
        return None
    eligible = (
        principal.has(MANAGE_PERMISSION)
        if beamer
        else principal.in_group(str(meeting.gremium_id))
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
    """Voter-Kanal: Live-State, ``cast`` (Lock + unique), ``subscribe`` (Reconnect)."""
    await _serve(
        websocket, meeting_id, principal, meetings, voting, broker, locker, beamer=False
    )


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
    """Read-only Beamer-Stream: nur ``meeting_state|vote_opened|vote_tally|vote_closed``."""
    await _serve(
        websocket, meeting_id, principal, meetings, voting, broker, locker, beamer=True
    )
