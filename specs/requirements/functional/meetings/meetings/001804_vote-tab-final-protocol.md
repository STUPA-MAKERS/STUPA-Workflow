---
id: "001804"
title: A closed meeting keeps the vote tab
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

# A closed meeting keeps the vote tab

Above the phone width the tab "Abstimmungen" at the end edge (spec 001460) must show for every
open item, also when the item has no vote and also in a closed meeting with a final protocol.
In a closed meeting it shows for the minute-taker too. The sheet then shows the votes read-only
or the empty state "Keine Abstimmungen" (spec 001802).

Reason: The votes of a finished meeting are looked up later, and the tab is the one place where
they open.
