"""Admin routes of the guest, meeting and login settings."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import DbSession, Principal, require_principal
from app.modules.admin.router.deps import _GREMIEN, _USERS, GremienAdmin, UsersAdmin, _errors
from app.modules.admin.schemas import (
    GremiumDefaults,
    GuestSettingsOut,
    GuestSettingsUpdate,
    LoginSettingsOut,
    LoginSettingsUpdate,
    MeetingPeriods,
    MeetingSettingsOut,
    MeetingSettingsUpdate,
)
from app.modules.applications.guest_settings import GuestSettingsService
from app.modules.auth.login_settings import LoginSettingsService
from app.modules.livevote.open_window import MeetingSettingsService, gremium_defaults
from app.modules.meetings.periods import periods
from app.shared.errors import ForbiddenError

router = APIRouter(prefix="/admin", tags=["admin"])


DeadlinesAdmin = Annotated[Principal, Depends(require_principal("admin.deadlines"))]


def get_guest_settings_service(session: DbSession) -> GuestSettingsService:
    """Build the guest-settings service."""
    return GuestSettingsService(session)


GuestSettingsServiceDep = Annotated[GuestSettingsService, Depends(get_guest_settings_service)]


@router.get(
    "/guest-settings",
    response_model=GuestSettingsOut,
    dependencies=[Depends(require_principal("admin.deadlines"))],
    responses=_errors(401, 403),
)
async def get_guest_settings(service: GuestSettingsServiceDep) -> GuestSettingsOut:
    """Return the confirmation window (hours) and the magic-link lifetime (days)."""
    row = await service.get()
    await service.session.commit()
    return GuestSettingsOut.model_validate(row, from_attributes=True)


@router.put(
    "/guest-settings",
    response_model=GuestSettingsOut,
    responses=_errors(400, 401, 403, 422),
)
async def put_guest_settings(
    payload: GuestSettingsUpdate,
    service: GuestSettingsServiceDep,
    principal: DeadlinesAdmin,
) -> GuestSettingsOut:
    """Replace both values. ``linkTtlDays: null`` gives magic links without an expiry.

    A new ``confirmTtlHours`` applies to the waiting applications at the next
    worker run. A new ``linkTtlDays`` applies to the links requested from now on;
    the existing links keep their expiry. The change writes a ``config_change``
    audit entry that the audit log cannot revert.
    """
    row = await service.update(
        confirm_ttl_hours=payload.confirm_ttl_hours,
        link_ttl_days=payload.link_ttl_days,
        actor=principal.sub,
    )
    return GuestSettingsOut.model_validate(row, from_attributes=True)


def get_meeting_settings_service(session: DbSession) -> MeetingSettingsService:
    """Build the meeting-settings service."""
    return MeetingSettingsService(session)


MeetingSettingsServiceDep = Annotated[MeetingSettingsService, Depends(get_meeting_settings_service)]


def get_login_settings_service(session: DbSession) -> LoginSettingsService:
    """Build the login-settings service."""
    return LoginSettingsService(session)


LoginSettingsServiceDep = Annotated[LoginSettingsService, Depends(get_login_settings_service)]


@router.get(
    "/meeting-settings",
    response_model=MeetingSettingsOut,
    dependencies=[Depends(require_principal("admin.deadlines"))],
    responses=_errors(401, 403),
)
async def get_meeting_settings(service: MeetingSettingsServiceDep) -> MeetingSettingsOut:
    """Return the earliest open of meetings, in minutes before the planned start."""
    row = await service.get()
    await service.session.commit()
    return MeetingSettingsOut.model_validate(row, from_attributes=True)


@router.put(
    "/meeting-settings",
    response_model=MeetingSettingsOut,
    responses=_errors(400, 401, 403, 422),
)
async def put_meeting_settings(
    payload: MeetingSettingsUpdate,
    service: MeetingSettingsServiceDep,
    principal: DeadlinesAdmin,
) -> MeetingSettingsOut:
    """Replace the value.

    ``openLeadMinutes`` is the earliest open before the planned start. The change
    applies to every planned meeting at once and writes a ``config_change`` audit
    entry that the audit log cannot revert.
    """
    row = await service.update(open_lead_minutes=payload.open_lead_minutes, actor=principal.sub)
    return MeetingSettingsOut.model_validate(row, from_attributes=True)


@router.get(
    "/gremium-defaults",
    response_model=GremiumDefaults,
    dependencies=[_GREMIEN],
    responses=_errors(401, 403),
)
async def get_gremium_defaults(service: MeetingSettingsServiceDep) -> GremiumDefaults:
    """Return the values that the form of a new Gremium starts with."""
    row = await service.get()
    await service.session.commit()
    return GremiumDefaults.model_validate(gremium_defaults(row))


@router.put(
    "/gremium-defaults",
    response_model=GremiumDefaults,
    responses=_errors(400, 401, 403, 422),
)
async def put_gremium_defaults(
    payload: GremiumDefaults,
    service: MeetingSettingsServiceDep,
    principal: GremienAdmin,
) -> GremiumDefaults:
    """Replace the values that the form of a new Gremium starts with.

    A change touches no Gremium that exists. It writes a ``config_change`` audit entry
    that the audit log cannot revert.
    """
    row = await service.update_gremium_defaults(
        payload.model_dump(by_alias=True), actor=principal.sub
    )
    await service.session.commit()
    return GremiumDefaults.model_validate(gremium_defaults(row))


@router.get(
    "/meeting-periods",
    response_model=MeetingPeriods,
    dependencies=[Depends(require_principal("admin.deadlines"))],
    responses=_errors(401, 403),
)
async def get_meeting_periods(service: MeetingSettingsServiceDep) -> MeetingPeriods:
    """Return the periods of the Geschäftsordnung."""
    row = await service.get()
    await service.session.commit()
    return MeetingPeriods.model_validate(periods(row))


@router.put(
    "/meeting-periods",
    response_model=MeetingPeriods,
    responses=_errors(400, 401, 403, 422),
)
async def put_meeting_periods(
    payload: MeetingPeriods,
    service: MeetingSettingsServiceDep,
    principal: DeadlinesAdmin,
) -> MeetingPeriods:
    """Replace the periods of the Geschäftsordnung.

    The change applies at once: to the warning of the meeting form, to the late
    excuse, to the absence count and to a new Umlaufverfahren. It writes a
    ``config_change`` audit entry that the audit log cannot revert.
    """
    row = await service.update_periods(payload.model_dump(by_alias=True), actor=principal.sub)
    await service.session.commit()
    return MeetingPeriods.model_validate(periods(row))


@router.get(
    "/login-settings",
    response_model=LoginSettingsOut,
    dependencies=[_USERS],
    responses=_errors(401, 403),
)
async def get_login_settings(service: LoginSettingsServiceDep) -> LoginSettingsOut:
    """Return the lifetime of an OIDC login in a browser tab and in the installed app."""
    row = await service.get()
    await service.session.commit()
    return LoginSettingsOut.model_validate(row, from_attributes=True)


@router.put(
    "/login-settings",
    response_model=LoginSettingsOut,
    responses=_errors(400, 401, 403, 422),
)
async def put_login_settings(
    payload: LoginSettingsUpdate,
    service: LoginSettingsServiceDep,
    principal: UsersAdmin,
) -> LoginSettingsOut:
    """Replace both lifetimes (days after the last use, 1 to 400).

    A new value applies to every session at its next check at the IdP, so the
    existing sessions follow it too. The change writes a ``config_change`` audit
    entry that the audit log cannot revert. Only a person in the browser may change
    the session policy: an agent token (OAuth scope) gets 403, also with
    ``admin:write``, like the account merge.
    """
    if principal.scope_permissions is not None:
        raise ForbiddenError(
            "Agent tokens cannot change the session lifetimes.", code="cookie_session_required"
        )
    row = await service.update(
        web_session_days=payload.web_session_days,
        pwa_session_days=payload.pwa_session_days,
        actor=principal.sub,
    )
    return LoginSettingsOut.model_validate(row, from_attributes=True)
