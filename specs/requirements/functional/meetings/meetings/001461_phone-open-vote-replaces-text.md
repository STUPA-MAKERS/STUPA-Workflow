---
id: "001461"
title: On a phone an open vote takes the place of the text
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

# On a phone an open vote takes the place of the text

On a phone, while a vote of the open item is open, the page must show the card of that vote in
the place of the text of the item.

1. Every person sees the vote card there: the voters, the lead and the minute-taker.
2. A switch "Abstimmung | Text" above the card shows the text instead, and back. The choice
   holds until the vote ends.
3. When the vote closes or is cancelled, the text comes back.
4. The other votes of the item stay in the side sheet (001460).

Reason: On a phone the vote is the one thing that the person must do now. In a bottom sheet
it is hidden behind a button of the dock, and the text above it is not needed during the
vote.
