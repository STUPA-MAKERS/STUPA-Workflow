---
id: "003017"
title: Every global permission has a German and an English name
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
tests:
  - "backend/tests/unit/test_permission_names.py:test_every_permission_has_a_name"
implementation:
  - frontend/src/app/core/i18n/catalog/de.json
  - frontend/src/app/core/i18n/catalog/en.json
scope:
  - backend/app/shared
  - frontend/src/app/core/i18n
  - frontend/src/app/pages/admin/roles
---

# Every global permission has a German and an English name

Each key of the permission catalogue (`PERMISSION_CATALOGUE`) must have a name in German and in
English. The names must be the UI texts `admin.perm.<key>` of the built-in catalogue, so the
page "Übersetzungen" can change them like any other UI text. A new key must not reach
development without its two names.

The names are:

| Key | German | English |
|---|---|---|
| `application.read` | Anträge lesen | Read applications |
| `application.read_all` | Alle Anträge lesen | Read all applications |
| `application.transition` | Status von Anträgen ändern | Change application status |
| `application.force_status` | Status erzwingen | Force a status |
| `application.record_decision` | Beschluss eintragen | Record a decision |
| `application.amend_decision` | Bewilligten Betrag ändern | Amend the approved amount |
| `application.manage` | Anträge bearbeiten | Edit applications |
| `application.edit_any` | Anträge in jedem Status bearbeiten | Edit applications in any status |
| `application.delete` | Anträge löschen | Delete applications |
| `application.archive` | Anträge archivieren | Archive applications |
| `application.create_on_behalf` | Anträge für andere erfassen | Submit applications for others |
| `application.change_type` | Antragsart ändern | Change the application type |
| `form.configure` | Formulare bearbeiten | Edit forms |
| `flow.configure` | Flow bearbeiten | Edit the flow |
| `meeting.view_all` | Alle Sitzungen lesen | Read all meetings |
| `meeting.delete_finalized` | Abgeschlossene Sitzungen löschen | Delete finalized meetings |
| `gremium.view_all` | Alle Gremien lesen | Read all Gremien |
| `budget.view` | Haushalt lesen | Read the budget |
| `budget.structure` | Haushalt aufbauen | Build the budget |
| `budget.book` | Buchen | Book |
| `finance.export` | Finanzen exportieren | Export finances |
| `budget.plan.set_state` | Status des Haushaltsplans setzen | Set the budget plan status |
| `application.export` | Anträge exportieren | Export applications |
| `webhook.manage` | Webhooks verwalten | Manage webhooks |
| `audit.read` | Audit-Log lesen | Read the audit log |
| `audit.verify` | Audit-Log prüfen | Verify the audit log |
| `audit.revert` | Änderungen zurücknehmen | Revert changes |
| `admin.site` | Branding und Texte verwalten | Manage branding and texts |
| `admin.gremien` | Gremien verwalten | Manage Gremien |
| `admin.types` | Antragsarten verwalten | Manage application types |
| `admin.types_delete` | Antragsarten löschen | Delete application types |
| `admin.roles` | Rollen verwalten | Manage roles |
| `admin.users` | Benutzer verwalten | Manage users |
| `admin.users.merge` | Konten zusammenführen | Merge accounts |
| `admin.users.revoke_groups` | Rechte entziehen | Revoke rights |
| `admin.group_mappings` | Gruppen-Zuordnung verwalten | Manage group mappings |
| `gremien.gremium_roles` | Gremium-Rollen verwalten | Manage Gremium roles |
| `admin.cd_variants` | Dokument-Varianten verwalten | Manage document variants |
| `admin.delegations` | Vertretungen verwalten | Manage delegations |
| `admin.deadlines` | Fristen verwalten | Manage deadlines |
| `admin.translations` | Übersetzungen verwalten | Manage translations |
| `admin.notifications` | Benachrichtigungen verwalten | Manage notifications |
| `privacy.manage` | Datenschutz verwalten | Manage privacy |
| `backup.manage` | Backups verwalten | Manage backups |
| `mcp.use` | Agent-Zugänge nutzen | Use agent access |
| `ticket.manage` | Tickets bearbeiten | Work on tickets |
| `order.manage` | Bestellungen verwalten | Manage orders |
| `invoice.manage` | Rechnungen verwalten | Manage invoices |
| `todo.read_all` | Alle Boards lesen | Read all boards |
| `todo.all` | Alle Boards bearbeiten | Edit all boards |
| `todo.create_board` | Boards anlegen | Create boards |
| `calendar.manage` | Kalender verwalten | Manage the calendar |
| `calendar.publish` | Termine veröffentlichen | Publish appointments |
| `admin.calendars` | Externe Kalender verwalten | Manage external calendars |
| `admin.features` | Funktionen schalten | Switch features |
| `graph.view` | Graph öffnen | Open the graph |
| `admin.paperless` | Paperless verwalten | Manage Paperless |
| `admin.ticket_mail` | Ticket-Postfächer verwalten | Manage ticket mailboxes |
| `paperless.use` | Paperless nutzen | Use Paperless |

Reason: A key such as `budget.plan.set_state` does not tell an admin what the right allows. The
names come from the UI catalogue, so the admin can adapt them without a code change.

Test: A backend unit test reads both catalogue files and fails for each key of
`PERMISSION_CATALOGUE` without a non-empty `admin.perm.<key>` text.
