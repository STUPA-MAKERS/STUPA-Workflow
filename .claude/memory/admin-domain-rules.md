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
`/admin/roles` screen. The Gremien admin manages Gremium membership per Gremium, not through a
per-user gremium dropdown. See [[nextcloud-parity-ui]], [[antragsplattform-backlog]].
