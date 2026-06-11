"""Live-Presence: wer hat die Sitzungs-Seite gerade offen (#live-viewers).

Prozess-lokales Register der offenen **Voter**-WS-Verbindungen je Sitzung
(Beamer zählen nicht — sie sind Anzeige, keine Person). Jede Verbindung erhält
eine eigene Connection-ID, damit derselbe Nutzer mit zwei Tabs beim Schließen
des ersten nicht aus der Liste fällt. Der Stand wird nach Join/Leave als
``viewers``-Event über den Broker gefan-outet — das FE (Protokollant) zeigt die
Namen live an.

Bewusst in-memory (kein Redis): die Verbindungen leben im selben Prozess; stirbt
er, sterben auch die WS-Verbindungen mit. Bei mehreren API-Replikas zeigt jede
Instanz nur ihre eigenen Verbindungen — fürs aktuelle Single-Replica-Deployment
ausreichend (dokumentierte Grenze).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass
class MeetingPresence:
    """``meeting_id → {connection_id: (sub, anzeigename)}``."""

    _viewers: dict[UUID, dict[str, tuple[str, str]]] = field(
        default_factory=lambda: defaultdict(dict)
    )

    def join(self, meeting_id: UUID, sub: str, name: str) -> tuple[str, list[str]]:
        """Verbindung registrieren → (connection_id, aktuelle Namensliste)."""
        connection_id = uuid4().hex
        self._viewers[meeting_id][connection_id] = (sub, name)
        return connection_id, self.names(meeting_id)

    def leave(self, meeting_id: UUID, connection_id: str) -> list[str]:
        """Verbindung austragen → aktuelle Namensliste."""
        room = self._viewers.get(meeting_id)
        if room is not None:
            room.pop(connection_id, None)
            if not room:
                self._viewers.pop(meeting_id, None)
        return self.names(meeting_id)

    def names(self, meeting_id: UUID) -> list[str]:
        """Deduplizierte (je ``sub``), sortierte Anzeigenamen der Zuschauer."""
        seen: dict[str, str] = {}
        for sub, name in self._viewers.get(meeting_id, {}).values():
            seen.setdefault(sub, name)
        return sorted(seen.values(), key=str.casefold)


# Ein Register je API-Prozess (die WS-Verbindungen leben im selben Prozess).
PRESENCE = MeetingPresence()
