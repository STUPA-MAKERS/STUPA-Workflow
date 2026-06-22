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

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
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
    # ``none_as_null=True``: Python ``None`` MUSS als SQL NULL (nicht als JSONB-Skalar
    # ``'null'``) gespeichert werden — sonst matcht ``action_on_pass IS NOT NULL`` (Scan +
    # Partial-Index ``ix_deadline_due_at_action``) auch reine Erinnerungs-Fristen, und
    # ``mark_fired`` (setzt ``None``) entfernte die Frist nie aus dem Scan (Doppel-Feuern).
    action_on_pass: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
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


class DeadlinePolicy(UUIDPkMixin, Base):
    """Benannte Frist-**Policy** (Registry), die der Flow per ``key`` referenziert.

    Entkoppelt die konkrete Frist von der Flow-Definition: eine Policy lässt sich
    z. B. pro Semester aktualisieren (``absolute``-Datum), **ohne** den Flow neu zu
    versionieren. Zwei relative Varianten leiten die Frist aus dem Antrag ab:

    * ``absolute``            — fixes ``due_at`` = ``absolute_at`` (pro Semester editierbar).
    * ``relative_submitted``  — Einreichung (``application.created_at``) + ``offset_days``.
    * ``relative_changed``    — letzte Änderung (``application.updated_at``) + ``offset_days``.
    """

    __tablename__ = "deadline_policy"

    # Stabiler Referenz-Schlüssel (vom Flow benutzt); eindeutig.
    key: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[dict] = mapped_column(JSONB)  # I18nMap (de/en …)
    kind: Mapped[str] = mapped_column(Text)
    # Nur bei ``absolute`` gesetzt (pro Semester nachpflegbar).
    absolute_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Nur bei den relativen Varianten gesetzt (Tage Versatz).
    offset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('absolute','relative_submitted','relative_changed')",
            name="deadline_policy_kind",
        ),
    )
