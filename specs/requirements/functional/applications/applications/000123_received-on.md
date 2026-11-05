---
id: "000123"
title: The received date is at most 365 days back
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The received date is at most 365 days back

`received_on` of a captured Antrag is at most 365 days in the past, else 422
`received_on_too_old`. A deadline "ab Einreichung" counts from `received_on` when it is set.
