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
    """Map the DB status and the HTTP code to a coarse failure bucket.

    The bucket stays coarse on purpose and shows no host or IP detail. A
    ``response_code`` of ``None`` on ``dead`` means an SSRF block at send time
    or a transport error such as DNS, connect or timeout. Both map to
    ``unreachable_or_blocked``, which hides the blocked IP.
    """
    if status == "ok":
        return "delivered"
    if status == "pending":
        return "in_progress"
    if response_code is None:
        # No HTTP response points to a transport, DNS or SSRF problem. The status
        # failed still retries, the status dead does not.
        return "transient_transport_error" if status == "failed" else "unreachable_or_blocked"
    if 400 <= response_code < 500:
        return "rejected_by_target"
    if response_code >= 500:
        return "target_server_error"
    return "unknown"


def _delivery_status_out(
    webhook_id: UUID, row: WebhookDelivery | None
) -> WebhookDeliveryStatusOut:
    """Reduce the latest delivery to a coarse view without IP or body detail."""
    if row is None:
        return WebhookDeliveryStatusOut(
            webhook_id=webhook_id,
            last_state="never",
            reason_class="no_deliveries",
        )
    # The four DB states pending, ok, failed and dead map to three admin states.
    if row.status == "ok":
        last_state = "sent"
    elif row.status == "dead":
        last_state = "dead"
    else:  # pending, or failed with a retry in progress
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
        """Check the webhook URL against the SSRF guard at save time.

        The send-time guard in the worker stays authoritative. That guard
        resolves all A and AAAA records, blocks non-global targets and pins the
        IP.

        This advisory check rejects a clearly internal or invalid target with
        400. Such a target has a bad scheme, a missing host or an allowlist
        violation. An IP literal counts too, as does a host that resolves to a
        non-global IP at save time. Without the check the platform would write
        one dead-letter row per event.

        The check is best effort. A transient DNS failure does not block the
        save, because the runtime guard covers that case. This keeps the
        advisory free of false positives.

        Raises:
            BadRequestError: The target is not a permitted external URL.
        """
        allowlist = get_settings().webhook_host_allowlist
        try:
            assert_allowed_url(url, allowlist=allowlist)
        except SsrfError as exc:
            msg = str(exc)
            # A transient DNS failure must not block the save. The runtime guard applies.
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

    async def delete_webhook(self, webhook_id: UUID, actor: str) -> None:
        """Delete a webhook and its delivery history.

        The ``webhook_delivery`` rows cascade, so the delete needs no guard.

        Raises:
            NotFoundError: No webhook has this id (404).
        """
        row = await self.session.get(Webhook, webhook_id)
        if row is None:
            raise NotFoundError(f"webhook {webhook_id} not found")
        await self._audit(actor, AuditAction.WEBHOOK_CONFIG, "webhook", webhook_id)
        await self.session.delete(row)
        await self.session.commit()

    async def list_webhook_delivery_status(self) -> list[WebhookDeliveryStatusOut]:
        """Report the latest delivery state per webhook.

        The method reads the most recent ``webhook_delivery`` of each webhook.
        It orders by ``last_at`` and falls back to insert order. It then reduces
        the row to a coarse state plus a coarse failure class.

        The result shows no resolved IP or host topology and no response body.
        It shows only the state class, the HTTP status code and the attempt
        count. A webhook without any delivery yields ``never``.
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
