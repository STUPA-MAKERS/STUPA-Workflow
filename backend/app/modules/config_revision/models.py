"""``config_revision`` — append-only Snapshot-Kette versionierter Configs.

Wie ``audit_entry`` **append-only**: ein DB-Trigger lehnt UPDATE/DELETE/TRUNCATE ab
(Migration ``0034`` + Least-Privilege-Grant ``audit_writer``) — eine frühere Version
kann **niemals** gelöscht werden (#config-versioning).

``snapshot`` hält den vollständigen, wiederherstellbaren Config-Stand in seiner
**natürlichen Form** (Forms: Felder+Beschreibung, Flow: ``FlowGraph``, Branding:
``Branding``) — **nur Config, nie Principal-PII** (DSGVO-Löschung bleibt intakt).
``version`` zählt monoton je (``entity_type``, ``entity_id``); ``prev_revision_id``
verkettet die Stände (Diff = aufeinanderfolgende Snapshots).
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
    # 'form' | 'flow' | 'site_config' (erweiterbar in Phase 2).
    entity_type: Mapped[str] = mapped_column(Text)
    # uuid-String (form: application_type_id) bzw. 'global' (flow/site_config).
    entity_id: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Vorgänger-Snapshot derselben Entität (NULL = erster Stand).
    prev_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("config_revision.id", ondelete="RESTRICT"), nullable=True
    )
    # OIDC-``sub`` des Auslösers (kein PII).
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
