---
id: "000380"
title: An unmet quorum blocks the manual close
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/voting
  - backend/worker
---

# An unmet quorum blocks the manual close

A manual close without the quorum answers 409. The cron closes an overdue vote, counts it as
failed and fires the `fail` branch.

Reason: Else the Antrag stays in the vote state forever.
