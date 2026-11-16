---
id: "000101"
title: A TOP with an Antrag shows the Antrag as its first row
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - frontend/src/app/features/meetings/top-sheet/top-sheet.component.ts
  - frontend/src/app/features/meetings/top-application-lead.util.ts
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.html
  - frontend/src/app/features/meetings/meeting-follow-view.component.html
scope:
  - frontend/src/app/features/meetings
---

# A TOP with an Antrag shows the Antrag as its first row

A TOP that links an Antrag must show the Antrag as the first row of its to-do list, as a card.
The title of such a TOP must be renamable.

The linked rows (the Antrag, the Haushaltsplan and the to-dos) must stand above the title of the
TOP, for a manager and for a member, in a live and in a closed meeting, on a desktop and on a
phone.
