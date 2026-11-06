---
id: "000369"
title: Each admin page has its own permission
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# Each admin page has its own permission

Each admin page needs its own `admin.*` permission. A read that several pages share accepts
any of their permissions.
