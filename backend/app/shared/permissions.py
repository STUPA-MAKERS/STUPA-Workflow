"""Permission catalog: the single source of selectable keys for the admin UI.

The `role_permission` table in the database stays the authoritative record of the
*assigned* permissions. This list is only the catalog of keys that the roles and
permissions UI offers. The frontend therefore never hardcodes which permissions exist.
The keys stay grouped by area to keep the contract stable and deterministic.

Voting, meeting management and protocol rights are NOT in this catalog. They are
gremium permissions (`vote.cast`, `vote.manage`, `session.manage`, `protocol.write`,
`protocol.finalize`) of the gremium role catalog in `app.modules.admin.gremium_roles`.
A vote names its gremium in `eligibleGroup`.

Keys that need a note:

- `application.read_all`: read every application, independent of Gremium and
  ownership (global).
- `application.force_status`: force an application into ANY state. It bypasses the
  flow guards and the transitions. The log records every use as a forced
  status_change, and you can revert it. It stays SEPARATE from
  `application.transition`; grant it deliberately.
- `application.edit_any`: edit application data in ANY flow state, overriding the
  state edit lock.
- `application.delete`: delete an application permanently with its versions, comments
  and timeline. No revert brings it back, so it stays SEPARATE from
  `application.manage`, which covers the edit only.
- `application.archive`: move an application out of the working list and back. It is
  reversible, so it is NOT part of `application.delete`. It decides what everyone else
  sees by default, so it is not part of `application.manage` either.
- `application.share`: create a PUBLIC read-only link. It is its own key, because
  reading an application and deciding that anyone with a URL may read it are
  different decisions, and a magic-link reader must not be able to publish.
- `application.create_on_behalf`: capture an application for an existing account or
  a guest. The application belongs to the applicant; the holder shows only in the
  history and the audit log. Global. Grant it deliberately, because the applicant
  search of the dialog exposes the names and e-mail addresses of ALL active accounts.
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
- `admin.roles`, `admin.users`, `admin.group_mappings`, `admin.gremium_roles`,
  `admin.cd_variants`, `admin.delegations`, `admin.deadlines`: one key per admin page
  (/admin/roles, /admin/users, /admin/group-mappings, /admin/gremien/:id/roles,
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
"""

from __future__ import annotations

PERMISSION_CATALOGUE: tuple[str, ...] = (
    "application.read",
    "application.read_all",
    "application.transition",
    "application.force_status",
    "application.manage",
    "application.edit_any",
    "application.delete",
    "application.archive",
    "application.share",
    "application.create_on_behalf",
    "form.configure",
    "flow.configure",
    "meeting.view_all",
    "meeting.delete_finalized",
    "gremium.view_all",
    "budget.view",
    "budget.structure",
    "budget.book",
    "budget.export",
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
    "admin.gremium_roles",
    "admin.cd_variants",
    "admin.delegations",
    "admin.deadlines",
    "admin.translations",
    "admin.notifications",
    "privacy.manage",
    "backup.manage",
    "mcp.use",
    "ticket.manage",
    "todo.read_all",
    "todo.all",
)
