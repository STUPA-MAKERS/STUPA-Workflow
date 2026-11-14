---
id: "000917"
title: The meeting settings hold the periods of the Geschäftsordnung
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/admin
  - backend/app/modules/meetings
  - frontend/src/app/pages/admin
---

# The meeting settings hold the periods of the Geschäftsordnung

The meeting settings must hold these values with these start values: `inviteDaysOrdinary` 7,
`inviteDaysExtraordinary` 3, `protocolDraftDays` 14, `lateExcuseDays` 7, `absenceLimit` 3,
`circularMinDays` 3 and `termStartMonth` 10. The admin page "Sitzungen" must edit them with the
permission `admin.deadlines`.

Reason: The periods come from the Geschäftsordnung, and an admin must be able to follow a
change of it without a release.

Test: An integration test of the settings route.
