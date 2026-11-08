---
id: "000421"
title: The start page is a work list with a side sheet
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
implementation:
  - frontend/src/app/pages/dashboard/dashboard.component.ts
scope:
  - frontend/src/app/pages/dashboard
---

# The start page is a work list with a side sheet

The start page must show the work list with the tabs "Offene Aufgaben" and "Meine Anträge",
with at most 25 rows and on the phone at most 5. The side sheet "Heute" must show the live
meeting and the next meetings: 3, on an XL screen 5, on the phone 2. Spec 000550 adds the
due cards of the person to the sheet.
