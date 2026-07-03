"""Webhook admin CRUD plus coarse per-webhook delivery diagnostics."""

from __future__ import annotations

import secrets
from typing import cast
from uuid import UUID

from sqlalchemy import select

from app.modules.admin.models import Webhook, WebhookDelivery
from app.modules.admin.schemas import (
    WebhookCreate,
    WebhookDeliveryStatusOut,
    WebhookOut,
    WebhookUpdate,
)
from app.modules.admin.service.service_base import ConfigServiceBase, _iso
from app.modules.audit.actions import AuditAction
from app.modules.webhooks.ssrf import SsrfError, assert_allowed_url
from app.settings import get_settings
from app.shared.config_schemas import EventName
from app.shared.errors import BadRequestError, NotFoundError


def _webhook_out(row: Webhook) -> WebhookOut:
    return WebhookOut(
        id=row.id,
        name=row.name,
        url=row.url,
        events=cast("list[EventName]", list(row.events)),
        active=row.active,
    )


def _delivery_reason_class(status: str, response_code: int | None) -> str:
    """Coarse failure bucket from DB status + HTTP code.

    Deliberately coarse and without host/IP detail. ``response_code is None``
    on ``dead`` means either an SSRF block at send time or a transport error
    (DNS/connect/timeout) — both reported as ``unreachable_or_blocked`` without
    revealing which IP was blocked.
    """
    if status == "ok":
        return "delivered"
    if status == "pending":
        return "in_progress"
    if response_code is None:
        # failed (retry running) or dead without HTTP response: transport/DNS/SSRF.
        return "transient_transport_error" if status == "failed" else "unreachable_or_blocked"
    if 400 <= response_code < 500:
        return "rejected_by_target"
    if response_code >= 500:
        return "target_server_error"
    return "unknown"


def _delivery_status_out(
    webhook_id: UUID, row: WebhookDelivery | None
) -> WebhookDeliveryStatusOut:
    """Latest delivery → coarse diagnostic view (no IP/body leak)."""
    if row is None:
        return WebhookDeliveryStatusOut(
            webhook_id=webhook_id,
            last_state="never",
            reason_class="no_deliveries",
        )
    # DB status (pending/ok/failed/dead) → admin-facing triad.
    if row.status == "ok":
        last_state = "sent"
    elif row.status == "dead":
        last_state = "dead"
    else:  # pending | failed (retry in progress)
        last_state = "pending"
    return WebhookDeliveryStatusOut(
        webhook_id=webhook_id,
        last_state=last_state,
        reason_class=_delivery_reason_class(row.status, row.response_code),
        response_code=row.response_code,
        attempts=row.attempts,
        last_at=_iso(row.last_at),
    )


class WebhookOps(ConfigServiceBase):
    """Webhook CRUD and delivery-status diagnostics."""

    async def list_webhooks(self) -> list[WebhookOut]:
        rows = (
            await self.session.scalars(select(Webhook).order_by(Webhook.name))
        ).all()
        return [_webhook_out(r) for r in rows]

    @staticmethod
    def _assert_webhook_url_advisory(url: str) -> None:
        """Save-time advisory check against the SSRF guard.

        The authoritative check remains the send-time guard in the worker
        (resolves all A/AAAA records, blocks non-global targets, pins the IP).
        An obviously internal/invalid target (bad scheme, missing host,
        allowlist violation, IP literal, or a host resolving to a non-global IP
        at save time) is rejected with 400 instead of silently producing a
        dead-letter row per event.

        Best-effort: a transient DNS failure does not block saving — the
        runtime guard covers that, keeping the advisory free of false
        positives.
        """
        allowlist = get_settings().webhook_host_allowlist
        try:
            assert_allowed_url(url, allowlist=allowlist)
        except SsrfError as exc:
            msg = str(exc)
            # Transient DNS failure → do not block (runtime guard applies).
            if msg.startswith("dns resolution failed"):
                return
            raise BadRequestError(
                f"Webhook target is not a permitted external URL: {msg}",
                title="Invalid webhook URL",
            ) from exc

    async def create_webhook(self, payload: WebhookCreate, actor: str) -> WebhookOut:
        self._assert_webhook_url_advisory(payload.url)
        row = Webhook(
            name=payload.name,
            url=payload.url,
            events=list(payload.events),
            active=payload.active,
            secret=secrets.token_bytes(32),
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, AuditAction.WEBHOOK_CONFIG, "webhook", row.id)
        await self.session.commit()
        return _webhook_out(row)

    async def update_webhook(
        self, webhook_id: UUID, payload: WebhookUpdate, actor: str
    ) -> WebhookOut:
        row = await self.session.get(Webhook, webhook_id)
        if row is None:
            raise NotFoundError(f"webhook {webhook_id} not found")
        if payload.name is not None:
            row.name = payload.name
        if payload.url is not None:
            self._assert_webhook_url_advisory(payload.url)
            row.url = payload.url
        if payload.events is not None:
            row.events = list(payload.events)
        if payload.active is not None:
            row.active = payload.active
        await self._audit(actor, AuditAction.WEBHOOK_CONFIG, "webhook", row.id)
        await self.session.commit()
        return _webhook_out(row)

    async def list_webhook_delivery_status(self) -> list[WebhookDeliveryStatusOut]:
        """Latest delivery state per webhook (diagnostics).

        Reduces each webhook's most recent ``webhook_delivery`` (by ``last_at``,
        falling back to insert order) to a coarse state plus a coarse failure
        class. Leaks no resolved IP/host topology and no response body — only
        state class, HTTP status code and attempt count. Webhooks without any
        delivery yield ``never``.
        """
        webhooks = (
            await self.session.scalars(select(Webhook).order_by(Webhook.name))
        ).all()
        out: list[WebhookDeliveryStatusOut] = []
        for hook in webhooks:
            latest = await self.session.scalar(
                select(WebhookDelivery)
                .where(WebhookDelivery.webhook_id == hook.id)
                .order_by(
                    WebhookDelivery.last_at.desc().nullslast(),
                    WebhookDelivery.id.desc(),
                )
                .limit(1)
            )
            out.append(_delivery_status_out(hook.id, latest))
        return out
