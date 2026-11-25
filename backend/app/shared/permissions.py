"""Permission catalog: the single source of selectable keys for the admin UI.

The `role_permission` table in the database stays the authoritative record of the
*assigned* permissions. This list is only the catalog of keys that the roles and
permissions UI offers. The frontend therefore never hardcodes which permissions exist.
The keys stay grouped by area to keep the contract stable and deterministic.

Voting, meeting management and protocol rights are NOT in this catalog. They are
gremium permissions (`vote.cast`, `vote.manage`, `session.manage`, `protocol.write`,
`protocol.finalize`) of the gremium role catalog in `app.modules.gremien.gremium_roles`.
A vote names its gremium in `eligibleGroup`.

Keys that need a note:

- `application.read_all`: read every application, independent of Gremium and
  ownership (global).
- `application.force_status`: force an application into ANY state. It bypasses the
  flow guards and the transitions. The log records every use as a forced
  status_change, and you can revert it. It stays SEPARATE from
  `application.transition`; grant it deliberately.
- `application.record_decision`: record on an application in a vote state the
  decision that a Gremium made in a meeting without a vote on the platform. It fires
  the `pass` or `fail` branch of the vote state with its actions and mails. It stays
  SEPARATE from `application.force_status`, because it follows the flow.
- `application.amend_decision`: change the approved amount of an approved
  application, with a reason and the decision that allows it. The state stays.
- `application.edit_any`: edit application data in ANY flow state, overriding the
  state edit lock.
- `application.delete`: delete an application permanently with its versions, comments
  and timeline. No revert brings it back, so it stays SEPARATE from
  `application.manage`, which covers the edit only.
- `application.archive`: move an application out of the working list and back. It is
  reversible, so it is NOT part of `application.delete`. It decides what everyone else
  sees by default, so it is not part of `application.manage` either.
- `application.create_on_behalf`: capture an application for an existing account or
  a guest. The application belongs to the applicant; the holder shows only in the
  history and the audit log. Global. Grant it deliberately, because the applicant
  search of the dialog exposes the names and e-mail addresses of ALL active accounts.
- `application.change_type`: change the Antragsart of a submitted application. The
  change writes a new version in the form of the new type and can send the application
  back to the applicant. Global.
- `meeting.view_all`: additive global read of every meeting (timeline, list, detail,
  agenda, protocol, vote results). The holder never writes and never votes.
- `meeting.delete_finalized`: delete a meeting with a finalized protocol, separate
  from `session.manage`. The audit log records each delete as meeting_delete.
- `gremium.view_all`: additive global read of every Gremium in the tab "Gremien": its
  members with their e-mail addresses, its meetings and the attendance per member and
  month. Without it a member sees the own Gremien only. The decisions of a Gremium keep
  the read scope of the votes (`meeting.view_all`).
- `audit.read`: GLOBAL without Gremium scope, because the audit log is an
  organization-wide forensic view over the hash chain. It can expose PII across
  Gremien.
- `audit.revert`: restore the prior state of a config change. Destructive and
  admin-only by default.
- `admin.types_delete`: delete an application type, separate from `admin.types`
  (create, edit), because a form and a flow hang on the type.
- `admin.roles`, `admin.users`, `admin.group_mappings`, `gremien.gremium_roles`,
  `admin.cd_variants`, `admin.delegations`, `admin.deadlines`: one key per admin page
  (/admin/roles, /admin/users, /admin/group-mappings, /admin/committees/:id/roles,
  /admin/cd-variants with the logo upload and download, /admin/delegations with the
  substitute pool, /admin/deadlines with the meeting window and guest confirmation).
- `admin.translations`: the UI texts of every key in every locale and the extra UI
  languages (/admin/translations). An override shows to every visitor, the login page
  and the public pages included.
- `admin.users.merge`: merge an old account (for example a Keycloak-era `sub`) into a
  new one, rewriting its references and locking it. Admin-only by default. No OAuth
  scope carries it, so an agent token never merges.
- `admin.users.revoke_groups`: revoke the rights of a person who no longer logs in.
  It clears whole Gremien (SSO groups, gremium role assignments, pool entries,
  delegations in planned meetings) and global roles. Admin-only by default. No OAuth
  scope carries it, so an agent token never revokes.
- `admin.notifications`: reminder thresholds and mail templates.
- `privacy.manage`: GDPR erasure, principal and application deletion, subject-access
  export and retention config.
- `backup.manage`: create, download, upload and restore whole-platform backups. It is
  separate from every `admin.*` key, because its holder can read the entire database,
  PII included, and can replace it.
- `mcp.use`: issue OAuth tokens for API agents. An admin holds it through the bypass;
  a non-admin can get it too.
- `ticket.manage`: work on reported tickets (status, assignee, kind, notes). The
  reports carry the e-mail and the technical context of the reporter.
- `todo.read_all`: additive global read of every Gremium and team to-do board (cards,
  comments, files, history). The holder never writes, never configures and is no
  member, so nobody assigns or mentions the holder. A personal board stays private.
- `todo.all`: global read AND write of the cards of every Gremium and team board. It
  never configures a board (that is the Gremium permission `todo.configure`) and makes
  no member. A personal board stays private.
- `todo.create_board`: create a free to-do board (spec 001061). The creator becomes a
  member with the role `manage`; the right reaches no existing board.
- `order.manage`: create, change and delete the Bestellungen that the person reads
  (F/finance/orders/002862). It is separate from `budget.book`, so a role can order
  without the right to book.
- `invoice.manage`: create, change and delete the invoices and upload their files
  (F/finance/invoices/003015). It gives no read and no booking. `budget.book` gives the
  same write, so a role that books keeps the invoices.
- `finance.export`: every file export of the finance pages: the Haushalt, the bookings
  and the Bestellungen (F/finance/budget/003016).
- `calendar.manage`: read, change and delete every Termin of the Kalender and invite
  any Gremium. Without it a person changes only the own Termine.
- `admin.calendars`: subscribe, change and delete the external calendars
  (/admin/calendars). The holder gives the server an address to fetch, so the key is
  separate from `calendar.manage`.
- `calendar.publish`: set the switches "Für alle" and "Öffentlich" of a Termin. "Für
  alle" shows the Termin to each signed-in person, "Öffentlich" also to a person without
  a sign-in. It is separate from `calendar.manage`, so no Termin is visible to all by
  accident.
- `budget.plan.set_state`: set the state of a Haushaltsplan by hand: the draft, a step
  or the state in force, without the decisions between them. The audit log records
  each use with its reason. It stays SEPARATE from `budget.structure`, and no OAuth
  scope carries it, so an agent token never sets a plan in force.
- `admin.features`: switch the features of the platform on and off (/admin/features).
  A switch changes the platform for every person, so the key is separate from
  `admin.site`. No OAuth scope carries it, so an agent token never switches a feature.
- `graph.view`: open the page "Graph", which draws the elements of every area and their
  relations at once. It opens the page only and gives no read access: each node keeps
  the read rule of its kind. No seeded role but the admin holds it.
- `admin.paperless`: set the connection to Paperless, its switches and the actions of
  the page /admin/paperless. The holder gives the server an address to call and a token,
  so the key is separate from `admin.site`. No OAuth scope carries it, so an agent token
  never changes the connection.
- `admin.order_phases`: edit the status list of the Bestellungen on the page
  "Bestellphasen" (/admin/order-phases, F/administration/admin/003035). A change moves
  Bestellungen to another status, so the key is separate from `admin.site`. The OAuth
  scope `admin:write` carries it.
- `admin.event_phases`: the same for the status list of the Events on the page
  "Veranstaltungsphasen" (/admin/event-phases).
- `admin.ticket_mail`: set the Postfach of a Bereich (/admin/help-tickets): its address,
  the IMAP and the SMTP account, and its switch. The holder gives the server two hosts to
  call and the password of a mail account, so the key is separate from `admin.site`
  (§F/integrations/ticket-mail/002721). No OAuth scope carries it, so an agent token never
  changes a Postfach.
- `paperless.use`: open the filed document of an element in Paperless and insert a
  document from Paperless. The holder reads what the account of the platform reads in
  Paperless, so no seeded role but the admin holds it and no OAuth scope carries it.
"""

from __future__ import annotations

PERMISSION_CATALOGUE: tuple[str, ...] = (
    "application.read",
    "application.read_all",
    "application.transition",
    "application.force_status",
    "application.record_decision",
    "application.amend_decision",
    "application.manage",
    "application.edit_any",
    "application.delete",
    "application.archive",
    "application.create_on_behalf",
    "application.change_type",
    "form.configure",
    "flow.configure",
    "meeting.view_all",
    "meeting.delete_finalized",
    "gremium.view_all",
    "budget.view",
    "budget.structure",
    "budget.book",
    "finance.export",
    "budget.plan.set_state",
    "application.export",
    "webhook.manage",
    "audit.read",
    "audit.verify",
    "audit.revert",
    "admin.site",
    "admin.gremien",
    "admin.types",
    "admin.types_delete",
    "admin.roles",
    "admin.users",
    "admin.users.merge",
    "admin.users.revoke_groups",
    "admin.group_mappings",
    "gremien.gremium_roles",
    "admin.cd_variants",
    "admin.delegations",
    "admin.deadlines",
    "admin.translations",
    "admin.notifications",
    "privacy.manage",
    "backup.manage",
    "mcp.use",
    "ticket.manage",
    "order.manage",
    "invoice.manage",
    "todo.read_all",
    "todo.all",
    "todo.create_board",
    "calendar.manage",
    "calendar.publish",
    "admin.calendars",
    "admin.features",
    "graph.view",
    "admin.paperless",
    "admin.ticket_mail",
    "admin.order_phases",
    "admin.event_phases",
    "paperless.use",
)


#: The permission that edits each status list, one page each (F/administration/admin/003035).
STATUS_LIST_PERMISSIONS: dict[str, str] = {
    "order": "admin.order_phases",
    "event": "admin.event_phases",
}
