---
id: "001460"
title: The vote cards of an item are in a side sheet
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/meetings/meeting-page/meeting-page.component.spec.ts:MeetingPageComponent"
implementation:
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.ts
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.html
  - frontend/src/app/features/meetings/session-dock/session-dock.component.html
scope:
  - frontend/src/app/features/meetings
---

# The vote cards of an item are in a side sheet

The meeting page must not show a column for the vote cards. At every width the vote cards of
the open item and "Beschlussfrage hinzufügen" must be in a side sheet "Abstimmungen".

1. The sheet opens at the end of the page. On a phone it is a bottom sheet.
2. Above the phone width a small tab at the end edge of the window opens the sheet for every
   person but the minute-taker. It shows
   the number of votes of the open item and takes the accent colour while a vote is open.
3. Only the minute-taker has a vote button in the dock. Its badge shows the number of votes
   of the open item and is highlighted while a vote is open.
4. On a phone, for every other person and when there is no dock, the menu (⋮) of the page
   has the entry "Abstimmungen".
5. The text of the item takes the width that the column had.

Reason: The column was mostly empty and took a third of the width from the protocol text. A
vote is a short moment of an item, the text is the work of the whole item.
