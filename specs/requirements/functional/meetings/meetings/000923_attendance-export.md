---
id: "000923"
title: The attendance of a Gremium exports as XLSX
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/gremien_overview
  - frontend/src/app/features/gremien
---

# The attendance of a Gremium exports as XLSX

A person with `session.manage` in the Gremium must be able to export the attendance of a date
range as XLSX. The file must have one row for each person with the number of closed `ordinary`
meetings with the status `present`. A pool substitute must have an own row with the number of
seats taken.

Reason: The Sitzungsgeld of a Semester is paid from the attendance lists.

Test: An integration test of the export route.
