---
id: "000941"
title: The absence count and the export offer each term
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/gremien_overview/test_gremien_service.py:test_attendance_of_a_past_term_counts_this_term_only"
  - "backend/tests/unit/modules/gremien_overview/test_gremien_router.py:test_attendance_passes_the_term"
  - "frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.spec.ts:term"
implementation:
  - backend/app/modules/gremien_overview/service.py
  - frontend/src/app/features/gremien
scope:
  - backend/app/modules/gremien_overview
  - backend/app/modules/meetings
  - frontend/src/app/features/gremien
---

# The absence count and the export offer each term

The count of the unexcused absences of a Gremium (000920) and the attendance export must offer
each term in which the Gremium had a meeting. The current term must be the choice at the
start.

Reason: A question about the absences of a member often comes after the end of the Amtszeit.

Test: A backend unit test reads the count of a past term and finds the absences of this term
only.
