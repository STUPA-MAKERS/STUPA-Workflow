---
id: "000255"
title: Every money change is audited and revertable
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget
  - backend/app/modules/audit
scope:
  - backend/app/modules/budget
  - backend/app/modules/audit
---

# Every money change is audited and revertable

Every money change must write an audit entry. A revert must remove an added booking, transfer
or cost centre, and must restore an update from the snapshot. A delete must not be revertable.
