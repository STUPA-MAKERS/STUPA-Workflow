---
id: "000292"
title: The audit chain is checked every night
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/worker/audit_verify.py
  - backend/worker/main.py
  - backend/app/modules/audit/router.py
scope:
  - backend/app/modules/audit
  - backend/worker
---

# The audit chain is checked every night

The worker must check the hash chain every night at 04:30 and after every restore. A holder of
`audit.verify` must be able to start a check, at most once in 5 minutes. The store must keep
the first failed check of each break.
