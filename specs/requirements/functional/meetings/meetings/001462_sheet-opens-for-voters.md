---
id: "001462"
title: The vote sheet opens by itself for a voter
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/meetings/meeting-page/meeting-page.component.spec.ts:MeetingPageComponent"
implementation:
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.ts
scope:
  - frontend/src/app/features/meetings
---

# The vote sheet opens by itself for a voter

Above the phone width, when a vote of the open item opens, the side sheet "Abstimmungen"
(001460) must open by itself for a person who may vote in it and has not voted yet.

1. The sheet opens once for each vote. When the person closes it, it stays closed.
2. For the lead and the minute-taker without a vote the sheet does not open by itself. The
   badge of the dock shows the open vote.

Reason: Without the column a voter on a laptop could miss the open vote. The minute-taker
types during the vote, and a sheet over the text would stop the typing.
