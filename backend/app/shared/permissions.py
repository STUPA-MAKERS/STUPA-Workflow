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
PERMISSION_CATALOGUE: tuple[str, ...] = (
    "application.read",
    "application.create",
    "application.update",
    "application.transition",
    "application.manage",
    "form.configure",
    "flow.configure",
    "vote.manage",
    "vote.cast",
    "meeting.manage",
    "protocol.manage",
    "protocol.write",
    "budget.manage",
    "budget.view",
    "notification.manage",
    "webhook.manage",
    "audit.read",
    "admin.config",
    "admin.roles",
)
