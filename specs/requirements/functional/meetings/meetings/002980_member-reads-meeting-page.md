---
id: "002980"
title: A member reads the meeting on the meeting page
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "frontend/src/app/features/meetings/meetings.component.spec.ts:MeetingsComponent"
  - "frontend/src/app/features/meetings/meeting-page/meeting-page.component.spec.ts:MeetingPageComponent"
implementation:
  - frontend/src/app/features/meetings/meetings.component.html
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.html
scope:
  - frontend/src/app/features/meetings
---

# A member reads the meeting on the meeting page

A member without the write right and without the manage right must see a meeting on the same
meeting page as the minute-taker, with the same agenda, head, dock, edge tabs and side sheets.
There must not be a second participant view.

The page is read-only for the member. The TOP sheet shows the text of the item as the room
types it, with "Jetzt" on the item that runs now and the name of the minute-taker. The member
casts the vote in the side sheet "Abstimmungen" (ui-kit:001460, 001461), which opens by itself
when a vote opens (001462). The member reports the own attendance and manages the own delegation
in the attendance sheet.

Reason: One page for every role shows a member the same layout as the lead, and a change of the
page reaches every role.

Test: The component spec renders the meeting page for a member without write and manage rights,
and the meeting page spec shows the text of the item to a reader.
