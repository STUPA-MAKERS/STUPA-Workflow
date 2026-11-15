---
id: "000948"
title: Each Gremium has its own start month of the term
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/livevote/test_meeting_periods_unit.py:test_absences_count_in_the_term_of_the_gremium"
  - "frontend/src/app/pages/admin/committees/gremium-dialog/gremium-dialog.component.spec.ts:termStartMonth"
implementation:
  - backend/app/modules/gremien/models.py
  - backend/app/modules/meetings/absence.py
  - backend/app/modules/admin/service/gremien.py
  - backend/migrations/versions/a7d3e9b15c64_gremium_term_start_month.py
scope:
  - backend/app/modules/gremien
  - backend/app/modules/meetings
  - backend/app/modules/gremien_overview
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# Each Gremium has its own start month of the term

A Gremium must have the setting `termStartMonth` (1 to 12). A term of the Gremium must start on
the first day of this month and must run one year. The count of the unexcused absences
(000920) must use the value of the Gremium. The value `termStartMonth` of the meeting settings
(000906) must be only the start value of a new Gremium. Each Gremium that exists must get the
value of the meeting settings.

Reason: The Amtszeit is a rule of the Satzung of one Gremium. Two Gremien can have different
terms.

Test: A backend unit test counts the absences of two Gremien with different start months.
