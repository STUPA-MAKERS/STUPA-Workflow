"""The webhook fields of an Antrag and the emit of its events.

`emit_application_event` hands an event of an Antrag to the webhooks
(§F/integrations/webhooks/002410). The field values come from `application_fields`, which
reads them in the transaction of the event (§F/integrations/webhooks/002417). The keys
follow the catalog in `app.modules.webhooks.catalog`. A personal field of an anonymized
Antrag is `None`, because the anonymization empties the applicant row
(§F/integrations/webhooks/002413).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from app.modules.application_types.models import ApplicationType
from app.modules.applications.models import Applicant, Application
from app.modules.flow.models import State
from app.modules.gremien.models import Gremium
from app.modules.webhooks.events import WebhookEvent, emit_event
from app.settings import get_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.webhooks.catalog import WebhookEventName


def label_of(i18n: Mapping[str, Any] | None, fallback: str) -> str:
    """Return the German label of an i18n map, else the first one, else `fallback`."""
    values = dict(i18n or {})
    value = values.get("de") or next(iter(values.values()), None)
    return value if isinstance(value, str) and value else fallback


def ref(row_id: UUID | None, name: str | None) -> dict[str, str] | None:
    """Return a reference object of the payload, or None without an id."""
    return None if row_id is None else {"id": str(row_id), "name": name or ""}


def money(value: Decimal | None) -> str | None:
    """Return an amount as a decimal string with two places, or None."""
    return None if value is None else f"{value:.2f}"


def link(path: str) -> str:
    """Return the absolute link of a path in the platform."""
    return get_settings().public_base_url.rstrip("/") + path


async def _state_ref(session: AsyncSession, state_id: UUID | None) -> dict[str, str] | None:
    state = None if state_id is None else await session.get(State, state_id)
    return None if state is None else ref(state.id, label_of(state.label_i18n, state.key))


async def application_fields(session: AsyncSession, app: Application) -> dict[str, Any]:
    """Return every catalog field of an Antrag event."""
    app_type = await session.get(ApplicationType, app.type_id)
    gremium = None if app.gremium_id is None else await session.get(Gremium, app.gremium_id)
    applicant = await session.scalar(
        select(Applicant).where(Applicant.application_id == app.id).limit(1)
    )
    title = (app.data or {}).get("title")
    return {
        "title": title.strip() if isinstance(title, str) else None,
        "type": None
        if app_type is None
        else ref(app_type.id, label_of(app_type.name_i18n, app_type.key)),
        "gremium": None if gremium is None else ref(gremium.id, gremium.name),
        "status": await _state_ref(session, app.current_state_id),
        "amount": money(app.amount),
        "currency": app.currency,
        "approvedAmount": money(app.approved_amount),
        "url": link(f"/applications/{app.id}"),
        "applicantName": None if applicant is None else applicant.name,
        "applicantEmail": None if applicant is None else applicant.email,
        "answers": dict(app.data or {}),
    }


async def emit_application_event(
    session: AsyncSession,
    name: WebhookEventName,
    app: Application,
    *,
    ids: Mapping[str, UUID | None] | None = None,
    extra: Mapping[str, Any] | None = None,
    state_key: str | None = None,
) -> int:
    """Emit an Antrag event with the fields of the Antrag plus `extra`.

    Returns:
        The number of new deliveries.
    """

    async def fields() -> Mapping[str, Any]:
        return {**await application_fields(session, app), **(extra or {})}

    return await emit_event(
        session,
        WebhookEvent(
            name=name,
            ids={"applicationId": app.id, **(ids or {})},
            fields=fields,
            gremium_id=app.gremium_id,
            type_id=app.type_id,
            state_key=state_key,
        ),
    )


async def emit_transition_event(
    session: AsyncSession,
    app: Application,
    *,
    transition_id: UUID,
    status_event_id: UUID,
    from_state_id: UUID | None,
    to_state: State | None,
    note: str | None,
) -> int:
    """Emit `application.transition` for a status change through a transition.

    The ORM row of the Antrag still holds the old state, because the flow moves it with a
    guarded `UPDATE`. So `status` and `toStatus` come from `to_state`. The filter of the
    target status reads the key of `to_state` (§F/integrations/webhooks/002414).

    Returns:
        The number of new deliveries.
    """
    to_ref = (
        None if to_state is None else ref(to_state.id, label_of(to_state.label_i18n, to_state.key))
    )
    return await emit_application_event(
        session,
        "application.transition",
        app,
        ids={"transitionId": transition_id, "statusEventId": status_event_id},
        extra={
            "status": to_ref,
            "fromStatus": await _state_ref(session, from_state_id),
            "toStatus": to_ref,
            "note": note,
        },
        state_key=None if to_state is None else to_state.key,
    )
