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
from datetime import datetime as _datetime
from datetime import time as _time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin


class Meeting(UUIDPkMixin, CreatedAtMixin, Base):
    """Gremium-Sitzung; Anker des Live-Vote-Kanals ``meeting:{id}`` (flows §5)."""

    __tablename__ = "meeting"

    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text)
    date: Mapped[_date | None] = mapped_column(Date, nullable=True)
    # Geplante Uhrzeit (#34) — optional, ergänzt das Datum.
    start_time: Mapped[_time | None] = mapped_column(Time, nullable=True)
    # Geplante End-Uhrzeit (#ics) — optional; fehlt sie, nimmt der iCal-Feed eine
    # Default-Dauer von 1 h ab ``start_time`` an. Muss (falls gesetzt) nach
    # ``start_time`` liegen (Schema-Check beim Anlegen).
    end_time: Mapped[_time | None] = mapped_column(Time, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="planned")
    # Automatisch gesetzt beim Wechsel auf ``closed`` (#14) — liefert die
    # »Ende«-Zeile der Protokoll-Titelseite. ``closed`` ist terminal.
    closed_at: Mapped[_datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active_application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Der je Sitzung zugewiesene Protokollant (genau einer). Er führt die Live-Sitzung
    # und schreibt das Protokoll; SET NULL, falls der Principal gelöscht wird.
    protokollant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('planned','live','closed')", name="meeting_status"
        ),
        Index("ix_meeting_gremium_id", "gremium_id"),
    )


class MeetingAttendance(UUIDPkMixin, TimestampMixin, Base):
    """Anwesenheit je (Sitzung, Mitglied) (#Meetings/#55/#56).

    ``status`` = present/excused/absent; ``source`` zeigt, wer den Eintrag setzte
    (``self`` = Mitglied selbst, ``lead`` = Sitzungsleitung). Genau **ein** Eintrag
    je (meeting, principal) — Upsert über die Unique-Constraint.
    """

    __tablename__ = "meeting_attendance"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meeting.id", ondelete="CASCADE")
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="lead")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("meeting_id", "principal_id", name="uq_attendance_meeting_principal"),
        CheckConstraint(
            "status IN ('present','excused','absent')", name="attendance_status"
        ),
        CheckConstraint("source IN ('self','lead')", name="attendance_source"),
        Index("ix_attendance_meeting", "meeting_id"),
    )


class MeetingAgendaItem(UUIDPkMixin, CreatedAtMixin, Base):
    """Tagesordnungspunkt: ein der Sitzung zugeordneter Antrag (#10/#58).

    Geordnete Liste (``position``) der auf der Sitzung zu behandelnden Anträge —
    Quelle der Protokoll-TOPs und (perspektivisch) der Live-Abstimmungen. Pro
    (Sitzung, Antrag) genau einmal.
    """

    __tablename__ = "meeting_agenda_item"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meeting.id", ondelete="CASCADE")
    )
    # NULL = Freitext-TOP (kein Antrag); dann trägt ``title`` den TOP-Text.
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True
    )
    # Freitext-Titel eines TOP ohne Antrag (z. B. »Verschiedenes«).
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Markdown-Text dieses TOP (pro-TOP-Editor); fließt ins finale Protokoll.
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    # Nicht-öffentlich (#PII-Re-Add): im öffentlichen Protokoll-PDF durch einen
    # Platzhalter ersetzt; die TOP-Nummerierung bleibt erhalten.
    non_public: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (
        UniqueConstraint("meeting_id", "application_id", name="uq_agenda_meeting_application"),
        Index("ix_agenda_meeting", "meeting_id"),
    )
