---
id: "000161"
title: Every entity has create, read, update and delete
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
  - backend/app/modules/
---

# Every entity has create, read, update and delete

Every domain entity supports create, read, update and delete for the admin or the holder of
the permission. A conditional delete answers 409, never a silent cascade. The immutable record
types are the only exception.
