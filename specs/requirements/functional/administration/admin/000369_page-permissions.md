---
id: "000369"
title: Each admin page has its own permission
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# Each admin page has its own permission

Each admin page must need its own `admin.*` permission. A read that several pages share must
accept any of their permissions.
