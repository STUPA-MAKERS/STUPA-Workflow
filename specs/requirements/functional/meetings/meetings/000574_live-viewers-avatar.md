---
id: "000574"
title: A live viewer shows with the own avatar
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
tests:
  - "backend/tests/unit/test_livevote_presence.py"
  - "frontend/src/app/features/meetings/meeting-page/meeting-page.component.spec.ts"
  - "frontend/src/app/features/meetings/attendance-sheet/attendance-sheet.component.spec.ts"
implementation:
  - backend/app/modules/livevote/presence.py
  - backend/app/modules/livevote/events.py
  - frontend/src/app/features/meetings
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - frontend/src/app/core/ws
---

# A live viewer shows with the own avatar

The `viewers` event must carry the principal id and the display name of each viewer. Each list of
live viewers must show each person with the avatar of that principal, followed by the name. This
applies to the "Live dabei" list of the attendance sheet and to the popover of the live chip.

Reason: The attendance list shows the profile picture of a person, but the live list showed the
same person with initials only, because the event carried names without ids.

Test: A unit test checks that the event holds id and name per viewer. A component test checks that
both lists render an avatar with the principal id.
