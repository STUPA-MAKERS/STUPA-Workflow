---
id: "001312"
title: The attendance average counts the pool seats
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.spec.ts:poolRows"
implementation:
  - frontend/src/app/features/gremien/gremien.util.ts
scope:
  - frontend/src/app/features/gremien/gremium-attendance
---

# The attendance average counts the pool seats

The line "Ø anwesend je Sitzung" of the attendance matrix must count the present members and
the pool seats of the rows that show. This is the present count of a meeting (000946).

Reason: The Beschlussfähigkeit knows one present count, and the pool seats are part of it.

Test: A frontend component test reads the average of a month with a pool seat.
