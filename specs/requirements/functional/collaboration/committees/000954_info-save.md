---
id: "000954"
title: An Info save is versioned and audited
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation: null
scope:
  - backend/app/modules/gremien_overview
  - backend/app/modules/audit
---

# An Info save is versioned and audited

The text and the links must save together in one request. The request must send the version
that the editor read. A save against an older version must fail with 409
`gremium_info_version_conflict`. Each save must write one audit entry `gremium_info_update`.
The tab must show who changed the Info last and when.

Reason: Two managers who edit at the same time must not overwrite each other without a
warning.

Test: A backend test of the 409 and of the audit entry.
