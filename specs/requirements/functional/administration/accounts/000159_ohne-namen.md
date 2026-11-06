---
id: "000159"
title: An account without a name shows Ohne Namen
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/shared/person-label.util.ts
scope:
  - backend/app/modules/auth
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# An account without a name shows Ohne Namen

An account without name and e-mail must show as "Ohne Namen". The `sub` must show only in the
admin detail.
