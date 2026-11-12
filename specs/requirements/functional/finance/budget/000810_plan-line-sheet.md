---
id: "000810"
title: A plan line opens in a sheet
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - frontend/src/app/pages/budget
---

# A plan line opens in a sheet

A press on a row of the plan page must open the line in a side sheet. On a phone it must
be a bottom sheet. The sheet must have the fields Ansatz and Erläuterung. The fields must be
read-only when the version is not in `draft`.
