---
id: "000580"
title: The add buttons of a card look like its chips with a dashed border
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/features/todos/card-detail/todo-card-detail.component.spec.ts:draws the add buttons of the assignees and the labels as dashed chips"
implementation:
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.scss
scope:
  - frontend/src/app/features/todos/card-detail
---

# The add buttons of a card look like its chips with a dashed border

In the card detail, the button that adds an assignee and the button that adds a label must have
the height, the radius and the type of the chips beside them. Both must have a dashed border.
The button that adds an assignee shows only the plus icon, as a square of the chip height.

Reason: A button that adds an item to a row of chips is read as the next, empty chip. A solid,
higher box beside the chips looks like a different control.

Test: A unit test renders the card detail with write access and expects the class of the
dashed add button on the assignee button and on the label button.
