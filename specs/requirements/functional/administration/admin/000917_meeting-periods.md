---
id: "000917"
title: The meeting settings hold the periods of the Geschäftsordnung
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/meetings/periods.py
  - backend/app/modules/admin/router.py
  - frontend/src/app/pages/admin/deadlines/meeting-periods/meeting-periods.component.ts
scope:
  - backend/app/modules/admin
  - backend/app/modules/meetings
  - frontend/src/app/pages/admin
---

# The meeting settings hold the periods of the Geschäftsordnung

The meeting settings must hold these values with these start values: `inviteDaysOrdinary` 7,
`inviteDaysExtraordinary` 3, `lateExcuseDays` 7, `absenceLimit` 3, `circularMinDays` 3 and
`termStartMonth` 10. The admin page "Sitzungen" must edit them with the permission
`admin.deadlines`. The settings must hold no value that the platform does not use.

Reason: The periods come from the Geschäftsordnung, and an admin must be able to follow a
change of it without a release. A period for the draft of the protocol is not in the list,
because the platform does nothing with it: a stored value without an effect looks like a rule.

Test: An integration test of the settings route.
