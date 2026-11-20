---
id: "002012"
title: Every back button of a head is a round tonal button
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/vendor/ui-kit/src/lib/list-detail/list-detail-bar.component.scss
  - frontend/vendor/ui-kit/src/styles/button-group.scss
  - frontend/src/app/features/public-meeting/guest-view.component.html
  - frontend/src/app/features/meetings/meeting-head
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Every back button of a head is a round tonal button

The back button of a head must be a round icon button: a circle of 40 px in the tonal colour
of the buttons of the head, with the arrow in its centre. This applies on a phone to the bar of every detail (an Antrag, a to-do card, a Sitzung)
and on a wide screen to every back button in a head, the head of a Sitzung included. All back
buttons must have the same size, the same circle and the same press feedback. In the very high
contrast mode (000605) the circle has the yellow edge of a control.

Reason: The back buttons looked different from page to page, and on the solid bar (002010) a
bare arrow lacks a clear target.

Test: Screenshots of the heads of an Antrag, a to-do card and a Sitzung on a phone and on a wide
screen, in the light and the dark theme and in the very high contrast mode.
