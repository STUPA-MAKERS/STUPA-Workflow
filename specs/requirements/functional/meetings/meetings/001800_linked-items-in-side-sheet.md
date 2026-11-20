---
id: "001800"
title: The linked rows of an item are in a side sheet
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/features/meetings/meeting-page/meeting-page.component.spec.ts:MeetingPageComponent"
implementation:
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.ts
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.html
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.scss
scope:
  - frontend/src/app/features/meetings
---

# The linked rows of an item are in a side sheet

The meeting page must not show the linked rows of the open item (the Antrag, the Haushaltsplan,
the to-dos and the other links) above the text of the item. At every width they must be in a
side sheet "Verknüpft mit TOP", in the same way as the vote cards (spec 001460).

1. The sheet opens at the end of the page. On a phone it is a bottom sheet.
2. Above the phone width a small tab at the end edge of the window opens the sheet while an
   item is open. It shows a link icon and no number. When the tab of the votes also shows, the
   two tabs stand one above the other.
3. On a phone the menu (⋮) of the page has the entry "Verknüpft mit TOP". The entry "Verknüpft"
   opens the links of the meeting (spec 000551).
4. The head of the sheet has "Verknüpfen" and "To-Do anlegen" when the person may do them.
5. When nothing is linked, the sheet shows the empty state "Nichts verknüpft".
6. The text of the item starts at the top of the page.

Reason: The linked rows pushed the protocol text down on every item. They are looked at now
and then, the text is the work of the whole item.
