"""Web push API of the own account (§F/collaboration/notifications/002500-002507).

* ``GET /api/push/key`` — the public VAPID key that the browser subscribes with.
* ``GET /api/push/devices`` — the own devices with push.
* ``POST /api/push/devices`` — store the subscription of this device.
* ``DELETE /api/push/devices/{device_id}`` — remove one own device.
* ``GET /api/push/preferences`` — the own push switch of every kind.
* ``PUT /api/push/preferences`` — set the own push switches in bulk.

Every route needs an account session (002507): an applicant with a magic link has no
principal, so the gate refuses it. A person reads and changes only the own devices and
switches. While the feature push is off, the feature gate answers 404 first (002504).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import Field
from sqlalchemy import select

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.notifications.push_models import PushSubscription
from app.modules.notifications.push_service import (
    MAX_ENDPOINT_LEN,
    MAX_KEY_LEN,
    PushService,
    SubscriptionIn,
)
from app.shared.errors import NotFoundError, ProblemDetail
from app.shared.schemas import FrozenCamelModel, FrozenStrictCamelModel

router = APIRouter(prefix="/push", tags=["push"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_AUTH_ERRORS: dict[int | str, dict[str, Any]] = {401: _PROBLEM, 403: _PROBLEM, 404: _PROBLEM}

PrincipalDep = Annotated[Principal, Depends(require_principal())]


class PushKeyOut(FrozenCamelModel, frozen=True):
    """The public VAPID key of the platform, base64url."""

    public_key: str = Field(alias="publicKey")


class PushKeysIn(FrozenStrictCamelModel, frozen=True):
    """The keys of a browser subscription."""

    p256dh: str = Field(min_length=1, max_length=MAX_KEY_LEN)
    auth: str = Field(min_length=1, max_length=MAX_KEY_LEN)


class PushDeviceIn(FrozenStrictCamelModel, frozen=True):
    """The subscription of this device, as ``PushSubscription.toJSON()`` gives it."""

    endpoint: str = Field(min_length=1, max_length=MAX_ENDPOINT_LEN)
    keys: PushKeysIn
    label: str = Field(default="", max_length=200)


class PushDeviceOut(FrozenCamelModel, frozen=True):
    """One own device. The endpoint is the key by which the page finds this device."""

    id: uuid.UUID
    label: str
    endpoint: str
    created_at: datetime = Field(alias="createdAt")
    last_success_at: datetime | None = Field(alias="lastSuccessAt")


class PushPreferenceOut(FrozenCamelModel, frozen=True):
    """The push switch of one kind."""

    kind: str
    enabled: bool


class PushPreferencesIn(FrozenStrictCamelModel, frozen=True):
    """A bulk update of the own push switches."""

    preferences: tuple[PushPreferenceOut, ...] = Field(max_length=100)


async def _principal_id(db: DbSession, principal: Principal) -> uuid.UUID:
    from app.modules.auth.models import Principal as PrincipalRow

    found = await db.scalar(select(PrincipalRow.id).where(PrincipalRow.sub == principal.sub))
    if found is None:
        raise NotFoundError("principal not found")
    return found


def _device_out(row: PushSubscription) -> PushDeviceOut:
    return PushDeviceOut(
        id=row.id,
        label=row.label,
        endpoint=row.endpoint,
        createdAt=row.created_at,
        lastSuccessAt=row.last_success_at,
    )


@router.get("/key", response_model=PushKeyOut, responses=_AUTH_ERRORS)
async def get_push_key(
    db: DbSession, settings: SettingsDep, _principal: PrincipalDep
) -> PushKeyOut:
    """Read the public VAPID key; the first read makes the key pair (002505)."""
    keys = await PushService(db, settings).vapid_keys()
    await db.commit()
    return PushKeyOut(publicKey=keys.public_key)


@router.get("/devices", response_model=list[PushDeviceOut], responses=_AUTH_ERRORS)
async def list_push_devices(
    db: DbSession, settings: SettingsDep, principal: PrincipalDep
) -> list[PushDeviceOut]:
    """List the own devices with push, newest first."""
    rows = await PushService(db, settings).devices(await _principal_id(db, principal))
    return [_device_out(row) for row in rows]


@router.post(
    "/devices",
    response_model=PushDeviceOut,
    status_code=201,
    responses={**_AUTH_ERRORS, 422: _PROBLEM},
)
async def add_push_device(
    body: PushDeviceIn, db: DbSession, settings: SettingsDep, principal: PrincipalDep
) -> PushDeviceOut:
    """Store the subscription of this device; a known device takes the new keys.

    The endpoint must be an ``https`` URL of a known push service (002510).
    """
    row = await PushService(db, settings).subscribe(
        await _principal_id(db, principal),
        SubscriptionIn(
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
            label=body.label,
        ),
    )
    out = _device_out(row)
    await db.commit()
    return out


@router.delete("/devices/{device_id}", status_code=204, responses=_AUTH_ERRORS)
async def remove_push_device(
    device_id: uuid.UUID, db: DbSession, settings: SettingsDep, principal: PrincipalDep
) -> Response:
    """Remove one own device; a device of another person answers 404."""
    await PushService(db, settings).remove(await _principal_id(db, principal), device_id)
    await db.commit()
    return Response(status_code=204)


@router.get("/preferences", response_model=list[PushPreferenceOut], responses=_AUTH_ERRORS)
async def get_push_preferences(
    db: DbSession, settings: SettingsDep, principal: PrincipalDep
) -> list[PushPreferenceOut]:
    """Read the own push switch of every kind (002501, 002502)."""
    prefs = await PushService(db, settings).preferences(await _principal_id(db, principal))
    return [PushPreferenceOut(kind=k, enabled=e) for k, e in prefs]


@router.put(
    "/preferences",
    response_model=list[PushPreferenceOut],
    responses={**_AUTH_ERRORS, 422: _PROBLEM},
)
async def put_push_preferences(
    body: PushPreferencesIn, db: DbSession, settings: SettingsDep, principal: PrincipalDep
) -> list[PushPreferenceOut]:
    """Set the own push switches in bulk; only a deviation from the default is stored."""
    prefs = await PushService(db, settings).set_preferences(
        await _principal_id(db, principal), [(p.kind, p.enabled) for p in body.preferences]
    )
    await db.commit()
    return [PushPreferenceOut(kind=k, enabled=e) for k, e in prefs]
