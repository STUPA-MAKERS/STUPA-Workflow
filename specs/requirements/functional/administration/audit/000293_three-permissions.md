---
id: "000293"
title: Read, check and revert are separate permissions
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/audit
---

# Read, check and revert are separate permissions

`audit.read` must be the permission to read the log, `audit.verify` to run a chain check and
`audit.revert` to undo a change. Each route must need exactly its permission.
