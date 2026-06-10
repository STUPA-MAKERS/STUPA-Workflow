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
PERMISSION_CATALOGUE: tuple[str, ...] = (
    "application.read",
    "application.create",
    "application.transition",
    "application.manage",
    "form.configure",
    "flow.configure",
    "vote.cast",
    "vote.manage",
    "meeting.manage",
    "budget.view",
    "budget.manage",
    "budget.export",
    "account.manage",
    "application.export",
    "webhook.manage",
    "audit.read",
    "admin.config",
    "admin.roles",
    # MCP/Agent-Zugang: erlaubt das Ausstellen von OAuth-Token für API-Agenten
    # (#MCP). Admin hat es ohnehin (Bypass); explizit zuweisbar für Nicht-Admins.
    "mcp.use",
)
