---
id: "000096"
title: There is no preparation page
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - frontend/src/app/features/meetings/meetings-list/meetings-list.component.ts
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.ts
scope:
  - frontend/src/app/features/meetings
---

# There is no preparation page

A meeting row must open the meeting page. "Sitzung eröffnen" must stand where "Sitzung
schließen" stands: above the phone width as a button in the header of the meeting, on the phone
as an item of the ⋮ menu. It must not be in the ⋮ menu above the phone width. The open must start
at the first TOP.

Reason: The opening is the main action of a planned meeting, as the close is of a live one, so
both take the same place.

Test: `meeting-page.component.spec.ts` checks the header button, the phone menu item and that the
menu above the phone width has no opening.
