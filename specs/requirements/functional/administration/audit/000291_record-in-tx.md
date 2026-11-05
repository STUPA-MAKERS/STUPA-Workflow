---
id: "000291"
title: An audit entry is written in the same transaction
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/audit
---

# An audit entry is written in the same transaction

Write an audit entry only through `record()`. It runs in the transaction of the change, so
the entry and the change commit together.
