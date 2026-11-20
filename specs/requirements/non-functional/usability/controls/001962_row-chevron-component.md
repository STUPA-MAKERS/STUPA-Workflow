---
id: "001962"
title: Every row arrow is app-row-chevron
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/src/app/shared/ui/row-chevron
  - frontend/src/app/row-chevron.templates.spec.ts
scope:
  - frontend/src/app/
---

# Every row arrow is app-row-chevron

The arrow of a row must be `app-row-chevron`:

- A row that opens a page or a detail shows the arrow without `open`. It points right, it is
  quiet (muted text colour, 17px), and it pulls into the end padding of the row by
  `--space-2`, so it lines up with the edge of the list.
- A row or a toggle that opens in place (a position of the cost list, the values of a history
  entry, an expandable row) shows the arrow with `[open]`. It points down and turns up while the
  row is open. Without motion (`display` setting) it turns without the animation.

An app template must not draw a row arrow itself with `app-icon`. A tree that turns its arrow
from right to down and the caret of a select are not row arrows.

Reason: Seven templates drew the arrow of a row themselves, with 17px or 18px, with or without
the pull into the padding, and four drew the arrow that turns with their own class and their own
animation. One component keeps the size, the place and the motion the same.

Test: `frontend/src/app/row-chevron.templates.spec.ts` fails on a hand-drawn row arrow.
`row-chevron.component.spec.ts` checks both forms. Screenshot review of the Buchungen list and
the positions of an Antrag, light, dark and very high contrast.
