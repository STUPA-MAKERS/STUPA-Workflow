"""Webhook-Dispatch-Service (T-19, flows §8 / security.md §5).

Zwei Aufgaben, strikt getrennt:

* :meth:`WebhookService.dispatch_event` (API-/Flow-Seite) — zu einem Domain-Event die
  **aktiven, abonnierten** Webhooks finden, je Webhook eine ``webhook_delivery``
  (``pending``) anlegen und einen ``deliver_webhook``-Job enqueuen. Idempotent über
  ``(webhook_id, idempotency_key)``: ein Flow-Retry desselben Status-Events legt keine
  Doppel-Delivery an.
* :meth:`WebhookService.deliver` (Worker-Seite) — eine Delivery zustellen: SSRF-Guard
  zur Sende-Zeit, HMAC-Signatur, POST ohne Redirects, Status/Versuche/Backoff
  zurückschreiben. Liefert ein :class:`DeliveryOutcome`; der Worker übersetzt
  ``retry`` in ``arq.Retry``.

Das pro-Webhook-``secret`` wird **nie** geloggt.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.admin.models import Webhook, WebhookDelivery
from app.modules.webhooks.signing import build_headers, canonical_body
from app.modules.webhooks.ssrf import (
    Resolver,
    SsrfError,
    assert_allowed_url,
    default_resolver,
    pin_url,
)

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.webhooks.queue import WebhookQueue
    from app.settings import Settings

logger = logging.getLogger("app.webhooks")

OutcomeKind = Literal["ok", "retry", "dead", "gone"]

# Wir verwerten ausschließlich den HTTP-**Statuscode**; der Response-Body interessiert
# nie. Ein bösartiger/kompromittierter Empfänger könnte mit einem Multi-GB-Body den
# (geteilten) arq-Worker per OOM töten — darum den Body **gestreamt** lesen und nach
# diesem harten Limit abbrechen (security.md §5).
_MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """Ergebnis eines Zustellversuchs. ``defer`` = Backoff-Sekunden bei ``retry``."""

    kind: OutcomeKind
    attempts: int = 0
    response_code: int | None = None
    defer: int | None = None


@dataclass(slots=True)
class WebhookService:
    session: AsyncSession
    settings: Settings
    queue: WebhookQueue | None = None

    # ----------------------------------------------------------- dispatch #
    async def dispatch_event(
        self,
        event: str,
        *,
        payload: dict[str, object] | None = None,
        idempotency_base: str | None = None,
    ) -> int:
        """Aktive, auf ``event`` abonnierte Webhooks → je eine Delivery + Job.

        Gibt die Anzahl **neu** angelegter Deliveries zurück (Dedup übersprungene
        zählen nicht)."""
        webhooks = (
            await self.session.scalars(
                select(Webhook).where(
                    Webhook.active.is_(True), Webhook.events.contains([event])
                )
            )
        ).all()
        if not webhooks:
            return 0

        existing = await self._existing_keys(event, idempotency_base)
        body = dict(payload or {})
        created: list[WebhookDelivery] = []
        for hook in webhooks:
            key = f"{idempotency_base}:{hook.id}" if idempotency_base else None
            if key is not None and key in existing:
                logger.info("webhook delivery deduped (event=%s hook=%s)", event, hook.id)
                continue
            delivery = WebhookDelivery(
                webhook_id=hook.id,
                event=event,
                payload=body,
                status="pending",
                attempts=0,
                idempotency_key=key,
            )
            # Savepoint je Delivery: bei nebenläufigem Insert verletzt das
            # unique(webhook_id, idempotency_key) — dann ist die Delivery bereits von
            # einem anderen Lauf angelegt (= schon enqueued), also überspringen statt
            # den ganzen Batch zu verlieren.
            try:
                async with self.session.begin_nested():
                    self.session.add(delivery)
                    await self.session.flush()
            except IntegrityError:
                logger.info(
                    "webhook delivery race-deduped (event=%s hook=%s)", event, hook.id
                )
                continue
            created.append(delivery)

        if not created:
            return 0
        await self.session.commit()

        if self.queue is None:
            logger.info(
                "webhook queue unavailable — %d delivery(ies) stay pending (event=%s)",
                len(created),
                event,
            )
        else:
            for delivery in created:
                await self.queue.enqueue(delivery.id)
        return len(created)

    async def dispatch_to_webhook(
        self,
        webhook_id: UUID,
        *,
        event: str,
        payload: dict[str, object] | None = None,
        idempotency_base: str | None = None,
    ) -> int:
        """Eine Delivery an **genau einen** (aktiven) Webhook anlegen + enqueuen (#28).

        Flow-Action ``webhook`` referenziert einen unter ``/admin/webhooks`` gepflegten
        Webhook per Id. Fehlt/inaktiv ⇒ ``0`` (still übersprungen). Dedup über
        ``(webhook_id, idempotency_key)``."""
        hook = await self.session.get(Webhook, webhook_id)
        if hook is None or not hook.active:
            logger.warning(
                "webhook %s missing/inactive — flow action skipped", webhook_id
            )
            return 0
        key = f"{idempotency_base}:{hook.id}" if idempotency_base else None
        if key is not None and key in await self._existing_keys(event, idempotency_base):
            logger.info("webhook delivery deduped (event=%s hook=%s)", event, hook.id)
            return 0
        delivery = WebhookDelivery(
            webhook_id=hook.id,
            event=event,
            payload=dict(payload or {}),
            status="pending",
            attempts=0,
            idempotency_key=key,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(delivery)
                await self.session.flush()
        except IntegrityError:
            logger.info("webhook delivery race-deduped (event=%s hook=%s)", event, hook.id)
            return 0
        await self.session.commit()
        if self.queue is not None:
            await self.queue.enqueue(delivery.id)
        return 1

    async def _existing_keys(self, event: str, base: str | None) -> set[str]:
        """Bereits vergebene Idempotenz-Keys für dieses Event (Dedup-Vorprüfung)."""
        if base is None:
            return set()
        rows = (
            await self.session.scalars(
                select(WebhookDelivery.idempotency_key).where(
                    WebhookDelivery.event == event,
                    WebhookDelivery.idempotency_key.is_not(None),
                )
            )
        ).all()
        return {k for k in rows if k is not None}

    # ------------------------------------------------------------- deliver #
    async def deliver(
        self,
        delivery_id: UUID,
        *,
        http_client: httpx.AsyncClient,
        resolver: Resolver = default_resolver,
        now: dt.datetime | None = None,
    ) -> DeliveryOutcome:
        """Eine Delivery zustellen + Status persistieren (Worker)."""
        import httpx

        moment = now or dt.datetime.now(tz=dt.UTC)
        delivery = await self.session.get(WebhookDelivery, delivery_id)
        if delivery is None:
            logger.info("webhook delivery %s gone — skipped", delivery_id)
            return DeliveryOutcome(kind="gone")

        hook = await self.session.get(Webhook, delivery.webhook_id)
        if hook is None or not hook.active or hook.secret is None:
            return await self._finish(
                delivery, "dead", moment, response_code=None
            )

        try:
            ips = assert_allowed_url(
                hook.url,
                allowlist=self.settings.webhook_host_allowlist,
                resolver=resolver,
            )
        except SsrfError:
            # Sicherheits-Block ist **permanent** — kein Retry (Ziel ändert sich nicht).
            # Bewusst ohne Fehlerdetail: die Meldung enthält Host/aufgelöste IP und
            # würde interne Netz-Topologie in die Logs tragen.
            logger.warning(
                "webhook delivery %s (webhook=%s) blocked by ssrf guard",
                delivery_id,
                delivery.webhook_id,
            )
            return await self._finish(delivery, "dead", moment, response_code=None)

        # DNS-Rebinding-Pinning: an die **validierte** IP connecten (kein erneutes
        # Auflösen durch den Client), Host/TLS-SNI bleibt der Original-Host.
        ip_url, host_header = pin_url(hook.url, ips[0])
        body = canonical_body(delivery.payload)
        headers = build_headers(
            hook.secret, body, event=delivery.event, timestamp=int(moment.timestamp())
        )
        headers["Host"] = host_header
        request = http_client.build_request("POST", ip_url, content=body, headers=headers)
        request.extensions["sni_hostname"] = host_header.rsplit(":", 1)[0]
        try:
            status_code = await self._send_capped(http_client, request)
        except httpx.HTTPError as exc:
            logger.warning(
                "webhook delivery %s transport error: %s",
                delivery_id,
                type(exc).__name__,
            )
            return await self._fail(delivery, moment, response_code=None)
        return await self._classify(delivery, moment, status_code, delivery_id)

    async def _send_capped(
        self, http_client: httpx.AsyncClient, request: httpx.Request
    ) -> int:
        """POST senden + nur den **Statuscode** zurückgeben — Body gestreamt und auf
        :data:`_MAX_RESPONSE_BYTES` gedeckelt lesen (OOM-Schutz, security.md §5).

        Der Body wird nie verwertet; wir lesen ihn nur so weit, bis das Limit erreicht
        ist, und schließen dann den Stream. Verbindungs-Reuse bleibt durch das saubere
        ``aclose`` (über den Context-Manager) intakt."""
        response = await http_client.send(request, stream=True)
        try:
            read = 0
            async for chunk in response.aiter_bytes():
                read += len(chunk)
                if read >= _MAX_RESPONSE_BYTES:
                    # Body zu groß: weiteres Lesen abbrechen — der Statuscode steht fest.
                    break
            return response.status_code
        finally:
            await response.aclose()

    async def _classify(
        self,
        delivery: WebhookDelivery,
        moment: dt.datetime,
        status_code: int,
        delivery_id: UUID,
    ) -> DeliveryOutcome:
        """Statuscode → Endzustand/Retry (Spec, unverändert zur vorigen Inline-Logik)."""
        if 200 <= status_code < 300:
            return await self._finish(
                delivery, "ok", moment, response_code=status_code
            )
        if 400 <= status_code < 500:
            # 4xx ist ein Client-/Config-Fehler — Wiederholung ändert nichts →
            # sofort Dead-Letter, kein Retry (Spec).
            logger.warning(
                "webhook delivery %s dead — non-retryable %s",
                delivery_id,
                status_code,
            )
            return await self._finish(
                delivery, "dead", moment, response_code=status_code,
                attempts=delivery.attempts + 1,
            )
        return await self._fail(delivery, moment, response_code=status_code)

    async def _fail(
        self, delivery: WebhookDelivery, moment: dt.datetime, *, response_code: int | None
    ) -> DeliveryOutcome:
        """Fehlversuch verbuchen: Retry mit Backoff oder Dead-Letter bei Erschöpfung."""
        attempts = delivery.attempts + 1
        if attempts >= self.settings.webhook_max_tries:
            return await self._finish(
                delivery, "dead", moment, response_code=response_code, attempts=attempts
            )
        defer = self.settings.webhook_retry_backoff_seconds * (2 ** (attempts - 1))
        next_at = moment + dt.timedelta(seconds=defer)
        delivery.attempts = attempts
        delivery.status = "failed"
        delivery.last_at = moment
        delivery.next_at = next_at
        delivery.response_code = response_code
        await self.session.commit()
        return DeliveryOutcome(
            kind="retry", attempts=attempts, response_code=response_code, defer=defer
        )

    async def _finish(
        self,
        delivery: WebhookDelivery,
        kind: Literal["ok", "dead"],
        moment: dt.datetime,
        *,
        response_code: int | None,
        attempts: int | None = None,
    ) -> DeliveryOutcome:
        """Endzustand schreiben (``ok``/``dead``) — kein weiterer Versuch."""
        final_attempts = attempts if attempts is not None else delivery.attempts
        delivery.attempts = final_attempts
        delivery.status = kind
        delivery.last_at = moment
        delivery.next_at = None
        delivery.response_code = response_code
        await self.session.commit()
        return DeliveryOutcome(
            kind=kind, attempts=final_attempts, response_code=response_code
        )
