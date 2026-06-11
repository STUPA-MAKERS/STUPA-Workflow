"""Katalog der konfigurierbaren Benachrichtigungs-Arten (#4-2/#4-3).

Eine *Art* (``kind``) bündelt fachlich zusammengehörige Mails; die
Einstellungsseite (`/account/notifications`) bietet genau diese Keys an.
Magic-Link-Mails sind essenziell (Login-Funktion) und bewusst NICHT
abschaltbar — sie stehen daher nicht im Katalog.

Versandseitig filtert :meth:`NotificationService.filter_by_preference`
Empfänger-Adressen über diesen Katalog; unbekannte Kinds werden nie
gefiltert (fail-open beim Versand, aber 422 beim Speichern unbekannter
Keys über die API).
"""

from __future__ import annotations

NOTIFICATION_KINDS: tuple[str, ...] = (
    # Eigene Anträge: Statuswechsel/Updates (Flow-notify-Actions).
    "status_update",
    # Neue Kommentare zu Anträgen, die einen betreffen (#4-1).
    "comment",
    # Antrag in einem State, in dem die eigene Rolle handeln kann (#4-3).
    "task",
    # Erinnerung an liegengebliebene offene Aufgaben (#4-3).
    "task_reminder",
    # Sitzungen: Einladung/Tagesordnung veröffentlicht (#4-3).
    "meeting",
    # Abstimmungen geöffnet/geschlossen (#4-3).
    "vote",
    # Eigene Rolle zugewiesen/entzogen (#4-3).
    "role_change",
    # Stimm-Delegation erhalten/widerrufen (#4-3).
    "delegation",
    # Sitzungsprotokoll finalisiert.
    "protocol",
    # Frist-Erinnerungen zu Anträgen.
    "deadline",
)
