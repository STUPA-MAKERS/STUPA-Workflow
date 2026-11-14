---
id: "000919"
title: An Antrag goes to the first meeting after the Antragsschluss
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/flow
  - backend/app/modules/meetings
---

# An Antrag goes to the first meeting after the Antragsschluss

The flow action `addToNextSession` must choose the next planned `ordinary` meeting of the
Gremium that starts at least `motionDeadlineDays` days later (000917). Without such a meeting
the action must add no TOP.

Reason: The Geschäftsordnung puts an Antrag on the agenda only when it arrives ten days before
the Sitzung.

Test: An integration test of the action with two planned meetings.
