---
id: "001350"
title: The buttons of a head form one connected button group
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/vendor/ui-kit/src/lib/button-group/button-group.component.spec.ts:ButtonGroupComponent"
implementation:
  - frontend/vendor/ui-kit/src/styles/button-group.scss
  - frontend/vendor/ui-kit/src/lib/button-group
  - frontend/vendor/ui-kit/src/lib/sheet-bar
  - frontend/vendor/ui-kit/src/lib/page-header
  - frontend/vendor/ui-kit/src/lib/list-detail/list-detail-bar.component.html
  - frontend/src/app/features/meetings/meeting-head
  - frontend/src/app/pages/applications/applications-detail.component.html
  - frontend/src/app/features/apply/status-timeline.component.html
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The buttons of a head form one connected button group

The buttons of a page head, a detail head, the meeting head, the vote head and the detail bar
of a phone must show as one connected button group (Material 3 Expressive, "connected button
group"). Each button must be a tonal surface in the accent container colour, 40 px high, with
its label in medium weight. The buttons must stand 2 px apart. Each button must have a corner
radius of 8 px. The first button must round its start, and the last button must round its end,
to half the height. A button with only an icon must be 48 px wide. The ⋮ menu is the last
button of the group.

A control that is not a button (a language switch) keeps its own look and stands 8 px away
from the buttons. The buttons beside it round their ends towards it.

A destructive button (a rejection) is a tonal surface in the danger container colour with the
danger text. A disabled button has a faint surface and its text at 38 %.

The transition buttons of an Antrag (the detail of an Antrag and the status page of the
applicant) form a group of the same look below the status line.

Reason: Loose text buttons, icon buttons and one filled pill looked different in each head.
One group shows the actions of a head as one control, in the same shape on every page.

Test: The spec of `ButtonGroupComponent` in the ui-kit reads the stylesheet and expects the
8 px inner radius, the outer radius of half the height and the 2 px gap.
