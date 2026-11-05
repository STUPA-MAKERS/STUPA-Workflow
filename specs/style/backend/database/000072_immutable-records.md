---
id: "000072"
title: Five record types are immutable
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
---

# Five record types are immutable

`AuditEntry`, `ConfigRevision`, `Ballot`/`SecretBallot`, `FormVersion`/`FlowVersion` and
`ErasureRequest` have no update and no delete route. A change makes a new row.

Reason: Each of them is a record of a decision or a proof. Its model docstring gives the
detail.
