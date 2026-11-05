---
id: "000242"
title: A status revert works only from the reverted state
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
  - backend/app/modules/config_revision
---

# A status revert works only from the reverted state

A revert of a status change works only while the Antrag is still in the target state of that
change, else 409 `stale_revert`. Sent mails and webhooks stay sent.
