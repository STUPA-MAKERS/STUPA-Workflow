---
id: "001804"
title: The vote tab shows for every person, always
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "frontend/src/app/features/meetings/meeting-page/meeting-page.component.spec.ts:MeetingPageComponent"
implementation:
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.ts
scope:
  - frontend/src/app/features/meetings
---

# The vote tab shows for every person, always

Above the phone width the tab "Abstimmungen" at the end edge (spec ui-kit:001460) must show for
every person who opens the meeting page, the minute-taker and the managers included. It must
show in every state of the meeting (planned, live, closed with a final protocol), also when the
open item has no vote and also when no item is open. It hides only while its sheet is open, and
the page shows no vote while the feature "Abstimmungen" is off (spec 000758).

The sheet then shows the votes or the empty state "Keine Abstimmungen" (spec ui-kit:001802).

Reason: The tab depended on the role and on the minute-taker of the moment, so after a handover
the same person saw it at one time and not at another. One fixed place for every person is
easier to find.
