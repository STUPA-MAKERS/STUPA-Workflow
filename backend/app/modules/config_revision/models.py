"""``config_revision``: an append-only snapshot chain of the versioned configs.

As for ``audit_entry``, a database trigger rejects UPDATE, DELETE and TRUNCATE. See
migration 0034 and the ``audit_writer`` grant. Nothing can delete an earlier version.
``snapshot`` holds the full restorable config in its natural form. It holds config
only and never principal PII, which keeps GDPR erasure intact. ``version`` counts up
per entity. ``prev_revision_id`` chains the states.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ConfigRevision(Base):
    __tablename__ = "config_revision"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    # 'form' | 'flow' | 'site_config'.
    entity_type: Mapped[str] = mapped_column(Text)
    # UUID string (form: application_type_id) or 'global' (flow/site_config).
    entity_id: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Predecessor snapshot of the same entity (NULL = first state).
    prev_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("config_revision.id", ondelete="RESTRICT"), nullable=True
    )
    # OIDC ``sub`` of the actor that caused the change (no PII).
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "version",
            name="uq_config_revision_entity_version",
        ),
        Index(
            "ix_config_revision_entity",
            "entity_type",
            "entity_id",
            "version",
        ),
    )
