---
id: "001310"
title: The attendance matrix shows the pool substitutes
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "backend/tests/unit/modules/gremien_overview/test_gremien_service.py:test_attendance_pool_rows"
  - "backend/tests/integration/modules/gremien/test_gremien_tab.py:test_attendance_matrix"
implementation:
  - backend/app/modules/gremien_overview/service.py
  - frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.ts
scope:
  - backend/app/modules/gremien_overview
  - frontend/src/app/features/gremien/gremium-attendance
---

# The attendance matrix shows the pool substitutes

The attendance matrix of a Gremium (tab "Anwesenheit") must have a row for each pool
substitute of the Gremium (000112): each person with an entry in the substitute pool, and
each person who took a pool seat (000113) in the range. A row must show also a pool
substitute without a seat in the range. A pool substitute who is no member must have no
member row, unless the range holds a present, excused or transferred meeting of that person
as a member. A member in the pool must have a member row and a pool row.

Reason: The Gremium must see who represents its members, and how often.

Test: A backend unit test and an integration test read the matrix of a Gremium with a pool
substitute who is no member, a member in the pool and a pool entry without a seat.
