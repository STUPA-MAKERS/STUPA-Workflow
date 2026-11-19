---
id: "001305"
title: The status in the head of a page is a badge
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/meetings/meeting-head/meeting-head.component.spec.ts:statusBadge"
implementation:
  - frontend/vendor/ui-kit/src/lib/status-text/status-text.component.ts
  - frontend/src/app/features/meetings/meeting-head/meeting-head.component.html
scope:
  - frontend/vendor/ui-kit
  - frontend/src/app
---

# The status in the head of a page is a badge

The status in the head of a page or a detail must be a badge: a pill tinted in the colour of
the status, centred on its line. This holds beside the title of the meeting head and of an admin
page, and in the line below the title of a detail (Antrag, Rechnung, Buchung, Ticket,
Abstimmung). In very high contrast the badge must have no tint and must keep the white edge of
a state (000605). The status in the phone bar of the meeting head must stay text, because the
bar has one small line below the title.

Reason: Status text on the baseline of the larger title sat low beside it, and in very high
contrast its edge box looked moved down. One look for every head keeps the pages alike.

Test: A kit unit test that finds the badge class, and a frontend unit test that finds the badge
in the meeting head.
