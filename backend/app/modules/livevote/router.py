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

# Single-Prozess-Fallback, falls die Lifespan keinen Broker/Locker auf den App-State
# gelegt hat (z. B. Tests ohne Wiring). Prod nutzt Redis (s. ``create_app``).
_FALLBACK_BROKER = InMemoryBroker()
_FALLBACK_LOCKER = InMemoryLocker()

# Pro (Sitzung, Principal) gleichzeitig offene WS-Verbindungen (DoS-Schutz,
# security.md): ein einzelner Nutzer soll nicht beliebig viele Sockets öffnen
# (jeder hält ein Abo + Empfangs-Task). In-Prozess-Zähler (pro Worker-Prozess); für
# Single-Worker-Deployments ausreichend, ein verteiltes Limit liegt an Redis/Ingress.
_MAX_CONNECTIONS_PER_PRINCIPAL = 5
_connection_counts: dict[tuple[UUID, str], int] = {}


def _try_acquire_slot(meeting_id: UUID, sub: str) -> bool:
    """Einen Verbindungs-Slot belegen (``False``, wenn das Limit erreicht ist)."""
    key = (meeting_id, sub)
    current = _connection_counts.get(key, 0)
    if current >= _MAX_CONNECTIONS_PER_PRINCIPAL:
        return False
    _connection_counts[key] = current + 1
    return True


def _release_slot(meeting_id: UUID, sub: str) -> None:
    """Einen belegten Verbindungs-Slot freigeben (idempotent, räumt 0-Einträge auf)."""
    key = (meeting_id, sub)
    current = _connection_counts.get(key, 0)
    if current <= 1:
        _connection_counts.pop(key, None)
    else:
        _connection_counts[key] = current - 1


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


def get_agenda_service(session: DbSession) -> AgendaService:
    return AgendaService(session)


def get_voting_service(session: DbSession) -> VotingService:
    return VotingService(session)


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


# --------------------------------------------------------------------------- #
# REST
# --------------------------------------------------------------------------- #
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
    """Sitzung (``planned``) anlegen — Sitzungsverwalter (``session.manage``)/Admin.

    Die RBAC ist gremium-genau (Vorstand/Manager des Gremiums oder globale
    ``meeting.manage``); der Service wirft 403, wenn der Principal das Gremium nicht
    verwalten darf. Gremium-Mitglieder erhalten eine Sitzungs-Mail (#4-3)."""
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
    """Aktuelle Gremium-Mitglieder als Protokollant-Kandidaten — wer das Gremium
    verwalten darf (``session.manage``/Admin). Beim Anlegen einer Sitzung steht noch
    kein Roster bereit; diese Liste füllt die Protokollant-Auswahl im Create-Dialog."""
    if not await service.can_manage(gremium_id, principal):
        raise ForbiddenError("not allowed to manage meetings for this committee")
    return await attendance.members(gremium_id)


@router.get("/meetings", response_model=list[MeetingOut], responses=_errors(401, 403))
async def list_meetings(
    service: ServiceDep,
    principal: ReaderDep,
    gremium_id: Annotated[UUID | None, Query(alias="gremiumId")] = None,
) -> list[MeetingOut]:
    """Sitzungen auflisten (neueste zuerst), optional Gremium-gefiltert (#104)."""
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
    """Keyset-paginierte Sitzungs-Timeline um *jetzt* herum (#104).

    ``upcoming`` liefert anstehende Sitzungen chronologisch vorwärts, ``past`` die
    vergangenen rückwärts (für Infinite-Scroll nach oben). ``cursor`` stammt aus
    ``nextCursor`` der vorigen Seite; ``None`` ⇒ Beginn ab *jetzt*.

    Mit ``q`` kollabiert die Timeline in eine **einzige** relevanz-sortierte Liste
    (Fuzzy-Suche, #search): ``direction`` ist dann bedeutungslos, ``cursor`` trägt
    einen Offset, ``nextCursor === null`` ⇒ Ende der Trefferliste."""
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
    """Gremien für den Filter der Sitzungsübersicht (#meetings-filter).

    Liefert alle Gremien, in denen der Principal MINDESTENS EINE lesbare Sitzung hat
    — nicht die Mitglieds-Gremien. Muss VOR ``/meetings/{meeting_id}`` stehen, sonst
    fängt der UUID-Pfad ``gremien`` ab."""
    return await service.list_filter_gremien(principal)


@router.get("/meetings/{meeting_id}", response_model=MeetingOut, responses=_errors(401, 403, 404))
async def get_meeting(meeting_id: UUID, service: ServiceDep, principal: ReaderDep) -> MeetingOut:
    """Sitzungs-State."""
    await service.assert_can_read(meeting_id, principal)
    return await service.get(meeting_id, principal)


@router.delete("/meetings/{meeting_id}", status_code=204, responses=_errors(401, 403, 404))
async def delete_meeting(meeting_id: UUID, service: ServiceDep, principal: ReaderDep) -> None:
    """Sitzung löschen — nur Sitzungsverwalter (``session.manage``)/Admin."""
    await service.delete(meeting_id, principal)


@router.patch(
    "/meetings/{meeting_id}",
    response_model=MeetingOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def patch_meeting(
    meeting_id: UUID, payload: MeetingPatch, service: ServiceDep, principal: ReaderDep
) -> MeetingOut:
    """Steuerung/Planung → ``meeting_state``-Broadcast.

    Feld-genaue RBAC im Service: Status/aktiver Antrag = ``canWrite`` (Protokollant
    oder Verwalter); Datum/Zeit/Protokollant = ``canManage`` (Sitzungsverwalter).

    Start (planned→live): nach dem atomaren Status-Wechsel legt der Router das
    Protokoll an (idempotent). Das Protokoll entsteht ausschließlich hier — nicht
    manuell vorab. Der Service hat zuvor sichergestellt, dass ein Protokollant
    feststeht (sonst 409)."""
    updated = await service.patch(meeting_id, payload, principal)
    if payload.status == "live" and updated.status == "live":
        # Lokaler Import: ``protocol`` hängt von ``livevote`` — Modul-Level wäre ein
        # Zyklus. Dieselbe Session wie der Service (eine Transaktion/ein Commit).
        from app.modules.protocol.service import ProtocolService

        await ProtocolService(service.session).get_or_create(meeting_id, author=principal.sub)
        # Frisch lesen, damit die Antwort die neue ``protocolId`` trägt (das FE lädt
        # das Protokoll direkt nach dem Start darüber nach).
        return await service.get(meeting_id, principal)
    return updated


# --------------------------------------------------------------------------- #
# Anwesenheit (#Meetings/#55/#56)
# --------------------------------------------------------------------------- #
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
    """Anwesenheits-Roster (aktuelle Gremium-Mitglieder + Status)."""
    # #12 sec-audit: Roster (Namen/E-Mails) nur für Berechtigte der Sitzung.
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
    principal: ReaderDep,
) -> list[AttendanceOut]:
    """Anwesenheit eines Mitglieds setzen — wer die Sitzung führt (Protokollant/Verwalter)."""
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_write:
        raise ForbiddenError("not allowed to set members' attendance")
    return await attendance.set_for(meeting_id, principal_id, payload.status, principal.sub)


# --------------------------------------------------------------------------- #
# Tagesordnung (#10/#58)
# --------------------------------------------------------------------------- #
@router.get(
    "/meetings/{meeting_id}/agenda",
    response_model=list[AgendaItemOut],
    responses=_errors(401, 403, 404),
)
async def list_agenda(
    meeting_id: UUID, agenda: AgendaDep, service: ServiceDep, principal: ReaderDep
) -> list[AgendaItemOut]:
    """Tagesordnung der Sitzung (zugewiesene Anträge, geordnet)."""
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
    """Beschlussfrage eines TOP in dieser Sitzung anlegen + sofort öffnen (Live-Vote).

    Verwalter/Protokollant/``vote.manage``. Antrags-TOPs erlauben genau **eine**
    Abstimmung (sie feuert beim Schließen den pass/fail-Branch); Freitext-TOPs
    erlauben **mehrere** generische Beschlussfragen. ``eligibleGroup`` = Gremium der
    Sitzung; ``eligibleCount`` defaultet auf den Roster (Mitglieder mit ``vote.cast``).
    Broadcastet ``vote_opened``."""
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_manage_votes:
        raise ForbiddenError("not allowed to open a vote in this meeting")
    # Abstimmungen erst ab Start: vor »live« gibt es kein Protokoll, in dem das
    # Ergebnis festgehalten würde.
    if meeting.status != "live":
        raise ConflictError("the meeting has not started — start it before opening a vote")
    item = await agenda.item(meeting_id, payload.agenda_item_id)
    if item.application_id is not None:
        if await service.agenda_item_has_vote(item.id):
            raise ConflictError("this application TOP already has a decision vote")
        # Fail-fast statt erst beim Schließen: die Entscheidung eines Antrags-Votes
        # feuert den pass/fail-Branch des AKTUELLEN States. Ist der Antrag nicht in
        # einem vote-State, wäre der Vote unschließbar (409 erst beim close — die
        # abgegebenen Stimmen wären umsonst, #abort-vote).
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
    # Quorum-Default aus dem Gremium: wenn der Aufrufer keins angibt, übernimmt der
    # Vote das per-Gremium konfigurierte Prozent-Quorum (% der Stimmberechtigten, die
    # teilnehmen müssen). Explizit gesetzte Quoren bleiben unberührt (hier gibt es
    # bisher keine — der Open-Body kennt kein Quorum-Feld, daher reiner Default).
    if payload.quorum_percent is not None:
        config_data["quorum"] = {"type": "percent", "value": payload.quorum_percent}
    else:
        default_quorum = await service.gremium_quorum_percent(meeting.gremium_id)
        if default_quorum is not None:
            config_data["quorum"] = {"type": "percent", "value": default_quorum}
    config = VoteConfig.model_validate(config_data)
    eligible = payload.eligible_count
    if eligible is None:
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
    """Eine Beschlussfrage löschen (Stimmen inklusive). Verwalter/Protokollant/``vote.manage``."""
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
    """Anträge in einem Abstimmungs-State dieses Gremiums, noch nicht auf der TO."""
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
    """TOP setzen (Antrag oder Freitext) — nur Sitzungsleitung/Admin (#Meetings)."""
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
    """TOP von der Tagesordnung entfernen — nur Sitzungsleitung/Admin."""
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
    """TOPs umsortieren (Drag&Drop) — nur Sitzungsleitung/Admin."""
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
    """Markdown-Text/Titel eines TOP setzen (pro-TOP-Editor) — nur Sitzungsleitung/Admin."""
    meeting = await service.get(meeting_id, principal)
    if not meeting.can_write:
        raise ForbiddenError("not allowed to edit the agenda")
    # Protokollieren (TOP-Text) erst ab Start. Reine Titel-Umbenennung (Freitext-TOP)
    # gehört zur Planung und bleibt vor »live« erlaubt.
    if payload.body is not None and meeting.status != "live":
        raise ConflictError("the meeting has not started — start it before taking minutes")
    items = await agenda.set_body(
        meeting_id,
        item_id,
        body=payload.body,
        title=payload.title,
        non_public=payload.non_public,
    )
    # Live-Follower über den geänderten TOP-Text informieren (#live-refresh).
    await service.broadcast_state(meeting_id, principal)
    return items


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
    # Voter-Kanal: aktive Gremium-Mitglieder UND Delegations-Empfänger der Sitzung
    # (#delegation-rework — externe Stellvertreter) dürfen live mitlesen (das
    # STIMMRECHT ist separat über ``vote.cast``/Delegations-Check gegatet); die
    # »Beamer«-Ansicht für Mitglieder ist eine FE-Anzeige auf derselben Verbindung.
    # Der dedizierte read-only Beamer-Kanal bleibt ``meeting.manage``-gegatet.
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
    # Verbindungs-Cap je (Sitzung, Principal) — VOR dem Accept prüfen, damit ein
    # flutender Client gar nicht erst aufmacht (DoS-Schutz). Bei Überschreitung:
    # ``not_eligible``-Frame + 4403 (wie der RBAC-Verstoß).
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
    """Voter-Kanal: Live-State, ``cast`` (Lock + unique), ``subscribe`` (Reconnect)."""
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
    """Read-only Beamer-Stream: nur ``meeting_state|vote_opened|vote_tally|vote_closed``."""
    await _serve(websocket, meeting_id, principal, meetings, voting, broker, locker, beamer=True)
