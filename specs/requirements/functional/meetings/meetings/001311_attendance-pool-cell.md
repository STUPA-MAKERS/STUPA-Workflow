---
id: "001311"
title: A pool cell counts the pool seats
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.spec.ts:poolRows"
  - "frontend/src/app/features/gremien/attendance-detail/attendance-detail.component.spec.ts:poolSeats"
  - "backend/tests/integration/modules/gremien/test_gremien_tab.py:test_pool_attendance_detail"
implementation:
  - frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.html
  - frontend/src/app/features/gremien/attendance-detail/attendance-detail.component.ts
  - backend/app/modules/gremien_overview/service.py
scope:
  - frontend/src/app/features/gremien
  - backend/app/modules/gremien_overview
---

# A pool cell counts the pool seats

A cell of a pool row (001310) must show the pool seats of the month and the closed meetings
of the month, for example "1/2", with the colour of a member cell. The column "Gesamt" of a
pool row must show the sum of the seats and of the meetings without a quota. A pool row must
show no role and no unexcused absences. A click on a pool cell must open the meetings of the
month with the state "Vertreten" and the name of the represented member, or "Kein Sitz".

Reason: A quota reads as an attendance duty, and a pool substitute has no such duty.

Test: Frontend component tests of the matrix and of the popover, and a backend integration
test of the pool detail route.
