---
id: "001462"
title: The vote sheet opens by itself for a voter
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/features/meetings/meeting-page/meeting-page.component.spec.ts:MeetingPageComponent"
implementation:
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.ts
scope:
  - frontend/src/app/features/meetings
---

# The vote sheet opens by itself for a voter

Above the phone width, when a vote of the open item opens, the side sheet "Abstimmungen"
(ui-kit:001460) must open by itself (ui-kit:002284) for a person who may vote in it and has not
voted yet. The key is the vote.

For the lead and the minute-taker without a vote the sheet does not open by itself. The badge
of the dock shows the open vote.

Reason: Without the column a voter on a laptop could miss the open vote. The minute-taker
types during the vote, and a sheet over the text would stop the typing.
