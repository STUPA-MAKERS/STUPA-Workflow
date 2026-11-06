---
id: "000072"
title: Five record types are immutable
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/
---

# Five record types are immutable

`AuditEntry`, `ConfigRevision`, `Ballot`/`SecretBallot`, `FormVersion`/`FlowVersion` and
`ErasureRequest` must have no update and no delete route. A change must make a new row. The
status of an `ErasureRequest` is the one exception: it moves from `open` to `executed` or
`rejected`.

Reason: Each of them is a record of a decision or a proof. Its model docstring gives the
detail.
