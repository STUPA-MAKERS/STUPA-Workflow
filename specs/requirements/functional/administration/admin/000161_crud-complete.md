---
id: "000161"
title: Every entity has create, read, update and delete
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/admin/router.py
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
  - backend/app/modules/
---

# Every entity has create, read, update and delete

Every domain entity must support create, read, update and delete for the admin or the holder of
the permission. A conditional delete must answer 409 and must never cascade silently. The
immutable record types are the only exception.
