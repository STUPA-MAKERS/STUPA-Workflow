---
id: "000292"
title: The audit chain is checked every night
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/audit
  - backend/app/worker
---

# The audit chain is checked every night

The worker checks the hash chain every night at 04:30 and after every restore. A holder of
`audit.verify` can start a check, at most once in 5 minutes. The store keeps the first failed
check of each break.
