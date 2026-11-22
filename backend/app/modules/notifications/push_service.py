"""Web push: device subscriptions, push switches, the VAPID key and the push jobs.

A push goes along with a mail of a notification kind (§F/collaboration/notifications/
002501): `NotificationService` calls `PushService.jobs` with the recipients of the event
before the mail filter, because the push switch and the mail switch do not change each
other. A recipient gets the push only when it is an active account with the push switch
of the kind on and at least one device. So the rule "only who can act" of the mail holds
for push too: the push reaches only addresses that the mail of the event resolved.

The service builds one job per device. The worker encrypts and sends it
(`worker/push.py`), so a failed device retries alone and a gone one (404/410) is deleted
alone (002506).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.kinds import NOTIFICATION_KINDS
from app.modules.notifications.push_kinds import (
    button_label,
    is_push_kind,
    push_default,
    push_title,
)
from app.modules.notifications.push_models import (
    PushPreference,
    PushSubscription,
    PushVapidKey,
)
from app.modules.notifications.push_tokens import PushActionClaim, PushActionKind, sign_action
from app.modules.notifications.webpush import VapidKeys, generate_vapid_keys
from app.modules.site_config.brand_images import has_icon_mark
from app.modules.site_config.features import Feature, feature_on
from app.modules.site_config.reads import active_branding
from app.settings import Settings
from app.shared.errors import NotFoundError, ValidationProblem

#: The hosts of the push services of the browsers (§F/collaboration/notifications/002510):
#: Chrome and Edge on Android (Google), Safari (Apple), Firefox (Mozilla), Edge on
#: Windows (Microsoft). A subdomain of one of them counts, because Apple and Microsoft
#: hand out endpoints on numbered subdomains.
PUSH_SERVICE_HOSTS: tuple[str, ...] = (
    "fcm.googleapis.com",
    "push.apple.com",
    "push.services.mozilla.com",
    "notify.windows.com",
)

#: The longest endpoint and key that a subscription may carry. Real ones stay far below.
MAX_ENDPOINT_LEN = 2048
MAX_KEY_LEN = 256
MAX_LABEL_LEN = 80

#: How long a push service keeps an undelivered push: one day, because a push about an
#: event that is older is noise.
PUSH_TTL_SECONDS = 24 * 3600

#: The kinds whose push the push service delivers at once even to a device that saves
#: power, because the person is asked to act now.
HIGH_URGENCY_KINDS: frozenset[str] = frozenset({"poll_started", "meeting", "mention"})

#: The built-in app icon of a push; a branding with a Bildmarke uses its own route.
DEFAULT_ICON = "/icons/icon-192x192.png"
BRANDED_ICON = "/api/branding/icons/icon-192x192.png"

#: A button of a push. ``open_poll`` opens a place, the others act in the background.
ButtonKey = Literal["open_poll", "appointment_accept", "appointment_decline", "todo_done"]

Urgency = Literal["normal", "high"]


@dataclass(frozen=True, slots=True)
class PushButton:
    """One button that a sender asks for: a place to open or an action on an element.

    ``url`` is the place of ``open_poll``. ``target_id`` is the element of an action.
    """

    key: ButtonKey
    url: str | None = None
    target_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class PushNote:
    """What one push says: kind, short line, language, link and buttons.

    ``tag`` groups pushes of one event, so a second push of it replaces the first on the
    device instead of stacking.
    """

    kind: str
    line: str
    lang: str
    url: str | None
    tag: str
    buttons: tuple[PushButton, ...] = ()


@dataclass(frozen=True, slots=True)
class PushJob:
    """One encrypted send to one device, as the worker gets it.

    ``payload`` is the JSON of the notification that the service worker shows.
    """

    subscription_id: str
    payload: str
    urgency: Urgency
    ttl: int
    job_id: str

    def to_payload(self) -> dict[str, object]:
        """Return the queue form."""
        return {
            "subscriptionId": self.subscription_id,
            "payload": self.payload,
            "urgency": self.urgency,
            "ttl": self.ttl,
        }

    @classmethod
    def from_payload(cls, data: dict[str, object]) -> PushJob:
        """Build the job from its queue form."""
        urgency: Urgency = "high" if data.get("urgency") == "high" else "normal"
        return cls(
            subscription_id=str(data["subscriptionId"]),
            payload=str(data["payload"]),
            urgency=urgency,
            ttl=int(str(data.get("ttl", PUSH_TTL_SECONDS))),
            job_id="",
        )


@dataclass(frozen=True, slots=True)
class SubscriptionIn:
    """A subscription as the browser hands it over."""

    endpoint: str
    p256dh: str
    auth: str
    label: str


def endpoint_allowed(endpoint: str) -> bool:
    """Return whether ``endpoint`` is an ``https`` URL on a known push service host."""
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(
        host == known or host.endswith(f".{known}") for known in PUSH_SERVICE_HOSTS
    )


def _check_subscription(sub: SubscriptionIn) -> None:
    errors = [
        *(
            [{"field": "endpoint", "msg": "not a known push service"}]
            if len(sub.endpoint) > MAX_ENDPOINT_LEN or not endpoint_allowed(sub.endpoint)
            else []
        ),
        *(
            [{"field": "keys", "msg": "invalid keys"}]
            if not (0 < len(sub.p256dh) <= MAX_KEY_LEN and 0 < len(sub.auth) <= MAX_KEY_LEN)
            else []
        ),
    ]
    if errors:
        raise ValidationProblem("Invalid push subscription.", errors=errors)


def _action_kind(key: ButtonKey) -> PushActionKind | None:
    match key:
        case "open_poll":
            return None
        case "appointment_accept" | "appointment_decline" | "todo_done":
            return key


def _button_entry(
    button: PushButton, *, base: str, secret: str, principal_id: uuid.UUID
) -> tuple[str, dict[str, str]] | None:
    """Return the ``onActionClick`` entry of one button, or None when it lacks its data.

    A background action is a ``sendRequest`` of the Angular service worker, which fetches
    the URL with a GET; the token in the path is the only right that the request carries.
    """
    action = _action_kind(button.key)
    match action:
        case None:
            return (
                (button.key, {"operation": "navigateLastFocusedOrOpen", "url": button.url})
                if button.url
                else None
            )
        case _ if button.target_id is None:
            return None
        case _:
            token = sign_action(
                secret,
                PushActionClaim(
                    principal_id=principal_id, action=action, target_id=button.target_id
                ),
            )
            return (
                button.key,
                {"operation": "sendRequest", "url": f"{base}/api/push/actions/{token}"},
            )


def notification_payload(
    note: PushNote, *, title: str, icon: str, base: str, secret: str, principal_id: uuid.UUID
) -> dict[str, Any]:
    """Return the payload that the Angular service worker shows (``notification`` key).

    A tap on the push opens its link in the open app or in a new window. At most two
    buttons go along (002508), because Android shows no more.
    """
    entries = [
        entry
        for entry in (
            _button_entry(b, base=base, secret=secret, principal_id=principal_id)
            for b in note.buttons[:2]
        )
        if entry is not None
    ]
    default = (
        {"default": {"operation": "navigateLastFocusedOrOpen", "url": note.url}} if note.url else {}
    )
    return {
        "notification": {
            "title": title,
            "body": note.line,
            "icon": icon,
            "lang": note.lang,
            "tag": note.tag,
            "actions": [
                {"action": key, "title": button_label(key, note.lang)} for key, _ in entries
            ],
            "data": {"onActionClick": {**default, **dict(entries)}},
        }
    }


@dataclass(frozen=True, slots=True)
class PushService:
    """Web push operations bound to an ``AsyncSession``. The routers commit."""

    session: AsyncSession
    settings: Settings

    async def enabled(self) -> bool:
        """Return whether the feature push is on (002504)."""
        return await feature_on(self.session, Feature.PUSH)

    async def vapid_keys(self) -> VapidKeys:
        """Return the VAPID key pair; make and store it at the first need (002505).

        Two first calls at once both insert, and ``ON CONFLICT DO NOTHING`` keeps the
        first, so every caller reads the same stored pair and no pair is ever replaced.
        """
        stored = await self.session.get(PushVapidKey, 1)
        row = stored if stored is not None else await self._create_key()
        return VapidKeys(private_pem=row.private_pem, public_key=row.public_key)

    async def _create_key(self) -> PushVapidKey:
        fresh = generate_vapid_keys()
        await self.session.execute(
            insert(PushVapidKey)
            .values(id=1, private_pem=fresh.private_pem, public_key=fresh.public_key)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await self.session.flush()
        row = await self.session.get(PushVapidKey, 1, populate_existing=True)
        if row is None:  # pragma: no cover — the insert above guarantees the row
            raise NotFoundError("push key missing")
        return row

    async def subscribe(self, principal_id: uuid.UUID, sub: SubscriptionIn) -> PushSubscription:
        """Store the device of a person; a known endpoint moves to this person with new keys.

        A browser has one subscription per origin, so a second account on the same
        device takes the device over; the first account no longer pushes there.
        """
        _check_subscription(sub)
        label = sub.label.strip()[:MAX_LABEL_LEN]
        await self.session.execute(
            insert(PushSubscription)
            .values(
                principal_id=principal_id,
                endpoint=sub.endpoint,
                p256dh=sub.p256dh,
                auth=sub.auth,
                label=label,
            )
            .on_conflict_do_update(
                index_elements=["endpoint"],
                set_={
                    "principal_id": principal_id,
                    "p256dh": sub.p256dh,
                    "auth": sub.auth,
                    "label": label,
                },
            )
        )
        await self.session.flush()
        return (
            await self.session.scalars(
                select(PushSubscription)
                .where(PushSubscription.endpoint == sub.endpoint)
                .execution_options(populate_existing=True)
            )
        ).one()

    async def devices(self, principal_id: uuid.UUID) -> Sequence[PushSubscription]:
        """Return the devices of a person, newest first."""
        return (
            await self.session.scalars(
                select(PushSubscription)
                .where(PushSubscription.principal_id == principal_id)
                .order_by(PushSubscription.created_at.desc(), PushSubscription.id)
            )
        ).all()

    async def remove(self, principal_id: uuid.UUID, device_id: uuid.UUID) -> None:
        """Delete one device of a person.

        Raises:
            NotFoundError: The device is unknown or belongs to another person.
        """
        row = await self.session.get(PushSubscription, device_id)
        if row is None or row.principal_id != principal_id:
            raise NotFoundError("push device not found")
        await self.session.delete(row)

    async def preferences(self, principal_id: uuid.UUID) -> list[tuple[str, bool]]:
        """Return the effective push switch of every kind (stored deviation or default)."""
        stored: dict[str, bool] = dict(
            (
                await self.session.execute(
                    select(PushPreference.kind, PushPreference.enabled).where(
                        PushPreference.principal_id == principal_id
                    )
                )
            ).tuples()
        )
        return [(k, stored.get(k, push_default(k))) for k in NOTIFICATION_KINDS]

    async def set_preferences(
        self, principal_id: uuid.UUID, items: Iterable[tuple[str, bool]]
    ) -> list[tuple[str, bool]]:
        """Store the push switches; only a deviation from the default keeps a row.

        Raises:
            ValidationProblem: A kind is not in the catalogue.
        """
        wanted = tuple(items)
        unknown = sorted({k for k, _ in wanted if not is_push_kind(k)})
        if unknown:
            raise ValidationProblem(
                "Unknown notification kinds.",
                errors=[{"field": "preferences", "msg": f"unknown: {unknown}"}],
            )
        for kind, enabled in wanted:
            await self.session.execute(
                delete(PushPreference).where(
                    PushPreference.principal_id == principal_id, PushPreference.kind == kind
                )
            )
            if enabled != push_default(kind):
                self.session.add(
                    PushPreference(principal_id=principal_id, kind=kind, enabled=enabled)
                )
        await self.session.flush()
        return await self.preferences(principal_id)

    async def _receivers(
        self, recipients: Sequence[str], kind: str
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        """Return ``(principal id, device id)`` of every device that gets this push.

        The person is an active account with an address among ``recipients``, and the
        push switch of ``kind`` is on: a stored ``true`` row, or no row and a default on.
        """
        from app.modules.auth.models import Principal as PrincipalRow

        rows = (
            await self.session.execute(
                select(PrincipalRow.id, PushSubscription.id, PushPreference.enabled)
                .join(PushSubscription, PushSubscription.principal_id == PrincipalRow.id)
                .outerjoin(
                    PushPreference,
                    (PushPreference.principal_id == PrincipalRow.id)
                    & (PushPreference.kind == kind),
                )
                .where(
                    PrincipalRow.email.in_(list(recipients)),
                    PrincipalRow.active.is_(True),
                    PrincipalRow.merged_into.is_(None),
                )
                .order_by(PrincipalRow.id, PushSubscription.id)
            )
        ).tuples()
        return [
            (person, device)
            for person, device, enabled in rows
            if (enabled if enabled is not None else push_default(kind))
        ]

    async def has_receivers(self, recipients: Sequence[str], kind: str) -> bool:
        """Return whether a push of ``kind`` reaches a device of one of ``recipients``."""
        return (
            bool(recipients)
            and is_push_kind(kind)
            and await self.enabled()
            and bool(await self._receivers(recipients, kind))
        )

    async def _icon(self) -> str:
        return BRANDED_ICON if has_icon_mark(await active_branding(self.session)) else DEFAULT_ICON

    async def jobs(
        self, note: PushNote, recipients: Sequence[str], *, fallback_title: str
    ) -> list[PushJob]:
        """Return one push job per device that gets ``note``; none while push is off.

        ``recipients`` are the addresses that the mail of the event resolved, before
        the mail switch. ``fallback_title`` names the platform for a kind without a
        push title.
        """
        if not recipients or not is_push_kind(note.kind) or not await self.enabled():
            return []
        receivers = await self._receivers(recipients, note.kind)
        if not receivers:
            return []
        icon = await self._icon()
        base = self.settings.public_base_url.rstrip("/")
        title = push_title(note.kind, note.lang, fallback_title)
        urgency: Urgency = "high" if note.kind in HIGH_URGENCY_KINDS else "normal"
        return [
            PushJob(
                subscription_id=str(device),
                payload=json.dumps(
                    notification_payload(
                        note,
                        title=title,
                        icon=icon,
                        base=base,
                        secret=self.settings.session_secret,
                        principal_id=person,
                    ),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                urgency=urgency,
                ttl=PUSH_TTL_SECONDS,
                job_id=f"push:{note.tag}:{device}",
            )
            for person, device in receivers
        ]
