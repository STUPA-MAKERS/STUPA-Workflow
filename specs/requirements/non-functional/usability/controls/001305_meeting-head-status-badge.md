---
id: "001305"
title: The status beside the meeting title is a badge
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/meetings/meeting-head/meeting-head.component.spec.ts:statusBadge"
implementation:
  - frontend/src/app/features/meetings/meeting-head/meeting-head.component.scss
scope:
  - frontend/src/app/features/meetings/meeting-head
---

# The status beside the meeting title is a badge

The status beside the title of the meeting head must be a badge: a pill tinted in the colour of
the status, centred on the title line. In very high contrast the badge must have no tint and
must keep the white edge of a state (000605). The status in the phone bar must stay text
(000399).

Reason: Status text on the baseline of the larger title sat low beside it, and in very high
contrast its edge box looked moved down.

Test: A frontend unit test that reads the size and the centring of the status in the style of
the meeting head.
