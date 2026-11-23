"""Tables of the outgoing webhooks: ``webhook`` and ``webhook_delivery``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class Webhook(UUIDPkMixin, CreatedAtMixin, Base):
    """Outbound webhook config (`webhook.manage`).

    The server generates ``secret`` and never exposes it through the API. The
    worker signs the deliveries with it (HMAC).

    ``subscriptions`` is a list of ``{"event": <name>, "fields": [<key>, ...]}``: the
    events of the catalog that the webhook gets and, per event, the fields of its
    ``data`` object (§F/integrations/webhooks/002410, 002412). ``gremium_ids`` and
    ``type_ids`` (UUID strings) and ``state_keys`` (status keys of the target state of
    ``application.transition``) are the filters; an empty list lets every value pass
    (§F/integrations/webhooks/002414).
    """

    __tablename__ = "webhook"

    name: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    subscriptions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    gremium_ids: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    type_ids: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    state_keys: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")


class WebhookDelivery(UUIDPkMixin, CreatedAtMixin, Base):
    """Delivery attempt of a webhook.

    The body in ``payload`` is built when the event occurs and never changes after
    (§F/integrations/webhooks/002417). The worker cron ``enqueue_pending_webhooks``
    hands each new ``pending`` row without an attempt to its own arq job
    ``deliver_webhook`` with the job key ``webhook:<id>``, and a retry is the same
    job, deferred by ``arq.Retry`` with an exponential backoff.
    ``idempotency_key`` decouples the event instance from the dispatch. A flow
    retry of the same status event creates no second delivery, because
    ``(webhook_id, idempotency_key)`` is unique. A ``NULL`` key means no
    deduplication, for example for a manual delivery.
    """

    __tablename__ = "webhook_delivery"

    webhook_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhook.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_code: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','ok','failed','dead')",
            name="webhook_delivery_status",
        ),
        UniqueConstraint(
            "webhook_id",
            "idempotency_key",
            name="uq_webhook_delivery_idempotency",
        ),
    )
