"""Public routes of a meeting with a QR code (#17).

A person without an account reaches these routes from the join page `/j/<code>`. No
session is involved. The device token sits in the HttpOnly cookie `mg_token`
(SameSite=Strict, path `/api/public/meetings`); the server keeps only its hash.

Abuse protection: ALTCHA, a body cap and a limit per IP and per join code on the
join; a limit per IP on the reads; a limit per device on the writes of a guest. The
default write limit per IP does not apply to these routes (many guests share the
campus NAT). The guest WebSocket checks the `Origin` like the member channel.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, WebSocket
from sqlalchemy import select

from app.deps import DbSession
from app.modules.flow.dispatch import ActionDispatcher
from app.modules.flow.router import get_action_dispatcher
from app.modules.livevote.broker import MeetingBroker
from app.modules.livevote.connection import (
    WS_FORBIDDEN,
    WS_NOT_FOUND,
    WS_UNAUTHENTICATED,
    origin_allowed,
)
from app.modules.livevote.events import ErrorEvent, GuestStatusEvent
from app.modules.livevote.guest_connection import GuestConnection
from app.modules.livevote.guests import GuestService, token_hash
from app.modules.livevote.models import MeetingGuest
from app.modules.livevote.public_schemas import (
    GuestBallotBody,
    GuestJoinBody,
    GuestMe,
    PublicMeetingHead,
)
from app.modules.livevote.router import get_broker_rest, get_broker_ws
from app.modules.livevote.schemas import GuestNameBody
from app.modules.livevote.service import BrokerPublisher
from app.modules.voting.schemas import BallotAccepted
from app.modules.voting.service import VotingService
from app.settings import Settings, get_settings
from app.shared.antiabuse import (
    RateLimiterDep,
    client_ip,
    enforce_auth_payload_limit,
    get_rate_limiter,
    rate_limit_public_join,
    rate_limit_public_read,
    verify_altcha,
)
from app.shared.errors import NotFoundError, ProblemDetail, RateLimitedError, UnauthorizedError

router = APIRouter(prefix="/public/meetings", tags=["public-meetings"])

# The path of the device cookie: only the public meeting routes see it.
GUEST_COOKIE_PATH = "/api/public/meetings"

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}

# Close code of a guest socket handshake over the rate limit.
WS_RATE_LIMITED = 4429
_HOUR = 3600
# The cookie lasts at least this long; for a meeting in the future until its day ends.
_MIN_COOKIE_TTL = timedelta(hours=24)

# Cap of the concurrent sockets per guest device (DoS guard, per process).
_MAX_CONNECTIONS_PER_GUEST = 3
_guest_connections: dict[UUID, int] = {}

SettingsDep = Annotated[Settings, Depends(get_settings)]


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_public_guest_service(
    session: DbSession,
    broker: Annotated[MeetingBroker, Depends(get_broker_rest)],
    settings: SettingsDep,
) -> GuestService:
    return GuestService(session, BrokerPublisher(broker), base_url=settings.public_base_url)


def get_public_voting_service(
    session: DbSession,
    dispatcher: Annotated[ActionDispatcher, Depends(get_action_dispatcher)],
) -> VotingService:
    """Voting service with the app flow dispatcher: a guest ballot never closes a vote,
    but the service keeps one construction path."""
    return VotingService(session, dispatcher)


GuestsDep = Annotated[GuestService, Depends(get_public_guest_service)]
VotingDep = Annotated[VotingService, Depends(get_public_voting_service)]


def _token(request: Request, settings: Settings) -> str | None:
    return request.cookies.get(settings.guest_cookie_name)


def cookie_ttl_seconds(meeting_date: date | None, settings: Settings, now: datetime) -> int:
    """Return the lifetime of the device cookie.

    The base is ``guest_cookie_ttl_hours``. A join before a planned meeting keeps the
    cookie until the end of the day after the meeting day, so the guest can return on
    that day. The token itself stops working when the meeting closes.
    """
    base = timedelta(hours=settings.guest_cookie_ttl_hours)
    if meeting_date is None:
        return int(base.total_seconds())
    end = datetime.combine(meeting_date + timedelta(days=2), time(0, 0), tzinfo=UTC)
    return int(max(base, _MIN_COOKIE_TTL, end - now).total_seconds())


async def rate_limit_public_guest_write(
    request: Request,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    session: DbSession,
) -> None:
    """The writes of a guest (name, leave, ballot): a limit per guest, else per IP.

    The key is the guest of the device token when the token resolves. An unknown or
    missing cookie counts against the IP, so random cookies get no fresh budget.
    """
    token = request.cookies.get(settings.guest_cookie_name)
    guest_id = (
        await session.scalar(
            select(MeetingGuest.id).where(MeetingGuest.token_hash == token_hash(token))
        )
        if token
        else None
    )
    key = f"public-guest:{guest_id}" if guest_id else f"public-guest:ip:{client_ip(request)}"
    result = await limiter.hit(
        key, limit=settings.rl_public_guest_write_per_hour, window_seconds=_HOUR
    )
    if not result.allowed:
        raise RateLimitedError(
            "Too many requests. Try again later.", retry_after=result.retry_after
        )


def _set_cookie(response: Response, token: str, settings: Settings, max_age: int) -> None:
    response.set_cookie(
        settings.guest_cookie_name,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=GUEST_COOKIE_PATH,
    )


def _clear_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.guest_cookie_name,
        path=GUEST_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


@router.get(
    "/{code}",
    response_model=PublicMeetingHead,
    responses=_errors(404, 429),
    dependencies=[Depends(rate_limit_public_read)],
)
async def public_meeting_head(code: str, guests: GuestsDep) -> PublicMeetingHead:
    """The head of a public meeting for the join page.

    404 ``join_code_unknown`` for an unknown code, 404 ``meeting_not_public`` when the
    public participation is off.
    """
    return await guests.head(code)


@router.post(
    "/join/{code}",
    response_model=GuestMe,
    responses=_errors(400, 404, 409, 413, 422, 429),
    dependencies=[
        Depends(enforce_auth_payload_limit),
        Depends(rate_limit_public_join),
        Depends(verify_altcha),
    ],
)
async def join_public_meeting(
    code: str,
    payload: GuestJoinBody,
    request: Request,
    response: Response,
    guests: GuestsDep,
    settings: SettingsDep,
) -> GuestMe:
    """Ask to join a public meeting with a name.

    The request waits for the meeting lead. A new device gets the token cookie. A
    second request of the same device replaces the first one. 409 ``meeting_closed``,
    409 ``already_admitted``, 429 ``retry_later`` (``Retry-After``) within 3 minutes
    after a rejection or a removal.
    """
    me, token = await guests.join(
        code, payload.display_name, _token(request, settings), now=datetime.now(UTC)
    )
    if token is not None:
        now = datetime.now(UTC)
        _set_cookie(response, token, settings, cookie_ttl_seconds(me.meeting.date, settings, now))
    return me


@router.get(
    "/{code}/me",
    response_model=GuestMe,
    responses=_errors(401, 404, 429),
    dependencies=[Depends(rate_limit_public_read)],
)
async def public_guest_me(
    code: str, request: Request, guests: GuestsDep, settings: SettingsDep
) -> GuestMe:
    """The own state of the device, and once admitted the participant view.

    401 ``guest_token_missing``, 404 ``guest_not_found``, 404 ``meeting_not_public``.
    """
    return await guests.me(code, _token(request, settings), now=datetime.now(UTC))


@router.patch(
    "/{code}/me",
    response_model=GuestMe,
    responses=_errors(401, 404, 409, 413, 422, 429),
    dependencies=[Depends(enforce_auth_payload_limit), Depends(rate_limit_public_guest_write)],
)
async def rename_public_guest(
    code: str,
    payload: GuestNameBody,
    request: Request,
    guests: GuestsDep,
    settings: SettingsDep,
) -> GuestMe:
    """Change the own name while the request waits (409 ``guest_not_pending``)."""
    return await guests.rename_self(
        code, _token(request, settings), payload.display_name, now=datetime.now(UTC)
    )


@router.delete(
    "/{code}/me",
    status_code=204,
    responses=_errors(401, 404, 429),
    dependencies=[Depends(rate_limit_public_guest_write)],
)
async def leave_public_meeting(
    code: str, request: Request, response: Response, guests: GuestsDep, settings: SettingsDep
) -> Response:
    """Withdraw the request or leave the meeting.

    The own name becomes the pseudonym at once, and the device cookie goes.
    """
    await guests.leave(code, _token(request, settings), now=datetime.now(UTC))
    out = Response(status_code=204)
    _clear_cookie(out, settings)
    return out


@router.post(
    "/{code}/votes/{vote_id}/ballot",
    response_model=BallotAccepted,
    responses=_errors(401, 403, 404, 409, 413, 422, 429),
    dependencies=[Depends(enforce_auth_payload_limit), Depends(rate_limit_public_guest_write)],
)
async def cast_public_ballot(
    code: str,
    vote_id: UUID,
    payload: GuestBallotBody,
    request: Request,
    guests: GuestsDep,
    voting: VotingDep,
    settings: SettingsDep,
) -> BallotAccepted:
    """Cast the ballot of an admitted guest.

    The meeting must let guests vote, and the vote must be a vote with guests on a
    public agenda item of the meeting. One ballot, never changed after the cast.
    403 ``guest_not_admitted``, ``guests_watch_only``, ``vote_members_only``; 409
    ``already_voted``.
    """
    return await guests.cast(
        code,
        _token(request, settings),
        vote_id,
        payload.choice,
        voting=voting,
        now=datetime.now(UTC),
    )


def _try_acquire(guest_id: UUID) -> bool:
    current = _guest_connections.get(guest_id, 0)
    if current >= _MAX_CONNECTIONS_PER_GUEST:
        return False
    _guest_connections[guest_id] = current + 1
    return True


def _release(guest_id: UUID) -> None:
    current = _guest_connections.get(guest_id, 0)
    if current <= 1:
        _guest_connections.pop(guest_id, None)
    else:
        _guest_connections[guest_id] = current - 1


@router.websocket("/{code}/ws")
async def guest_socket(
    websocket: WebSocket,
    code: str,
    session: DbSession,
    settings: SettingsDep,
    broker: Annotated[MeetingBroker, Depends(get_broker_ws)],
) -> None:
    """The live channel of a guest device (cookie token, Origin check).

    Close codes: 4401 without a valid token, 4404 for an unknown guest or meeting,
    4403 for a foreign origin or too many connections, 4429 over the handshake limit
    per IP.
    """
    if not origin_allowed(websocket.headers.get("origin"), settings):
        await websocket.close(code=WS_FORBIDDEN)
        return
    # The handshake counts like a read of the guest page, per IP.
    limiter = get_rate_limiter(cast(Request, websocket), settings)
    ip = websocket.client.host if websocket.client is not None else "unknown"
    hit = await limiter.hit(
        f"public-ws:ip:{ip}",
        limit=settings.rl_public_meeting_read_ip_per_hour,
        window_seconds=_HOUR,
    )
    if not hit.allowed:
        await websocket.close(code=WS_RATE_LIMITED)
        return
    guests = GuestService(session)
    try:
        token = websocket.cookies.get(settings.guest_cookie_name)
        _meeting, guest = await guests.resolve(code, token)
    except UnauthorizedError:
        await websocket.close(code=WS_UNAUTHENTICATED)
        return
    except NotFoundError:
        await websocket.close(code=WS_NOT_FOUND)
        return
    finally:
        # End the read transaction, so the socket holds no open transaction. A
        # commit keeps the loaded rows (no expiry), unlike a rollback.
        await session.commit()
    if guest.status not in ("pending", "admitted"):
        await websocket.accept()
        await websocket.send_json(
            GuestStatusEvent(
                status=guest.status,  # type: ignore[arg-type]
                displayName=guest.display_name,
                number=guest.seq,
            ).dump()
        )
        await websocket.close(code=1000)
        return
    if not _try_acquire(guest.id):
        await websocket.accept()
        await websocket.send_json(ErrorEvent(code="too_many_connections").dump())
        await websocket.close(code=WS_FORBIDDEN)
        return
    try:
        await websocket.accept()
        await GuestConnection(
            websocket,
            session=session,
            broker=broker,
            meeting_id=guest.meeting_id,
            guest=guest,
        ).run()
    finally:
        _release(guest.id)
