"""Deadline-Tabelle (data-model »deadline«, flows §9.4, T-44).

Eine :class:`Deadline` bindet einen Zeitpunkt (``due_at``) an einen Antrag und/oder
Antragstyp und beschreibt **optional**, was bei Ablauf passiert:

* ``action_on_pass`` (JSONB, NULL) = Referenz auf einen Flow-Übergang
  (``{"transitionId": "<uuid>"}``). Ist er gesetzt, scannt der arq-Cron (flows §9.4)
  die Frist und feuert den Übergang mit Guard ``deadlinePassed`` (Auto-Übergang bzw.
  Wiedervorlage/Requeue, ``kind="requeue"``). Nach erfolgreichem Feuern wird
  ``action_on_pass`` auf NULL gesetzt → die Frist verlässt den (partiellen) Scan-Index,
  ein erneuter Lauf feuert **nicht** doppelt (Idempotenz-Marker).
* ``reminded_at`` (timestamptz, NULL) markiert eine bereits versandte Erinnerung
  (``deadline_approaching``) → genau-einmal-Semantik, auch bei parallelen Workern.

Auf einem **frischen** Schema entsteht die Tabelle über ``Base.metadata.create_all``
in Migration 0002 (Single-Source via ``app.models``); für ältere Schemata legt
Migration 0014 sie **idempotent** (``checkfirst``) nach.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UUIDPkMixin


class Deadline(UUIDPkMixin, Base):
    """Frist zu einem Antrag/Antragstyp mit optionaler Ablauf-Aktion (flows §9.4)."""

    __tablename__ = "deadline"

    # Antrags-Frist (CASCADE: gelöschter Antrag entfernt seine Fristen) — NULL bei
    # rein typ-bezogenen Vorlagen-Fristen (``type_id``).
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True
    )
    type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application_type.id", ondelete="CASCADE"), nullable=True
    )
    # Freitext-Klassifikation (z. B. ``flow_phase``, ``vote``, ``requeue``) — rein
    # informativ/filterbar; die Wirkung steckt in ``action_on_pass``.
    kind: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # = Transition-/Action-Ref; NULL = reine Erinnerungs-/Anzeige-Frist ohne Auto-Wirkung.
    action_on_pass: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Cron-Scan der ablaufenden Auto-Fristen (data-model »deadline«): partiell, da nur
        # Fristen mit Aktion gefeuert werden; nach dem Feuern fällt die Zeile heraus.
        Index(
            "ix_deadline_due_at_action",
            "due_at",
            postgresql_where=text("action_on_pass IS NOT NULL"),
        ),
        # Erinnerungs-Scan: nur noch nicht erinnerte Fristen.
        Index(
            "ix_deadline_reminder",
            "due_at",
            postgresql_where=text("reminded_at IS NULL"),
        ),
    )
