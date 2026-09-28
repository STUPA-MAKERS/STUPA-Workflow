---
name: admin-domain-rules
description: "Domain rules the user asserted for the antragsplattform admin (roles, delegation, i18n editing)"
metadata: 
  node_type: memory
  type: project
---

User-asserted rules (apply them from now on, tasks #14 to #16):

- **The admin role always has ALL permissions** and must not be editable. The FE Roles screen
  (`pages/admin/roles`) shows the `admin` role as locked and read-only, with everything granted.
  The backend must enforce this too (#15).
- **Vote delegation (German UI label "Stimmrecht delegieren") is a per-Gremium setting**, NOT a
  per-user and NOT a per-role setting. The Users assign form no longer has the per-user checkbox
  (#14). It still needs a Gremium-level flag plus UI.
- **Every i18n-configurable value must be editable in EN too, not only in DE** (#16). Many editors
  bind only `['de']` — branding (copyright/footer/freetexts), gremium, form labels. The flow-editor
  state and transition labels already do DE+EN.

Also: the Users screen is now a Nextcloud-style table. Role *permissions* live on a separate
`/admin/roles` screen.

**Membership and roles come from OIDC groups only (2026-09-27).** Nobody can set a Gremium
membership or a global role assignment by hand. An OIDC group links in THREE SEPARATE ways, all on
`/admin/group-mappings`: group → global role (`group_mapping`, no gremium scope), group → gremium
membership (`gremium_membership_mapping`), group → gremium role (`gremium_role_mapping`, only for
members). The user was explicit: global roles, gremien and gremium roles are unrelated and must
never be combined in one mapping. The login sync writes `gremium_membership`. The only `role_assignment` rows are the bootstrap ones. Do not
add a manual write path back. See [[nextcloud-parity-ui]], [[antragsplattform-backlog]].
