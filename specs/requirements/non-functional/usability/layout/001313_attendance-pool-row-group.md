---
id: "001313"
title: The pool substitutes are an own row group
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.spec.ts:poolRows"
implementation:
  - frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.html
  - frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.scss
scope:
  - frontend/src/app/features/gremien/gremium-attendance
---

# The pool substitutes are an own row group

The pool rows (001310) of the attendance matrix must follow the member rows as an own row
group with the title "Pool-Vertretungen" in the look of a section title. The title must have
no count. On a phone the pool cards must follow the member cards under the same title. The
sort must order each group. The chip "Rolle" must have the choice "Pool-Vertretung", which
shows only the pool rows. A choice of a member role must show no pool row.

Reason: The quota order of the members stays readable, and the pool substitutes are easy to
find.

Test: Frontend component tests of the matrix on a desktop and on a phone.
