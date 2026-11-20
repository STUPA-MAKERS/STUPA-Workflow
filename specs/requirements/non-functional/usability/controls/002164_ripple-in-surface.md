---
id: "002164"
title: The ripple is the ripple of Angular Material inside the pressed surface
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/src/lib/press-ripple/press-ripple.spec.ts:PressRipple"
  - "frontend/vendor/ui-kit/src/styles/touch.spec.ts:TouchRules"
implementation:
  - frontend/vendor/ui-kit/src/lib/press-ripple/press-ripple.ts
  - frontend/vendor/ui-kit/src/styles/base.scss
  - frontend/vendor/ui-kit/src/styles/_press.scss
scope:
  - frontend/vendor/ui-kit
---

# The ripple is the ripple of Angular Material inside the pressed surface

The ripple of a press (001314) must be drawn by the ripple of Angular Material
(`RippleRenderer` of `@angular/material/core`), in a box that is a child of the pressed
surface. The box must fill the surface, take its corners and clip the circle, so that the
ripple moves, scrolls and leaves the page with the surface. An element with a part that shows
the press (`data-press-surface`, for example the pill of a navigation entry) must ripple in
that part, from its centre. A tab must ripple as a pill (`--press-radius`). The circle must
start at the point of the press, or at the centre for Enter and Space. After a short tap the
circle must grow to its end and then fade. A held press must stay until the release. A touch
that turns into a scroll (a move of more than 8 px, or a cancel by the browser) must fade the
ripple at once. A disabled element must not ripple. When a view transition starts, the circle
must show its end, because the still picture of the transition would hold it in the middle of
its growth. A table row keeps the CSS ripple of 001314, because a row cannot hold a box.

Reason: Our own ripples did not work on a phone. The CSS ripple depends on `:active`, which a
phone sets late or not at all on a short tap, and it is painted on the main thread. A ripple on
a layer of its own above the page did not move with its row on a scroll or a pull to refresh,
and it stayed after the press. The ripple of Angular Material is tested on phones and lives
inside the surface, so it has neither fault (decision 2026-11-20: MatRipple instead of an own
ripple; Angular Material is used for this part only).

Test: The tests of the press ripple check the box in the surface, the colour, the growth to
the end of a short tap, the hold, the fade on a drag and on a cancel, the pill shape, the
disabled element, the key press and the table row. A person checks the look on recordings of a
phone in both themes and in the display settings.
