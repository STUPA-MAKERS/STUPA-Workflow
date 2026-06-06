"""Sitzungs-Tabelle (data-model §»Sitzung & Protokoll«, flows §5, T-16).

:class:`Meeting` — eine (Gremium-)Sitzung, an die Live-Votes gebunden werden.
``status`` steuert den Live-Vote-Kanal (``planned`` → ``live`` → ``closed``),
``active_application_id`` zeigt den aktuell auf dem Beamer behandelten Antrag.

Wie alle Modul-Tabellen entsteht ``meeting`` auf einem **frischen** Schema über
``Base.metadata.create_all`` in Migration 0002 (Single-Source via ``app.models``);
für ältere Schemata legt Migration 0008 sie idempotent nach und ergänzt dort die
zuvor bewusst FK-lose ``vote.meeting_id``-Spalte (T-15) um die echte Constraint.
"""

from __future__ import annotations

import uuid
from datetime import date as _date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class Meeting(UUIDPkMixin, CreatedAtMixin, Base):
    """Gremium-Sitzung; Anker des Live-Vote-Kanals ``meeting:{id}`` (flows §5)."""

    __tablename__ = "meeting"

    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text)
    date: Mapped[_date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="planned")
    active_application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('planned','live','closed')", name="meeting_status"
        ),
        Index("ix_meeting_gremium_id", "gremium_id"),
    )
