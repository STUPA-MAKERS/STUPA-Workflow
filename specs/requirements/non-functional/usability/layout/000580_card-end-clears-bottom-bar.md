---
id: "000580"
title: The end of a card keeps room above the bottom bar
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.scss
scope:
  - frontend/src/app/features/todos/card-detail
---

# The end of a card keeps room above the bottom bar

On a phone, the details column of an open to-do card must end with `var(--space-6)` (32px)
of free space below its last row. When the column scrolls to its end, the last row (for
example "Punkt hinzufügen") must not touch the bottom bar.

Reason: A row directly on the bottom bar looks cut and is hard to tap without a tap on the bar.

Test: Screenshot of an open card with a long checklist on a phone width, scrolled to the end.
