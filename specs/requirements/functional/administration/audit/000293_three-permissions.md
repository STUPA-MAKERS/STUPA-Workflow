---
id: "000293"
title: Read, check and revert are separate permissions
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/audit
---

# Read, check and revert are separate permissions

`audit.read` reads the log. `audit.verify` runs a chain check. `audit.revert` undoes a
change. Each route needs exactly its permission.
