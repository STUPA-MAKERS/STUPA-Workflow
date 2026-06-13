"""Permission-Katalog (Single Source fürs Admin-FE, api.md §1).

Die autoritative Wahrheit über *zugewiesene* Permissions bleibt ``role_permission``
(DB) — diese Liste ist der **Katalog wählbarer Keys**, den die Rollen-/Rechte-UI
(``/admin/users``, #72) anbietet, damit das FE nicht hartkodiert, welche Permissions
existieren. Deckungsgleich mit den Permission-Keys aus ``sds/api.md §1`` plus den von
Bestands-Guards/Routen erzwungenen Keys (``flow.configure``/``form.configure``,
``budget.view``/``protocol.write``), inkl. der in Migration 0010/0016 an die
``admin``-Rolle nachgeseedeten Konfigurations-Permissions.
"""

from __future__ import annotations

# Reihenfolge nach Bereich gruppiert (stabil → deterministischer Contract).
# #28-Redesign: ``application.update`` (→ ``application.manage``) sowie
# ``protocol.manage``/``protocol.write`` (→ ``meeting.manage``) entfallen;
# ``application.transition`` gatet das Feuern manueller Flow-Übergänge.
# #6-Granularität (Migration 0017 remappt Bestands-Zuweisungen):
#   ``admin.config``  → ``admin.site`` / ``admin.gremien`` / ``admin.types``
#   ``budget.manage`` → ``budget.structure`` (Baum/HHJ/Zuteilungen) /
#                       ``budget.book`` (Buchungen/Umbuchungen)
#   ``meeting.manage`` behält Sitzungen/Protokoll-Entwurf; ``protocol.finalize``
#                       gatet das Finalisieren+Versenden separat
#   ``audit.read``     behält die Lesesicht; ``audit.verify`` die Hash-Kette
PERMISSION_CATALOGUE: tuple[str, ...] = (
    "application.read",
    # Jeden Antrag lesen — Gremiums-/Eigentums-unabhängig (global). #app-read-all.
    "application.read_all",
    "application.create",
    "application.transition",
    "application.manage",
    # Antragsdaten in JEDEM Flow-State ändern — hebt den State-Edit-Lock auf
    # (state.edit_allowed). #app-edit-any.
    "application.edit_any",
    "form.configure",
    "flow.configure",
    "vote.cast",
    "vote.manage",
    "meeting.manage",
    "protocol.finalize",
    # Löschen von Sitzungen mit FINALISIERTEM Protokoll (#16) — bewusst getrennt
    # von meeting.manage; jedes Löschen landet als meeting_delete im Audit-Log.
    "meeting.delete_finalized",
    "budget.view",
    "budget.structure",
    "budget.book",
    "budget.export",
    "account.manage",
    "application.export",
    "webhook.manage",
    "audit.read",
    "audit.verify",
    "admin.site",
    "admin.gremien",
    "admin.types",
    # Antragsarten LÖSCHEN — bewusst getrennt von admin.types (Anlegen/Bearbeiten);
    # das Entfernen einer Antragsart ist destruktiv (Formular/Flow hängen dran).
    "admin.types_delete",
    "admin.roles",
    # Plattform-Benachrichtigungs-Config (#task-reminder): Erinnerungs-Schwellen,
    # künftig Mail-Templates. Migration 0018 verteilt es an admin.site-Inhaber.
    "admin.notifications",
    # MCP/Agent-Zugang: erlaubt das Ausstellen von OAuth-Token für API-Agenten
    # (#MCP). Admin hat es ohnehin (Bypass); explizit zuweisbar für Nicht-Admins.
    "mcp.use",
)
