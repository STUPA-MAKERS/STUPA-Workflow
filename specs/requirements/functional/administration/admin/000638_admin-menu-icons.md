---
id: "000638"
title: Each entry of the admin menu has its own icon
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - frontend/src/app/pages/admin/admin-frame
---

# Each entry of the admin menu has its own icon

No two entries of `ADMIN_PAGES` must have the same icon. Gruppen-Zuordnung has the icon
`link`, Agent-Zugänge has the icon `handshake`, and Anmeldung keeps the icon `key`.

Reason: The three entries all show the key, so the icon does not help to find an entry.

Test: `frontend/src/app/pages/admin/admin-frame/admin-pages.spec.ts`: the icons of
`ADMIN_PAGES` are unique.
