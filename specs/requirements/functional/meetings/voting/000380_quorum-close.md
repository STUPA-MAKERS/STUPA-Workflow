---
id: "000380"
title: An unmet quorum blocks the manual close
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/voting
  - backend/worker
---

# An unmet quorum blocks the manual close

A manual close without the quorum must answer 409. The cron must close an overdue vote, count
it as failed and fire the `fail` branch.

Reason: Else the Antrag stays in the vote state forever.
