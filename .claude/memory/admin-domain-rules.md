---
name: admin-domain-rules
description: "Domain rules the user asserted for the antragsplattform admin (roles, delegation, i18n editing)"
metadata: 
  node_type: memory
  type: project
---

User-asserted rules (apply going forward; tasks #14–#16):

- **Admin role always has ALL permissions** and must not be editable. FE Roles screen (`pages/admin/roles`) renders the `admin` role as locked/read-only (all granted). Backend should enforce this too (#15).
- **Vote delegation ("Stimmrecht delegieren") is a per-Gremium setting**, NOT per user or per role. The per-user checkbox was removed from the Users assign form (#14). Needs a Gremium-level flag + UI.
- **Every i18n-configurable value must be editable in EN too, not only DE** (#16). Many editors bind only `['de']` — branding (copyright/footer/freetexts), gremium, form labels. Flow-editor state/transition labels already do DE+EN.

Also: the Users screen is now a Nextcloud-style table; role *permissions* live on a separate `/admin/roles` screen; Gremium membership is managed per-Gremium in the Gremien admin (not via a per-user gremium dropdown). See [[nextcloud-parity-ui]], [[antragsplattform-backlog]].
