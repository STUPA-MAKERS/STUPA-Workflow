---
id: "000291"
title: An audit entry is written in the same transaction
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/audit
scope:
  - backend/app/modules/audit
---

# An audit entry is written in the same transaction

An audit entry must be written only through `record()`. `record()` runs in the transaction of
the change, so the entry and the change commit together.
