---
id: "001801"
title: A tab at the end edge opens the attendance
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/meetings/meeting-page/meeting-page.component.spec.ts:MeetingPageComponent"
implementation:
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.ts
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.html
scope:
  - frontend/src/app/features/meetings
---

# A tab at the end edge opens the attendance

Above the phone width the meeting page must show a small tab "Anwesenheit" at the end edge of
the window. It opens the sheet "Anwesenheit", in addition to the chip of the dock and the entry
"Anwesenheit erfassen" of the menu (⋮). It stands below the tabs of the votes (spec 001460) and
of the linked rows (spec 001800), and it hides while the sheet is open.

Reason: The edge tabs are the one place where the sheets of the page open.
