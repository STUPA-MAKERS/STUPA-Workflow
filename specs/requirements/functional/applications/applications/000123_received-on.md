---
id: "000123"
title: The received date is at most 365 days back
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The received date is at most 365 days back

`received_on` of a captured Antrag must be at most 365 days in the past, else the request must
answer 422 `received_on_too_old`. A deadline "ab Einreichung" must count from `received_on`
when it is set.
