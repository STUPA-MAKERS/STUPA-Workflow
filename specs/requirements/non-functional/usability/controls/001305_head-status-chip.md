---
id: "001305"
title: The status in the head of a page is a chip
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/meetings/meeting-head/meeting-head.component.spec.ts:statusChip"
implementation:
  - frontend/vendor/ui-kit/src/lib/status-text/status-text.component.ts
  - frontend/src/app/features/meetings/meeting-head/meeting-head.component.html
scope:
  - frontend/vendor/ui-kit
  - frontend/src/app
---

# The status in the head of a page is a chip

The status in the head of a page or a detail must be a chip: the grey pill of the app chips with the text in
the colour of the status, centred on its line. This holds beside the title of the meeting head and of an admin
page, and in the line below the title of a detail (Antrag, Rechnung, Buchung, Ticket,
Abstimmung). In very high contrast the chip must have no fill and must keep the white edge of
a state (000605). The status in the phone bar of the meeting head must stay text, because the
bar has one small line below the title.

Reason: Status text on the baseline of the larger title sat low beside it, and in very high
contrast its edge box looked moved down. One look for every head keeps the pages alike.

Test: A kit unit test that finds the chip class, and a frontend unit test that finds the chip
in the meeting head.
