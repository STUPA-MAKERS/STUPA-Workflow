---
id: "000920"
title: The Gremium page counts the unexcused absences of a term
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/app/modules/meetings/absence.py
  - backend/app/modules/gremien_overview/service.py
  - frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.ts
scope:
  - backend/app/modules/gremien_overview
  - frontend/src/app/features/gremien
---

# The Gremium page counts the unexcused absences of a term

The attendance view of a Gremium must show for each member the number of closed `ordinary`
meetings of the current term with the status `absent`. A term must start on the first day of
the `termStartMonth` of the Gremium (000948).

Reason: A member loses the Mandat after a fixed number of unexcused absences in one Amtszeit.

Test: An integration test of the attendance route over two terms.
