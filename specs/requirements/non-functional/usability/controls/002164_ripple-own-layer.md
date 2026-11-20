---
id: "002164"
title: The ripple runs on its own composited layer
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/src/lib/press-ripple/press-ripple.spec.ts:PressRipple"
implementation:
  - frontend/vendor/ui-kit/src/lib/press-ripple/press-ripple.ts
  - frontend/vendor/ui-kit/src/styles/base.scss
scope:
  - frontend/vendor/ui-kit
---

# The ripple runs on its own composited layer

The ripple of a press (001314) must grow as a circle that changes only `transform` and fade
out by `opacity`, on a layer of its own above the pressed element, in its shape. An element
with a part that shows the press (`data-press-surface`, for example the pill of a navigation
entry) must ripple in that part, from its centre. Inside a popover or an open dialog, where a
layer would be under the top layer, the ripple of 001314 applies.

Reason: The ripple animated a custom property of the background. The browser paints that on the
main thread, so the ripple stood still while a new page rendered, exactly when a press starts a
navigation. A transform runs on the compositor.

Test: The tests of the press ripple check the layer, its shape, the part that shows the press,
the fade and the fallback in a popover. A person checks the look on recordings in both themes
and in the display settings.
