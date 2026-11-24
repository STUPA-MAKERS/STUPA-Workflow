"""Tables of web push: the device subscriptions, the push switches and the VAPID key.

`push_subscription` holds one row per device of a person (§F/collaboration/
notifications/002500). The endpoint is unique, because a browser has one subscription
per origin; a second subscribe of the same device replaces the keys of the row.

`push_preference` stores the push switch of one notification kind, only where it
differs from the push default (`push_kinds.push_default`), the way
`notification_preference` does for mail. The two tables never change each other
(002501).

`push_vapid_key` is a single row with the VAPID key pair that the platform makes at the
first need and never replaces (002505). It lives in the database, so a restore brings
it back with the subscriptions that depend on it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.shared.sealed import Sealed


class PushSubscription(UUIDPkMixin, CreatedAtMixin, Base):
    """One device of a person that receives web push.

    Attributes:
        endpoint: The URL of the push service for this device.
        p256dh: The public key of the subscription, base64url.
        auth: The auth secret of the subscription, base64url.
        label: A short device name from the user agent, for the device list.
        last_success_at: The time of the last push that the push service took.
    """

    __tablename__ = "push_subscription"

    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text, server_default="")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PushPreference(Base):
    """The push switch of one notification kind where it differs from the default."""

    __tablename__ = "push_preference"

    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")


class PushVapidKey(CreatedAtMixin, Base):
    """The VAPID key pair of the platform (single row)."""

    __tablename__ = "push_vapid_key"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    private_pem: Mapped[str] = mapped_column(Sealed("push_vapid_key.private_pem"))
    public_key: Mapped[str] = mapped_column(Text)

    __table_args__ = (CheckConstraint("id = 1", name="push_vapid_key_singleton"),)
