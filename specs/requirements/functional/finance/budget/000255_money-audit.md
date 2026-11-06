---
id: "000255"
title: Every money change is audited and revertable
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/budget
  - backend/app/modules/audit
---

# Every money change is audited and revertable

Every money change writes an audit entry. A revert removes an added booking, transfer or cost
centre, and restores an update from the snapshot. A delete is not revertable.
