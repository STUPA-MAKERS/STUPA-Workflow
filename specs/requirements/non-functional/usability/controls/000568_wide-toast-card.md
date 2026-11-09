---
id: "000568"
title: A wide-screen toast is the same glass card
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.scss
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.html
scope:
  - frontend/vendor/ui-kit
---

# A wide-screen toast is the same glass card

On a screen wider than a phone, a toast must look like the phone toast (000565): the tinted
glass card with the round tile and the centred message. An action with an icon must be the
round icon button of 000566.

The toasts must stay at the bottom end of the window, one above the other, each 24rem wide
at most. Each toast must have a close button. The close button must be a round tonal icon
button of 40px, like the action button.

Reason: One toast must look the same on every width. A mouse cannot swipe, so the close
button stays on a wide screen.
